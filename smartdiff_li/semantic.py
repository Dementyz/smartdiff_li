"""Семантическое сравнение двух версий файла: что изменилось на самом деле."""
from __future__ import annotations

from dataclasses import dataclass

from . import core
from .symbols import IMPORTS, Param, Symbol

# переносим символ как "moved" только если он не тривиальный
MIN_MOVE_SIZE = 8
MOVABLE_KINDS = ("function", "method", "class")


@dataclass
class Change:
    path: str
    module: str
    qualname: str
    kind: str
    change: str  # added | removed | signature | body | doc | moved
    breaking: bool = False
    details: str = ""
    lineno: int = 0
    old: Symbol | None = None
    new: Symbol | None = None
    moved_to: str | None = None
    whole_file: bool = False


def compare_symbols(path: str, module: str, old: dict[str, Symbol],
                    new: dict[str, Symbol], whole_file: bool = False) -> list[Change]:
    changes = []
    for qualname in old.keys() | new.keys():
        a, b = old.get(qualname), new.get(qualname)
        if qualname == IMPORTS and whole_file:
            continue
        if b is None:
            change = Change(path, module, qualname, a.kind, "removed",
                            lineno=a.lineno, old=a, whole_file=whole_file)
        elif a is None:
            change = Change(path, module, qualname, b.kind, "added",
                            lineno=b.lineno, new=b, whole_file=whole_file)
        elif a.signature != b.signature:
            details, breaking = describe_signature(a, b)
            if a.body != b.body:
                details += "; body changed"
            change = Change(path, module, qualname, b.kind, "signature", breaking,
                            details, b.lineno, a, b)
        elif a.body != b.body:
            change = Change(path, module, qualname, b.kind, "body",
                            lineno=b.lineno, old=a, new=b)
        elif a.doc != b.doc:
            change = Change(path, module, qualname, b.kind, "doc",
                            lineno=b.lineno, old=a, new=b)
        else:
            continue
        changes.append(change)
    changes.sort(key=lambda c: (c.lineno, c.qualname))
    return changes


def signature_break(old: tuple[Param, ...], new: tuple[Param, ...]) -> bool:
    """Ломает ли новая сигнатура существующие вызовы (считает ядро)."""
    return core.signature_break(old, new)


def describe_signature(a: Symbol, b: Symbol) -> tuple[str, bool]:
    if a.kind == "class":
        return "bases or decorators changed", True
    notes = []
    old_names = {p.name: p for p in a.params}
    new_names = {p.name: p for p in b.params}
    removed = [n for n in old_names if n not in new_names]
    if removed:
        notes.append("removed params: " + ", ".join(removed))
    added = [f"{n}{'' if new_names[n].has_default else ' (required)'}"
             for n in new_names if n not in old_names]
    if added:
        notes.append("added params: " + ", ".join(added))
    if any(n in new_names and old_names[n].kind != new_names[n].kind for n in old_names):
        notes.append("param kinds changed")
    if a.is_async != b.is_async:
        notes.append("async changed")
    if a.returns != b.returns:
        notes.append("return annotation changed")
    if a.decorators != b.decorators:
        notes.append("decorators changed")
    breaking = signature_break(a.params, b.params) or a.is_async != b.is_async
    if not notes:
        notes.append("defaults or annotations changed" if not breaking else "params reordered")
    return "; ".join(notes), breaking


def pair_moves(changes: list[Change]) -> list[Change]:
    """Находит удалённые символы, которые появились в другом месте без изменений."""
    added: dict[tuple, list[Change]] = {}
    for c in changes:
        if c.change == "added" and c.kind in MOVABLE_KINDS:
            added.setdefault((c.kind, c.new.signature, c.new.body), []).append(c)

    consumed = set()
    for c in changes:
        if c.change != "removed" or c.kind not in MOVABLE_KINDS:
            continue
        candidates = added.get((c.kind, c.old.signature, c.old.body), [])
        name = c.qualname.rsplit(".", 1)[-1]
        same_name = [t for t in candidates if t.qualname.rsplit(".", 1)[-1] == name]
        if same_name:
            target = same_name[0]
        elif candidates and c.old.size >= MIN_MOVE_SIZE:
            target = candidates[0]
        else:
            continue
        candidates.remove(target)
        consumed.add(id(target))
        c.change = "moved"
        c.new = target.new
        c.moved_to = f"{target.module}:{target.qualname}"
        if target.module == c.module:
            c.details = f"renamed to {target.qualname}"
        else:
            c.details = f"moved to {target.module}"
    return [c for c in changes if id(c) not in consumed]
