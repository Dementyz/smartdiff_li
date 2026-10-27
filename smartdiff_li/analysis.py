"""Анализ диффа: семантические изменения, влияние на остальной код, риск."""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from .gitutil import GitRev, WorkTree, changed_files
from .graph import ProjectGraph, build_graph, module_names
from .risk import (
    LEVEL_ORDER, NO_TESTS_SCORE, SYNTAX_ERROR_SCORE, change_score, is_runnable_test,
    is_test_path, level_for,
)
from .semantic import Change, compare_symbols, pair_moves
from .symbols import extract_symbols

BEHAVIOUR_CHANGES = ("body", "signature", "removed", "moved")


@dataclass
class Impacted:
    module: str
    symbol: str
    path: str
    lineno: int
    depth: int
    certain: bool
    also_changed: bool = False


@dataclass
class ChangeImpact:
    change: Change
    impacted: list[Impacted] = field(default_factory=list)
    score: float = 0.0

    @property
    def direct(self) -> int:
        return sum(1 for i in self.impacted if i.depth == 1)

    @property
    def broken(self) -> int:
        if self.change.change not in ("removed", "moved"):
            return 0
        return sum(1 for i in self.impacted if i.certain)


@dataclass
class Risk:
    score: int
    level: str
    reasons: list[str]


@dataclass
class Analysis:
    label: str
    items: list[ChangeImpact]
    cosmetic: list[str]
    other_files: list[str]
    unparsable: list[str]
    dependents: dict[str, int]
    tests: list[str]
    risk: Risk
    python_files: int = 0


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _parse(source: str | None):
    if source is None:
        return {}
    return extract_symbols(ast.parse(source))


def _impacted(uses, depth: int, changed: set, certain: bool = True) -> list[Impacted]:
    return [Impacted(u.module, u.symbol, u.path, u.lineno, depth, c and certain,
                     (u.module, u.symbol) in changed) for u, c in uses]


def trace_impact(graph: ProjectGraph, change: Change, depth: int,
                 changed: set[tuple[str, str]], all_paths: list[str]) -> list[Impacted]:
    module, qualname = change.module, change.qualname
    if change.change in ("added", "doc") or qualname == "<imports>":
        return []

    if change.kind == "file":
        uses = []
        for name in module_names(change.path, all_paths):
            uses.extend(graph.unresolved.get(name, ()))
        return _impacted([(u, True) for u in uses], 1, changed)

    if change.change in ("removed", "moved"):
        # символа больше нет в этом месте: любая оставшаяся ссылка сломана
        hits = list(graph.references_to(module, qualname, change.kind, attr_names=False))
        seen = {(u.module, u.symbol) for u, _ in hits}
        for use in graph.local_uses(module, qualname, change.kind):
            if (use.module, use.symbol) not in seen:
                hits.append((use, True))
        return _impacted(hits, 1, changed)

    if depth < 1:
        return []
    seeds = graph.references_to(module, qualname, change.kind)
    return [Impacted(mod, sym, graph.modules[mod].path, line, level, certain, (mod, sym) in changed)
            for mod, sym, level, certain, line in graph.trace(module, qualname, depth, seeds)]


def _label(change: Change) -> str:
    if change.kind == "file":
        return change.path
    return f"{change.module}.{change.qualname}"


def _reason(item: ChangeImpact) -> str:
    c = item.change
    name = f"`{_label(c)}`"
    if c.change == "signature":
        text = f"{'breaking ' if c.breaking else ''}signature change in {name}"
    elif c.change == "moved":
        text = f"{name} was moved or renamed"
    else:
        text = f"{name} {c.change}" if c.kind == "file" else f"{c.change} {name}"
    if item.broken:
        text += f", {_plural(item.broken, 'broken reference')}"
    elif item.impacted:
        text += f", used by {_plural(len(item.impacted), 'symbol')}"
    return text


