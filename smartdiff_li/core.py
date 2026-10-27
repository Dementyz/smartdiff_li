"""Точка входа в ядро: C-расширение _core, если собрано, иначе _pycore.

SMARTDIFF_PURE_PYTHON=1 принудительно включает реализацию на Python."""
from __future__ import annotations

import os

from . import _pycore
from .symbols import KWARG, KWONLY, POSITIONAL, POSONLY, VARARG

try:
    if os.environ.get("SMARTDIFF_PURE_PYTHON"):
        raise ImportError("pure Python requested")
    from . import _core as _impl
except ImportError:
    _impl = _pycore

KINDS = {POSONLY: 0, POSITIONAL: 1, VARARG: 2, KWONLY: 3, KWARG: 4}


def backend() -> str:
    return "c" if _impl is not _pycore else "python"


def new_graph(nodes: int = 0):
    return _impl.Graph(nodes)


def signature_break(old, new) -> bool:
    """old и new: последовательности symbols.Param."""
    def convert(params):
        return [(p.name, KINDS[p.kind], p.has_default) for p in params]
    return _impl.signature_break(convert(old), convert(new))


def change_score(change: str, breaking: bool, public: bool, test: bool,
                 direct: int, total: int, broken: int) -> float:
    return _impl.change_score(change, breaking, public, test, direct, total, broken)


def level_for(score: float) -> str:
    return _impl.level_for(score)
