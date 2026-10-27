"""Ядро на чистом Python: тот же API, что у smartdiff_li._core (csrc/).

Используется, когда C-расширение не собрано. Логика повторяет csrc/*.c один в один,
tests/test_core.py проверяет, что обе реализации дают одинаковый результат."""
from __future__ import annotations

POSONLY, POSITIONAL, VARARG, KWONLY, KWARG = range(5)

SCORES = {"added": 0.5, "removed": 6.0, "body": 3.0, "doc": 0.0, "moved": 1.0}
BREAKING_SIGNATURE = 8.0
COMPATIBLE_SIGNATURE = 2.0
BROKEN_REF_SCORE = 15.0
MAX_BROKEN_REFS = 3
PRIVATE_FACTOR = 0.5
TEST_FACTOR = 0.2


class Graph:
    """Обратный граф: у каждого узла список тех, кто его использует."""

    def __init__(self, nodes: int = 0) -> None:
        if nodes < 0:
            raise ValueError("nodes must be >= 0")
        self._adj: list[dict[int, list]] = [{} for _ in range(nodes)]
        self.edge_count = 0

    def __len__(self) -> int:
        return len(self._adj)

    def _check(self, *nodes: int) -> None:
        for node in nodes:
            if not 0 <= node < len(self._adj):
                raise IndexError("node id out of range")

    def add_node(self) -> int:
        return self.add_nodes(1)

    def add_nodes(self, count: int) -> int:
        if count < 0:
            raise ValueError("count must be >= 0")
        first = len(self._adj)
        self._adj.extend({} for _ in range(count))
        return first

    def add_edge(self, used: int, user: int, certain: bool = True, line: int = 0) -> None:
        self._check(used, user)
        if used == user:
            return
        edges = self._adj[used]
        edge = edges.get(user)
        if edge is None:
            edges[user] = [bool(certain), line]
            self.edge_count += 1
        elif certain and not edge[0]:
            edge[0], edge[1] = True, line

    def users(self, node: int) -> list[tuple[int, bool, int]]:
        self._check(node)
        return [(user, c, line) for user, (c, line) in self._adj[node].items()]

    def trace(self, origins, depth: int = -1, seeds=None) -> list[tuple[int, int, bool, int]]:
        origins = list(origins)
        self._check(*origins)
        if seeds is not None:
            seeds = list(seeds)
            self._check(*(s[0] for s in seeds))
        if depth == 0:
            return []
        seen = set(origins)
        out = []
        if seeds is not None:
            first = seeds
        else:
            first = [(user, c, line) for o in origins for user, (c, line) in self._adj[o].items()]
        for node, certain, line in first:
            if node not in seen:
                seen.add(node)
                out.append((node, 1, bool(certain), line))
        start, end, level = 0, len(out), 1
        while start < end and (depth < 0 or level < depth):
            level += 1
            for node, _, certain, _ in out[start:end]:
                for user, (c, line) in self._adj[node].items():
                    if user not in seen:
                        seen.add(user)
                        out.append((user, level, certain and c, line))
            start, end = end, len(out)
        return out

    def reachable(self, origin: int, depth: int = -1) -> dict[int, int]:
        return {node: level for node, level, _, _ in self.trace([origin], depth)}


def signature_break(old, new) -> bool:
    new_by_name = {name: (kind, default) for name, kind, default in new}
    old_names = {name for name, _, _ in old}
    for name, kind, default in old:
        q = new_by_name.get(name)
        if q is None or q[0] != kind:
            return True
        if default and not q[1]:
            return True
    for name, kind, default in new:
        if name not in old_names and not default and kind not in (VARARG, KWARG):
            return True
    old_pos = [name for name, kind, _ in old if kind in (POSONLY, POSITIONAL)]
    new_pos = [name for name, kind, _ in new if kind in (POSONLY, POSITIONAL)]
    return new_pos[:len(old_pos)] != old_pos


def change_score(change: str, breaking: bool, public: bool, test: bool,
                 direct: int = 0, total: int = 0, broken: int = 0) -> float:
    if change == "signature":
        base = BREAKING_SIGNATURE if breaking else COMPATIBLE_SIGNATURE
    elif change in SCORES:
        base = SCORES[change]
    else:
        raise ValueError(f"unknown change kind: {change}")
    public_factor = 1.0 if public else PRIVATE_FACTOR
    fan_in = 1 + 0.3 * min(direct, 10) + 0.05 * min(total - direct, 20)
    score = base * public_factor * fan_in + BROKEN_REF_SCORE * min(broken, MAX_BROKEN_REFS)
    if test:
        score *= TEST_FACTOR
    return score


def level_for(score: float) -> str:
    if score >= 45:
        return "critical"
    if score >= 25:
        return "high"
    if score >= 10:
        return "medium"
    return "low"
