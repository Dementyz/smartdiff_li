"""Граф зависимостей проекта: импорты между модулями и ссылки между символами."""
from __future__ import annotations

import ast
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Callable, Iterable

from . import core
from .symbols import IMPORTS, FUNC_NODES, Symbol, extract_symbols


@dataclass(frozen=True)
class Use:
    module: str
    symbol: str
    path: str
    lineno: int


@dataclass(frozen=True)
class Ref(Use):
    target_module: str = ""
    target_name: str = ""


@dataclass
class ModuleInfo:
    name: str
    path: str
    tree: ast.Module
    symbols: dict[str, Symbol]
    defined: set[str]
    name_aliases: dict[str, tuple[str, str]] = field(default_factory=dict)  # local -> (module, name)
    mod_aliases: dict[str, str] = field(default_factory=dict)  # local -> dotted module
    imports: set[str] = field(default_factory=set)

    @property
    def is_package(self) -> bool:
        return self.path.endswith("__init__.py")


def module_names(path: str, all_paths: Iterable[str]) -> list[str]:
    """Все допустимые точечные имена модуля, от самого короткого к самому длинному."""
    all_paths = set(all_paths)
    parts = path[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    names = {".".join(parts)}
    # каталоги без __init__.py (src/, scripts/) не входят в имя пакета
    for i in range(1, len(parts)):
        if f"{'/'.join(parts[:i])}/__init__.py" in all_paths:
            break
        names.add(".".join(parts[i:]))
    return sorted((n for n in names if n), key=lambda n: (n.count("."), n))


def _chain(node: ast.AST) -> list[str] | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return parts[::-1]
    return None


def _absolute(node: ast.ImportFrom, package: str) -> str | None:
    if node.level == 0:
        return node.module
    parts = package.split(".") if package else []
    drop = node.level - 1
    if drop > len(parts):
        return None
    parts = parts[:len(parts) - drop]
    if node.module:
        parts += node.module.split(".")
    return ".".join(parts) or None


class ProjectGraph:
    def __init__(self) -> None:
        self.modules: dict[str, ModuleInfo] = {}
        self.lookup: dict[str, str] = {}
        self.by_path: dict[str, str] = {}
        # узлы и рёбра хранит ядро (csrc/graph.c), здесь только отображение имён в id
        self.symbol_graph = core.new_graph()
        self.node_ids: dict[tuple[str, str], int] = {}
        self.node_keys: list[tuple[str, str]] = []
        self.module_graph = core.new_graph()
        self.module_ids: dict[str, int] = {}
        self.module_list: list[str] = []
        self.refs: dict[str, dict[str, list[Ref]]] = defaultdict(lambda: defaultdict(list))
        self.attr_uses: dict[str, list[Use]] = defaultdict(list)
        self.unresolved: dict[str, list[Use]] = defaultdict(list)
        self.broken: list[str] = []

    def resolve(self, dotted: str) -> str | None:
        return self.lookup.get(dotted)

    def module_of(self, path: str) -> str | None:
        return self.by_path.get(path)

    def resolve_export(self, module: str, name: str) -> tuple[str, str]:
        """Идёт по цепочке реэкспортов (from .core import X в __init__.py)."""
        for _ in range(5):
            info = self.modules.get(module)
            top, _, rest = name.partition(".")
            if info is None or top in info.defined or top not in info.name_aliases:
                break
            target_module, target_name = info.name_aliases[top]
            target = self.resolve(target_module)
            if target is None:
                break
            module = target
            name = target_name + ("." + rest if rest else "")
        return module, name

    def importers(self, module: str) -> set[str]:
        node = self.module_ids.get(module)
        if node is None:
            return set()
        return {self.module_list[user] for user, _, _ in self.module_graph.users(node)}

    def dependents(self, module: str, depth: int | None = None) -> dict[str, int]:
        """Модули, которые импортируют `module` (транзитивно), и расстояние до них."""
        node = self.module_ids.get(module)
        if node is None:
            return {}
        reached = self.module_graph.reachable(node, -1 if depth is None else depth)
        return {self.module_list[n]: dist for n, dist in reached.items()}

    def trace(self, module: str, qualname: str, depth: int, seeds) -> list[tuple[str, str, int, bool, int]]:
        """Обход влияния в ядре. seeds: первый уровень [(Use, certain)]."""
        origin = self.node_ids.get((module, qualname))
        if origin is None:
            return []
        first = [(self.node_ids[(u.module, u.symbol)], certain, u.lineno) for u, certain in seeds]
        return [(*self.node_keys[node], level, certain, line)
                for node, level, certain, line in self.symbol_graph.trace([origin], depth, first)]

    def references_to(self, module: str, qualname: str, kind: str = "function",
                      attr_names: bool = True) -> list[tuple[Use, bool]]:
        """Кто ссылается на символ. Второй элемент: ссылка точная (True) или вероятная (False)."""
        found: dict[tuple[str, str], tuple[Use, bool]] = {}

        def add(use: Use, certain: bool) -> None:
            key = (use.module, use.symbol)
            if key not in found or (certain and not found[key][1]):
                found[key] = (use, certain)

        top = qualname.split(".")[0]
        for ref in self.refs.get(module, {}).get(top, ()):
            target = ref.target_name
            if target == qualname:
                add(ref, True)
            elif target.startswith(qualname + "."):
                add(ref, False)  # используют член изменённого класса
            elif qualname.startswith(target + "."):
                # используют класс, а изменился его метод
                add(ref, qualname.endswith(".__init__"))

        name = qualname.rsplit(".", 1)[-1]
        if attr_names and kind in ("method", "attribute") and not name.startswith("__"):
            scope = {module, *self.importers(module)}
            for use in self.attr_uses.get(name, ()):
                if use.module in scope and (use.module, use.symbol) != (module, qualname):
                    add(use, False)
        return list(found.values())

    def local_uses(self, module: str, qualname: str, kind: str) -> list[Use]:
        """Использования удалённого имени внутри того же модуля (оно больше не определено)."""
        info = self.modules.get(module)
        if info is None:
            return []
        if kind in ("method", "attribute") and "." in qualname:
            owner, _, member = qualname.rpartition(".")
            finder = lambda sym: _find_member_use(sym, member)
            scope = [s for s in info.symbols.values() if s.qualname.startswith(owner + ".")]
        else:
            top = qualname.split(".")[0]
            finder = lambda sym: _find_name_use(sym, top)
            scope = list(info.symbols.values())
        uses = []
        for sym in scope:
            if sym.qualname == IMPORTS:
                continue
            lineno = finder(sym)
            if lineno:
                uses.append(Use(module, sym.qualname, info.path, lineno))
        return uses


def _bound_names(node: ast.AST) -> set[str]:
    names = set()
    if isinstance(node, FUNC_NODES):
        a = node.args
        every = [*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg]
        names |= {x.arg for x in every if x}
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            names.add(n.id)
    return names


def _find_name_use(sym: Symbol, name: str) -> int:
    for node in sym.nodes:
        if name in _bound_names(node):
            continue
        for n in ast.walk(node):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id == name:
                return n.lineno
    return 0


def _find_member_use(sym: Symbol, member: str) -> int:
    for node in sym.nodes:
        for n in ast.walk(node):
            if (isinstance(n, ast.Attribute) and n.attr == member
                    and isinstance(n.value, ast.Name) and n.value.id in ("self", "cls")):
                return n.lineno
    return 0


class _Collector(ast.NodeVisitor):
    def __init__(self, graph: ProjectGraph, info: ModuleInfo, symbol: Symbol) -> None:
        self.graph = graph
        self.info = info
        self.symbol = symbol
        self.owner = symbol.qualname.rpartition(".")[0] if symbol.kind == "method" else None
        self.seen: set[tuple] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self._resolve([node.id], node.lineno)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        chain = _chain(node)
        if chain is None:
            self._attr(node.attr, node.lineno)
            self.generic_visit(node)
        else:
            self._resolve(chain, node.lineno)

    def _add(self, module: str, name: str, lineno: int) -> None:
        if module == self.info.name and name == self.symbol.qualname:
            return
        if (module, name) in self.seen:
            return
        self.seen.add((module, name))
        ref = Ref(self.info.name, self.symbol.qualname, self.info.path, lineno, module, name)
        self.graph.refs[module][name.split(".")[0]].append(ref)

    def _attr(self, attr: str, lineno: int) -> None:
        if ("attr", attr) in self.seen:
            return
        self.seen.add(("attr", attr))
        self.graph.attr_uses[attr].append(
            Use(self.info.name, self.symbol.qualname, self.info.path, lineno))

    def _resolve(self, chain: list[str], lineno: int) -> None:
        first, rest = chain[0], chain[1:]
        info, graph = self.info, self.graph

        if first in info.name_aliases:
            module, name = info.name_aliases[first]
            target = graph.resolve(module)
            if target:
                target, name = graph.resolve_export(target, ".".join([name, *rest]))
                self._add(target, name, lineno)
            return

        if first in info.mod_aliases:
            base = info.mod_aliases[first]
            for i in range(len(rest), -1, -1):
                target = graph.resolve(".".join([base, *rest[:i]]))
                if target:
                    if rest[i:]:
                        target, name = graph.resolve_export(target, ".".join(rest[i:]))
                        self._add(target, name, lineno)
                    break
            return

        if first in ("self", "cls") and self.owner and rest:
            member = f"{self.owner}.{rest[0]}"
            if member in info.symbols:
                self._add(info.name, member, lineno)
            else:
                self._attr(rest[0], lineno)
            for attr in rest[1:]:
                self._attr(attr, lineno)
            return

        if first in info.defined:
            self._add(info.name, ".".join(chain), lineno)
            return

        for attr in rest:
            self._attr(attr, lineno)


def _collect_imports(graph: ProjectGraph, info: ModuleInfo) -> None:
    package = info.name if info.is_package else info.name.rpartition(".")[0]

    def unresolved(dotted: str, lineno: int) -> None:
        graph.unresolved[dotted].append(Use(info.name, IMPORTS, info.path, lineno))

    for node in ast.walk(info.tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    info.mod_aliases[alias.asname] = alias.name
                else:
                    top = alias.name.split(".")[0]
                    info.mod_aliases[top] = top
                target = graph.resolve(alias.name)
                if target:
                    info.imports.add(target)
                else:
                    unresolved(alias.name, node.lineno)
        elif isinstance(node, ast.ImportFrom):
            base = _absolute(node, package)
            if base is None:
                continue
            base_mod = graph.resolve(base)
            if base_mod:
                info.imports.add(base_mod)
            else:
                unresolved(base, node.lineno)
            for alias in node.names:
                if alias.name == "*":
                    if base_mod:
                        for name in graph.modules[base_mod].defined:
                            if not name.startswith("_"):
                                info.name_aliases[name] = (base, name)
                    continue
                local = alias.asname or alias.name
                sub = graph.resolve(f"{base}.{alias.name}")
                defined_in_base = base_mod and alias.name in graph.modules[base_mod].defined
                if sub and not defined_in_base:
                    info.mod_aliases[local] = f"{base}.{alias.name}"
                    info.imports.add(sub)
                else:
                    info.name_aliases[local] = (base, alias.name)
                    if not sub:
                        unresolved(f"{base}.{alias.name}", node.lineno)


def build_graph(paths: Iterable[str], read: Callable[[str], str | None]) -> ProjectGraph:
    all_paths = set(paths)
    graph = ProjectGraph()
    for path in sorted(all_paths):
        source = read(path)
        if source is None:
            continue
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError, RecursionError):
            graph.broken.append(path)
            continue
        names = module_names(path, all_paths)
        name = names[0] if names[0] not in graph.modules else names[-1]
        symbols = extract_symbols(tree)
        defined = {q.split(".")[0] for q in symbols if not q.startswith("<")}
        graph.modules[name] = ModuleInfo(name, path, tree, symbols, defined)
        graph.by_path[path] = name
        for alias in names:
            graph.lookup.setdefault(alias, name)

    for info in graph.modules.values():
        _collect_imports(graph, info)
    graph.module_list = list(graph.modules)
    graph.module_ids = {name: i for i, name in enumerate(graph.module_list)}
    graph.module_graph.add_nodes(len(graph.module_list))
    for info in graph.modules.values():
        for target in info.imports:
            graph.module_graph.add_edge(graph.module_ids[target], graph.module_ids[info.name])

    for info in graph.modules.values():
        for symbol in info.symbols.values():
            if symbol.qualname == IMPORTS:
                continue
            graph.node_ids[(info.name, symbol.qualname)] = len(graph.node_keys)
            graph.node_keys.append((info.name, symbol.qualname))
            collector = _Collector(graph, info, symbol)
            for node in symbol.nodes:
                collector.visit(node)
    graph.symbol_graph.add_nodes(len(graph.node_keys))
    _link_symbols(graph)
    return graph


def _link_symbols(graph: ProjectGraph) -> None:
    """Переводит ссылки в рёбра ядра по тем же правилам, что и references_to:
    точная ссылка; ссылка на член класса (вероятно затрагивает сам класс);
    ссылка на класс (вероятно затрагивает его члены, конструктор точно)."""
    by_top: dict[tuple[str, str], list[str]] = defaultdict(list)
    for module, qualname in graph.node_keys:
        by_top[(module, qualname.split(".")[0])].append(qualname)

    add, ids = graph.symbol_graph.add_edge, graph.node_ids
    for module, tops in graph.refs.items():
        for top, refs in tops.items():
            members = by_top.get((module, top), ())
            for ref in refs:
                user = ids[(ref.module, ref.symbol)]
                target = ref.target_name
                exact = ids.get((module, target))
                if exact is not None:
                    add(exact, user, True, ref.lineno)
                parts = target.split(".")
                for i in range(1, len(parts)):
                    owner = ids.get((module, ".".join(parts[:i])))
                    if owner is not None:
                        add(owner, user, False, ref.lineno)
                prefix = target + "."
                for qualname in members:
                    if qualname.startswith(prefix):
                        add(ids[(module, qualname)], user, qualname.endswith(".__init__"), ref.lineno)
