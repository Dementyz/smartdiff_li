from smartdiff_li.graph import build_graph, module_names


def graph_of(files):
    return build_graph(files, files.get)


def callers(graph, module, qualname, kind="function", **kw):
    return {(u.module, u.symbol): c for u, c in graph.references_to(module, qualname, kind, **kw)}


def test_module_names_skip_non_package_dirs():
    paths = ["src/pkg/__init__.py", "src/pkg/mod.py", "scripts/run.py"]
    assert module_names("src/pkg/mod.py", paths)[0] == "pkg.mod"
    assert module_names("src/pkg/__init__.py", paths)[0] == "pkg"
    assert module_names("scripts/run.py", paths) == ["run", "scripts.run"]


def test_from_import_and_module_attribute():
    graph = graph_of({
        "pkg/__init__.py": "",
        "pkg/core.py": "def f(): pass\ndef g(): pass\n",
        "pkg/use.py": "from pkg.core import f\nimport pkg.core as core\n"
                      "def a(): f()\ndef b(): core.g()\n",
    })
    assert callers(graph, "pkg.core", "f") == {("pkg.use", "a"): True}
    assert callers(graph, "pkg.core", "g") == {("pkg.use", "b"): True}
    assert graph.dependents("pkg.core") == {"pkg.use": 1}


def test_relative_imports_and_reexports():
    graph = graph_of({
        "pkg/__init__.py": "from .core import f\n",
        "pkg/core.py": "def f(): pass\n",
        "pkg/use.py": "from . import f\nfrom pkg import core\ndef a(): f(); core.f()\n",
        "app.py": "import pkg\ndef b(): pkg.f()\n",
    })
    assert ("pkg.use", "a") in callers(graph, "pkg.core", "f")
    assert ("app", "b") in callers(graph, "pkg.core", "f")


def test_methods_self_calls_and_class_usage():
    graph = graph_of({
        "m.py": "class C:\n    def a(self): return self.b()\n    def b(self): pass\n",
        "u.py": "from m import C\ndef run():\n    return C().b()\n",
    })
    assert callers(graph, "m", "C.b", "method") == {("m", "C.a"): True, ("u", "run"): False}
    assert callers(graph, "m", "C.b", "method", attr_names=False) == {
        ("m", "C.a"): True, ("u", "run"): False}


def test_constructor_change_is_certain_for_class_users():
    graph = graph_of({
        "m.py": "class C:\n    def __init__(self): pass\n",
        "u.py": "from m import C\ndef run(): return C()\n",
    })
    assert callers(graph, "m", "C.__init__", "method") == {("u", "run"): True}


def test_attribute_name_heuristic_is_limited_to_importers():
    graph = graph_of({
        "m.py": "class C:\n    def go(self): pass\n",
        "u.py": "from m import C\ndef run(obj): obj.go()\n",
        "unrelated.py": "def run(obj): obj.go()\n",
    })
    assert set(callers(graph, "m", "C.go", "method")) == {("u", "run")}


def test_unresolved_imports_are_recorded_for_deleted_modules():
    graph = graph_of({"u.py": "from gone import x\nimport gone.sub\nfrom pkg import old\n"})
    assert [u.lineno for u in graph.unresolved["gone"]] == [1]
    assert [u.lineno for u in graph.unresolved["gone.sub"]] == [2]
    assert [u.lineno for u in graph.unresolved["pkg.old"]] == [3]


def test_local_uses_of_removed_names_ignore_shadowing():
    graph = graph_of({"m.py": "def a(removed): return removed\ndef b(): return removed()\n"})
    uses = graph.local_uses("m", "removed", "function")
    assert [u.symbol for u in uses] == ["b"]


def test_syntax_errors_are_collected():
    graph = graph_of({"bad.py": "def (:\n", "ok.py": "x = 1\n"})
    assert graph.broken == ["bad.py"] and "ok" in graph.modules


def test_core_edges_match_references_to():
    # рёбра в ядре должны совпадать с правилами references_to (без эвристики по имени атрибута)
    graph = graph_of({
        "m.py": "class C:\n    def __init__(self): pass\n    def a(self): return self.b()\n"
                "    def b(self): pass\nX = 1\n",
        "u.py": "from m import C, X\nimport m\ndef run(): return C().a() + X\n"
                "def other(): return m.C.b\n",
    })
    for (module, qualname), node in graph.node_ids.items():
        kind = graph.modules[module].symbols[qualname].kind
        expected = {(u.module, u.symbol): c
                    for u, c in graph.references_to(module, qualname, kind, attr_names=False)}
        actual = {graph.node_keys[user]: c for user, c, _ in graph.symbol_graph.users(node)}
        assert actual == expected, (module, qualname)
