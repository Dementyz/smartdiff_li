import ast

from smartdiff_li.semantic import compare_symbols, describe_signature, pair_moves
from smartdiff_li.symbols import extract_symbols


def compare(old, new, **kw):
    return compare_symbols("m.py", "m", extract_symbols(ast.parse(old)),
                           extract_symbols(ast.parse(new)), **kw)


def kinds(changes):
    return {c.qualname: c.change for c in changes}


def test_cosmetic_change_is_ignored():
    assert compare("def f(x):\n    return x+1\n", "def f(x):\n    # hi\n    return x + 1\n") == []


def test_body_added_removed_and_doc_changes():
    old = 'def a(): return 1\ndef b(): return 1\ndef c():\n    """x"""\n'
    new = 'def a(): return 2\ndef d(): return 1\ndef c():\n    """y"""\n'
    assert kinds(compare(old, new)) == {"a": "body", "b": "removed", "d": "added", "c": "doc"}


def test_signature_compatibility():
    def breaking(old, new):
        (change,) = compare(old, new)
        return change.breaking

    assert breaking("def f(a): pass", "def f(a, b): pass")
    assert breaking("def f(a, b): pass", "def f(a): pass")
    assert breaking("def f(a, b): pass", "def f(b, a): pass")
    assert breaking("def f(a, b): pass", "def f(a, c, b=1): pass")
    assert breaking("def f(a): pass", "async def f(a): pass")
    assert not breaking("def f(a): pass", "def f(a, b=1): pass")
    assert not breaking("def f(a): pass", "def f(a, *args, **kw): pass")
    assert not breaking("def f(a=1): pass", "def f(a=2): pass")
    assert not breaking("def f(a): pass", "def f(a: int) -> int: pass")
    assert breaking("def f(a=1): pass", "def f(a): pass")


def test_signature_description():
    (change,) = compare("def f(a, b): pass", "def f(a, c): pass")
    assert "removed params: b" in change.details
    assert "added params: c (required)" in change.details


def test_whole_file_ignores_imports_symbol():
    changes = compare("", "import os\ndef f(): pass\n", whole_file=True)
    assert kinds(changes) == {"f": "added"}


def test_pair_moves_across_files():
    body = "    total = 0\n    for i in range(n):\n        total += i * 2\n    return total\n"
    removed = compare_symbols("a.py", "a", extract_symbols(ast.parse(f"def calc(n):\n{body}")), {})
    added = compare_symbols("b.py", "b", {}, extract_symbols(ast.parse(f"def calc(n):\n{body}")))
    result = pair_moves(removed + added)
    assert [(c.change, c.moved_to) for c in result] == [("moved", "b:calc")]


def test_trivial_functions_with_different_names_are_not_paired():
    removed = compare_symbols("a.py", "a", extract_symbols(ast.parse("def a(): return 1")), {})
    added = compare_symbols("a.py", "a", {}, extract_symbols(ast.parse("def b(): return 1")))
    assert {c.change for c in pair_moves(removed + added)} == {"removed", "added"}


def test_rename_in_same_module_is_detected():
    body = "    total = 0\n    for i in range(n):\n        total += i * 2\n    return total\n"
    changes = compare(f"def old(n):\n{body}", f"def new(n):\n{body}")
    (change,) = pair_moves(changes)
    assert change.change == "moved" and "renamed to new" in change.details
