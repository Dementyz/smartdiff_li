import ast

from smartdiff_li.symbols import IMPORTS, MODULE, extract_symbols, is_public


def symbols(source):
    return extract_symbols(ast.parse(source))


def test_extracts_functions_classes_and_variables():
    syms = symbols(
        "import os\n"
        "X = 1\n"
        "def f(a, b=2): pass\n"
        "class C:\n"
        "    attr = 1\n"
        "    def m(self): pass\n"
        "if X: print(1)\n"
    )
    assert {q: s.kind for q, s in syms.items()} == {
        "X": "variable", "f": "function", "C": "class", "C.attr": "attribute",
        "C.m": "method", MODULE: "module", IMPORTS: "imports",
    }


def test_formatting_and_comments_do_not_change_symbols():
    a = symbols("def f(x):\n    return x+1\n")
    b = symbols("def f( x ):\n    # comment\n    return (x +  1)\n")
    assert a["f"].body == b["f"].body and a["f"].signature == b["f"].signature


def test_docstring_is_tracked_separately():
    a = symbols('def f():\n    """one"""\n    return 1\n')
    b = symbols('def f():\n    """two"""\n    return 1\n')
    assert a["f"].body == b["f"].body
    assert a["f"].doc != b["f"].doc


def test_import_order_is_not_a_change():
    a = symbols("import os\nimport sys\n")
    b = symbols("import sys\nimport os\n")
    assert a[IMPORTS].body == b[IMPORTS].body


def test_property_setter_does_not_lose_the_getter():
    syms = symbols(
        "class C:\n"
        "    @property\n"
        "    def x(self): return 1\n"
        "    @x.setter\n"
        "    def x(self, v): pass\n"
    )
    assert "return" not in syms["C.x"].signature
    assert syms["C.x"].body.count("||") == 1


def test_is_public():
    assert is_public("f") and is_public("C.__init__") and is_public("C.m")
    assert not is_public("_f") and not is_public("C._m") and not is_public("_C.m")
