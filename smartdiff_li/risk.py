"""Оценка риска изменений: простые прозрачные эвристики."""
from __future__ import annotations

from pathlib import PurePosixPath

from . import core
from .semantic import Change
from .symbols import is_public

# веса отдельных изменений и пороги уровней живут в ядре (csrc/risk.c, _pycore.py)
NO_TESTS_SCORE = 5.0
SYNTAX_ERROR_SCORE = 60.0

LEVEL_ORDER = ("low", "medium", "high", "critical")


def is_test_path(path: str) -> bool:
    p = PurePosixPath(path)
    return (p.name.startswith("test_") or p.stem.endswith("_test")
            or "tests" in p.parts or "test" in p.parts)


def is_runnable_test(path: str) -> bool:
    p = PurePosixPath(path)
    return p.name.startswith("test_") or p.stem.endswith("_test")


def level_for(score: float) -> str:
    return core.level_for(score)


def change_score(change: Change, direct: int, total: int, broken: int) -> float:
    score = core.change_score(change.change, change.breaking, is_public(change.qualname),
                              is_test_path(change.path), direct, total, broken)
    return round(score, 1)
