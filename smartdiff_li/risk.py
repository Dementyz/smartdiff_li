"""Оценка риска изменений: простые прозрачные эвристики."""
from __future__ import annotations

from pathlib import PurePosixPath

from .semantic import Change
from .symbols import is_public

BASE_SCORE = {"removed": 6.0, "body": 3.0, "moved": 1.0, "added": 0.5, "doc": 0.0}
BREAKING_SIGNATURE = 8.0
COMPATIBLE_SIGNATURE = 2.0
BROKEN_REF_SCORE = 15.0
MAX_BROKEN_REFS = 3
NO_TESTS_SCORE = 5.0
SYNTAX_ERROR_SCORE = 60.0
PRIVATE_FACTOR = 0.5
TEST_FACTOR = 0.2

LEVELS = ((45, "critical"), (25, "high"), (10, "medium"), (0, "low"))
LEVEL_ORDER = ("low", "medium", "high", "critical")


def is_test_path(path: str) -> bool:
    p = PurePosixPath(path)
    return (p.name.startswith("test_") or p.stem.endswith("_test")
            or "tests" in p.parts or "test" in p.parts)


def is_runnable_test(path: str) -> bool:
    p = PurePosixPath(path)
    return p.name.startswith("test_") or p.stem.endswith("_test")


def level_for(score: float) -> str:
    for threshold, level in LEVELS:
        if score >= threshold:
            return level
    return "low"


def change_score(change: Change, direct: int, total: int, broken: int) -> float:
    if change.change == "signature":
        base = BREAKING_SIGNATURE if change.breaking else COMPATIBLE_SIGNATURE
    else:
        base = BASE_SCORE[change.change]
    public = 1.0 if is_public(change.qualname) else PRIVATE_FACTOR
    fan_in = 1 + 0.3 * min(direct, 10) + 0.05 * min(total - direct, 20)
    score = base * public * fan_in + BROKEN_REF_SCORE * min(broken, MAX_BROKEN_REFS)
    if is_test_path(change.path):
        score *= TEST_FACTOR
    return round(score, 1)
