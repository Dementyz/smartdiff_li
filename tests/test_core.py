import random

import pytest

from smartdiff_li import _pycore, core

try:
    from smartdiff_li import _core
except ImportError:
    _core = None

needs_c = pytest.mark.skipif(_core is None, reason="C extension is not built (make ext)")


def test_graph_basics(backend):
    g = backend.Graph(2)
    assert len(g) == 2 and g.add_node() == 2 and g.add_nodes(3) == 3 and len(g) == 6
    g.add_edge(0, 1, False, 10)
    g.add_edge(0, 1, True, 11)   # повтор становится точным
    g.add_edge(0, 1, False, 12)  # и остаётся точным
    g.add_edge(0, 0)             # петли не храним
    assert g.users(0) == [(1, True, 11)]
    assert g.edge_count == 1


def test_graph_errors(backend):
    g = backend.Graph(2)
    with pytest.raises(IndexError):
        g.add_edge(0, 5)
    with pytest.raises(IndexError):
        g.users(-1)
    with pytest.raises(IndexError):
        g.trace([7])
    with pytest.raises(IndexError):
        g.trace([0], 2, [(9, True, 0)])
    with pytest.raises(ValueError):
        backend.Graph(-1)
    with pytest.raises(ValueError):
        backend.change_score("bogus", False, True, False)


def chain_graph(backend):
    # 0 <- 1 <- 2 <- 3, 0 <- 4 (вероятно), 4 <- 3
    g = backend.Graph(5)
    for used, user, certain, line in [(0, 1, True, 1), (1, 2, True, 2), (2, 3, True, 3),
                                      (0, 4, False, 4), (4, 3, True, 5)]:
        g.add_edge(used, user, certain, line)
    return g


def test_trace_order_depth_and_certainty(backend):
    g = chain_graph(backend)
    assert g.trace([0]) == [(1, 1, True, 1), (4, 1, False, 4), (2, 2, True, 2), (3, 2, False, 5)]
    assert g.trace([0], 1) == [(1, 1, True, 1), (4, 1, False, 4)]
    assert g.trace([0], 0) == []
    assert g.trace([0], -1, [(2, True, 42), (2, False, 43)]) == [(2, 1, True, 42), (3, 2, True, 3)]
    assert g.reachable(0) == {1: 1, 4: 1, 2: 2, 3: 2}
    assert g.reachable(0, 1) == {1: 1, 4: 1}


def test_signature_break_kinds(backend):
    pos, var, kwonly, kwarg = _pycore.POSITIONAL, _pycore.VARARG, _pycore.KWONLY, _pycore.KWARG
    a = [("a", pos, False)]
    assert backend.signature_break(a, a + [("b", pos, False)])
    assert not backend.signature_break(a, a + [("b", pos, True)])
    assert not backend.signature_break(a, a + [("args", var, False), ("kw", kwarg, False)])
    assert backend.signature_break(a, [("a", kwonly, False)])
    assert backend.signature_break([("a", pos, False), ("b", pos, False)],
                                   [("b", pos, False), ("a", pos, False)])


def test_levels(backend):
    assert [backend.level_for(s) for s in (0, 9.9, 10, 24.9, 25, 45, 100)] == [
        "low", "low", "medium", "medium", "high", "critical", "critical"]


@needs_c
def test_c_and_python_agree_on_random_graphs():
    rng = random.Random(0)
    for _ in range(200):
        n = rng.randint(1, 30)
        c, py = _core.Graph(n), _pycore.Graph(n)
        for _ in range(rng.randint(0, 80)):
            edge = (rng.randrange(n), rng.randrange(n), rng.random() < 0.6, rng.randint(1, 99))
            c.add_edge(*edge)
            py.add_edge(*edge)
        assert c.edge_count == py.edge_count
        origins = rng.sample(range(n), rng.randint(1, min(3, n)))
        depth = rng.choice([-1, 0, 1, 2, 3])
        seeds = [(rng.randrange(n), rng.random() < 0.5, rng.randint(1, 9)) for _ in range(rng.randint(0, 4))]
        assert c.trace(origins, depth) == py.trace(origins, depth)
        assert c.trace(origins, depth, seeds) == py.trace(origins, depth, seeds)
        for node in range(n):
            assert c.users(node) == py.users(node)


@needs_c
def test_c_and_python_agree_on_scores_and_signatures():
    rng = random.Random(1)
    names = ["a", "b", "c", "d"]
    for _ in range(500):
        args = (rng.choice(list(_pycore.SCORES) + ["signature"]), rng.random() < 0.5,
                rng.random() < 0.5, rng.random() < 0.5)
        direct = rng.randint(0, 30)
        counts = (direct, direct + rng.randint(0, 40), rng.randint(0, 6))
        assert _core.change_score(*args, *counts) == _pycore.change_score(*args, *counts)

        def params():
            chosen = rng.sample(names, rng.randint(0, 4))
            return [(n, rng.randint(0, 4), rng.random() < 0.5) for n in chosen]
        old, new = params(), params()
        assert _core.signature_break(old, new) == _pycore.signature_break(old, new)


def test_facade_reports_backend(backend):
    assert core.backend() == ("python" if backend is _pycore else "c")