def _assess(items: list[ChangeImpact], tests: list[str], syntax_errors: list[str]) -> Risk:
    total = sum(i.score for i in items) + SYNTAX_ERROR_SCORE * len(syntax_errors)
    reasons = [f"syntax error in {p}" for p in syntax_errors]
    behavioural = [i for i in items
                   if i.change.change in BEHAVIOUR_CHANGES and not is_test_path(i.change.path)]
    if behavioural and not tests:
        total += NO_TESTS_SCORE
    for item in sorted(items, key=lambda i: -i.score)[:3]:
        if item.score >= 3:
            reasons.append(_reason(item))
    if behavioural and not tests:
        reasons.append("no tests found among the affected code")
    score = min(100, round(total))
    level = level_for(score)
    if any(i.broken for i in items) and LEVEL_ORDER.index(level) < LEVEL_ORDER.index("high"):
        level = "high"
    return Risk(score, level, reasons)


def analyze_diff(root: Path, base: str, head: str | None, label: str,
                 depth: int = 3) -> Analysis:
    files = changed_files(root, base, head)
    old_tree = GitRev(root, base)
    new_tree = WorkTree(root) if head is None else GitRev(root, head)
    new_paths = new_tree.python_files()
    graph = build_graph(new_paths, new_tree.read)

    symbol_changes: list[Change] = []
    cosmetic, unparsable, syntax_errors, other = [], [], [], []
    whole: dict[str, tuple[str, str]] = {}  # путь -> (статус, модуль) для целых файлов
    for f in files:
        if not f.path.endswith(".py"):
            other.append(f.path)
            continue
        old_src = None if f.status == "A" else old_tree.read(f.path)
        new_src = None if f.status == "D" else new_tree.read(f.path)
        try:
            new = _parse(new_src)
        except (SyntaxError, ValueError):
            unparsable.append(f.path)
            syntax_errors.append(f.path)
            continue
        try:
            old = _parse(old_src)
        except (SyntaxError, ValueError):
            unparsable.append(f.path)
            continue
        module = graph.module_of(f.path) or module_names(f.path, [*new_paths, f.path])[0]
        is_whole = f.status in ("A", "D")
        if is_whole:
            whole[f.path] = ("added" if f.status == "A" else "removed", module)
        changes = compare_symbols(f.path, module, old, new, whole_file=is_whole)
        if not changes and not is_whole and old_src != new_src:
            cosmetic.append(f.path)
        symbol_changes.extend(changes)

    changes = pair_moves(symbol_changes)
    for path, (status, module) in whole.items():
        members = [c for c in changes if c.path == path and c.whole_file
                   and c.change in ("added", "removed")]
        member_ids = {id(c) for c in members}
        changes = [c for c in changes if id(c) not in member_ids]
        moved = sum(1 for c in changes if c.path == path and c.change == "moved")
        details = _plural(len(members), "symbol") + (f", {moved} moved" if moved else "")
        changes.append(Change(path, module, "<file>", "file", status, details=details))

    changed = {(c.module, c.qualname) for c in changes}
    items = []
    for change in changes:
        item = ChangeImpact(change, trace_impact(graph, change, depth, changed, new_paths))
        item.score = change_score(change, item.direct, len(item.impacted), item.broken)
        items.append(item)
    items.sort(key=lambda i: (i.change.path, i.change.lineno, i.change.qualname))

    changed_modules = {c.module for c in changes if c.module in graph.modules}
    dependents: dict[str, int] = {}
    for module in sorted(changed_modules):
        for dep, dist in graph.dependents(module).items():
            if dep not in changed_modules:
                dependents[dep] = min(dist, dependents.get(dep, dist))

    touched = changed_modules | set(dependents)
    touched |= {i.module for item in items for i in item.impacted}
    tests = {graph.modules[m].path for m in touched
             if m in graph.modules and is_runnable_test(graph.modules[m].path)}
    tests |= {c.path for c in changes if c.change != "removed" and is_runnable_test(c.path)}

    return Analysis(
        label=label, items=items, cosmetic=cosmetic, other_files=other,
        unparsable=unparsable,
        dependents=dict(sorted(dependents.items(), key=lambda kv: (kv[1], kv[0]))), tests=sorted(tests),
        risk=_assess(items, tests, syntax_errors), python_files=len(new_paths),
    )
