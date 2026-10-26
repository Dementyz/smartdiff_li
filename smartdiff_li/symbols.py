"""Извлечение символов (функции, классы, переменные) из Python-кода."""
from __future__ import annotations

import ast
from dataclasses import dataclass, field, replace

MODULE = "<module>"
IMPORTS = "<imports>"

POSONLY = "posonly"
POSITIONAL = "positional"
VARARG = "vararg"
KWONLY = "kwonly"
KWARG = "kwarg"

FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)


@dataclass(frozen=True)
class Param:
    name: str
    kind: str
    has_default: bool


@dataclass(frozen=True)
class Symbol:
    qualname: str
    kind: str  # function | method | class | variable | attribute | module | imports
    lineno: int
    end_lineno: int
    signature: str = ""
    body: str = ""
    doc: str | None = None
    params: tuple[Param, ...] = ()
    decorators: str = ""
    returns: str = ""
    is_async: bool = False
    size: int = 0
    nodes: tuple[ast.AST, ...] = field(default=(), compare=False, repr=False)

    @property
    def is_public(self) -> bool:
        return is_public(self.qualname)


def is_public(qualname: str) -> bool:
    for part in qualname.split("."):
        if part.startswith("_") and not (part.startswith("__") and part.endswith("__")):
            return False
    return True


def dump(node: ast.AST) -> str:
    # без позиций в файле: пробелы и комментарии не попадают в дамп
    return ast.dump(node, annotate_fields=False)


def dump_all(nodes) -> str:
    return "|".join(dump(n) for n in nodes)


def count_nodes(nodes) -> int:
    return sum(1 for n in nodes for _ in ast.walk(n))


def split_docstring(body: list[ast.stmt]) -> tuple[str | None, list[ast.stmt]]:
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        return " ".join(body[0].value.value.split()), body[1:]
    return None, body


def _params(args: ast.arguments) -> tuple[Param, ...]:
    positional = args.posonlyargs + args.args
    first_default = len(positional) - len(args.defaults)
    result = []
    for i, arg in enumerate(positional):
        kind = POSONLY if i < len(args.posonlyargs) else POSITIONAL
        result.append(Param(arg.arg, kind, i >= first_default))
    if args.vararg:
        result.append(Param(args.vararg.arg, VARARG, False))
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        result.append(Param(arg.arg, KWONLY, default is not None))
    if args.kwarg:
        result.append(Param(args.kwarg.arg, KWARG, False))
    return tuple(result)


def _function(node, qualname: str, kind: str) -> Symbol:
    doc, body = split_docstring(node.body)
    decorators = dump_all(node.decorator_list)
    returns = dump(node.returns) if node.returns else ""
    is_async = isinstance(node, ast.AsyncFunctionDef)
    signature = "|".join([str(is_async), dump(node.args), returns, decorators])
    return Symbol(
        qualname, kind, node.lineno, node.end_lineno or node.lineno,
        signature=signature, body=dump_all(body), doc=doc,
        params=_params(node.args), decorators=decorators, returns=returns,
        is_async=is_async, size=count_nodes(body), nodes=(node,),
    )


def _class(node: ast.ClassDef, qualname: str, doc: str | None, rest: list[ast.stmt]) -> Symbol:
    decorators = dump_all(node.decorator_list)
    bases = dump_all([*node.bases, *node.keywords])
    return Symbol(
        qualname, "class", node.lineno, node.end_lineno or node.lineno,
        signature=f"{bases}|{decorators}", body=dump_all(rest), doc=doc,
        decorators=decorators, size=count_nodes(rest),
        nodes=(*node.decorator_list, *node.bases, *node.keywords, *rest),
    )


def _variable(stmt, qualname: str, scope: str) -> Symbol:
    value = stmt.value
    annotation = getattr(stmt, "annotation", None)
    body = dump(value) if value is not None else ""
    if annotation is not None:
        body = f"{dump(annotation)}|{body}"
    return Symbol(
        qualname, "variable" if scope == "module" else "attribute",
        stmt.lineno, stmt.end_lineno or stmt.lineno, body=body,
        size=count_nodes([value]) if value is not None else 0, nodes=(stmt,),
    )


def _target_names(stmt) -> list[str]:
    if isinstance(stmt, ast.AnnAssign):
        return [stmt.target.id] if isinstance(stmt.target, ast.Name) else []
    names = []
    for target in stmt.targets:
        if isinstance(target, ast.Name):
            names.append(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            names.extend(e.id for e in target.elts if isinstance(e, ast.Name))
    return names


def _import_lines(imports: list[ast.stmt]) -> set[str]:
    lines = set()
    for node in imports:
        for alias in node.names:
            if isinstance(node, ast.Import):
                lines.add(f"import {alias.name} as {alias.asname}")
            else:
                lines.add(f"from {'.' * node.level}{node.module or ''} import {alias.name} as {alias.asname}")
    return lines


def _put(out: dict[str, Symbol], symbol: Symbol) -> None:
    # property.setter, overload и повторные определения склеиваем в один символ
    prev = out.get(symbol.qualname)
    if prev is None:
        out[symbol.qualname] = symbol
        return
    out[symbol.qualname] = replace(
        symbol,
        lineno=prev.lineno,
        signature=f"{prev.signature}||{symbol.signature}",
        body=f"{prev.body}||{symbol.body}",
        size=prev.size + symbol.size,
        nodes=prev.nodes + symbol.nodes,
    )


def _collect(body, prefix: str, scope: str, out: dict[str, Symbol]):
    rest, imports = [], []
    for stmt in body:
        if isinstance(stmt, FUNC_NODES):
            kind = "method" if scope == "class" else "function"
            _put(out, _function(stmt, prefix + stmt.name, kind))
        elif isinstance(stmt, ast.ClassDef):
            qualname = prefix + stmt.name
            doc, inner = split_docstring(stmt.body)
            members, _ = _collect(inner, qualname + ".", "class", out)
            _put(out, _class(stmt, qualname, doc, members))
        elif isinstance(stmt, (ast.Assign, ast.AnnAssign)) and _target_names(stmt):
            for name in _target_names(stmt):
                _put(out, _variable(stmt, prefix + name, scope))
        elif scope == "module" and isinstance(stmt, (ast.Import, ast.ImportFrom)):
            imports.append(stmt)
        else:
            rest.append(stmt)
    return rest, imports


def extract_symbols(tree: ast.Module) -> dict[str, Symbol]:
    out: dict[str, Symbol] = {}
    doc, body = split_docstring(tree.body)
    rest, imports = _collect(body, "", "module", out)
    if rest or doc is not None:
        out[MODULE] = Symbol(
            MODULE, "module",
            rest[0].lineno if rest else 1,
            (rest[-1].end_lineno or rest[-1].lineno) if rest else 1,
            body=dump_all(rest), doc=doc, size=count_nodes(rest), nodes=tuple(rest),
        )
    if imports:
        out[IMPORTS] = Symbol(
            IMPORTS, "imports", imports[0].lineno,
            imports[-1].end_lineno or imports[-1].lineno,
            body="|".join(sorted(_import_lines(imports))),
        )
    return out
