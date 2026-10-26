"""Вывод результата анализа: текст для терминала и JSON."""
from __future__ import annotations

import json

from .analysis import Analysis, ChangeImpact

MARKS = {"added": "+", "removed": "-", "moved": ">", "signature": "~", "body": "~", "doc": "."}
TITLES = {
    "added": "added", "removed": "removed", "moved": "moved",
    "signature": "signature changed", "body": "body changed", "doc": "docs only",
}
PREVIEW = 5


def _title(item: ChangeImpact) -> str:
    c = item.change
    if c.kind == "file":
        return f"file {c.change} ({c.details})"
    text = TITLES[c.change]
    if c.change == "signature" and c.breaking:
        text += " [BREAKING]"
    if c.details:
        text += f": {c.details}"
    return text


def _impact_lines(item: ChangeImpact, show_all: bool) -> list[str]:
    lines = []
    shown = item.impacted if show_all else item.impacted[:PREVIEW]
    broken = item.change.change in ("removed", "moved")
    for i in shown:
        arrow = "!!" if broken and i.certain else "<-"
        name = i.module if i.symbol.startswith("<") else f"{i.module}.{i.symbol}"
        notes = []
        if not i.certain:
            notes.append("possible")
        if i.also_changed:
            notes.append("also changed")
        suffix = f"  ({', '.join(notes)})" if notes else ""
        lines.append(f"{'   ' * (i.depth - 1)}        {arrow} {name}  {i.path}:{i.lineno}{suffix}")
    hidden = len(item.impacted) - len(shown)
    if hidden > 0:
        lines.append(f"        ... and {hidden} more (use --all to see them)")
    return lines


def format_text(result: Analysis, show_all: bool = False) -> str:
    out = [f"SmartDiff  {result.label}"]
    parts = []
    semantic = {i.change.path for i in result.items}
    if semantic:
        parts.append(f"{len(semantic)} with semantic changes")
    if result.cosmetic:
        parts.append(f"{len(result.cosmetic)} formatting only")
    if result.unparsable:
        parts.append(f"{len(result.unparsable)} unparsable")
    if result.other_files:
        parts.append(f"{len(result.other_files)} non-Python (not analyzed)")
    out.append("  " + (", ".join(parts) if parts else "no changes"))

    risk = result.risk
    out += ["", f"RISK  {risk.level.upper()} ({risk.score}/100)"]
    out += [f"  - {reason}" for reason in risk.reasons]

    if result.items:
        out += ["", "CHANGES"]
    current = None
    for item in result.items:
        c = item.change
        if c.path != current:
            current = c.path
            out.append(f"  {c.path}")
        name = "" if c.kind == "file" else f"{c.qualname} ({c.kind})  "
        if c.kind == "imports":
            name, title = "imports  ", "changed"
        else:
            title = _title(item)
        out.append(f"    {MARKS[c.change]} {name}{title}")
        out += _impact_lines(item, show_all)

    if result.cosmetic:
        out += ["", "FORMATTING ONLY (no semantic change)"]
        out += [f"  {p}" for p in result.cosmetic]
    if result.unparsable:
        out += ["", "COULD NOT PARSE"]
        out += [f"  {p}" for p in result.unparsable]

    if result.dependents:
        out += ["", "MODULES THAT IMPORT CHANGED CODE"]
        by_distance = sorted(result.dependents.items(), key=lambda kv: (kv[1], kv[0]))
        names = ", ".join(f"{m} ({d})" for m, d in by_distance)
        out.append(f"  {names}")
    if result.tests:
        out += ["", "TESTS TO RUN"]
        out += [f"  {t}" for t in result.tests]
    return "\n".join(out)


def to_dict(result: Analysis) -> dict:
    def impacted(i):
        return {"module": i.module, "symbol": i.symbol, "path": i.path, "line": i.lineno,
                "depth": i.depth, "certain": i.certain, "also_changed": i.also_changed}

    def change(item: ChangeImpact):
        c = item.change
        return {
            "path": c.path, "module": c.module, "symbol": c.qualname, "kind": c.kind,
            "change": c.change, "breaking": c.breaking, "details": c.details,
            "line": c.lineno, "moved_to": c.moved_to, "score": item.score,
            "impacted": [impacted(i) for i in item.impacted],
        }

    return {
        "label": result.label,
        "risk": {"score": result.risk.score, "level": result.risk.level,
                 "reasons": result.risk.reasons},
        "changes": [change(i) for i in result.items],
        "formatting_only": result.cosmetic,
        "unparsable": result.unparsable,
        "non_python": result.other_files,
        "dependent_modules": result.dependents,
        "tests": result.tests,
    }


def format_json(result: Analysis) -> str:
    return json.dumps(to_dict(result), indent=2, ensure_ascii=False)
