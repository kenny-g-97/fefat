"""What a feature's code reads from outside it (`fefat.features.source_lint`): each name its body
reads, lambdas included, and does not bind itself, with the first line reading it and the value
the function's globals or closure bind it to, which the lint judges: data, a reader of data, a
helper, or a constant."""

import ast
import inspect
from collections.abc import Iterator
from types import FunctionType


def names_read_outside(
    function: FunctionType, statement: ast.FunctionDef
) -> list[tuple[str, int, object]]:
    """Each name the body of `function`, parsed as `statement`, reads from outside it, by name,
    with the first line reading it, counted as the statement's lines, and its value."""
    outside = {**function.__globals__, **inspect.getclosurevars(function).nonlocals}
    read = names_read(statement)
    return [(name, read[name], outside[name]) for name in sorted(read) if name in outside]


_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def names_read(statement: ast.FunctionDef) -> dict[str, int]:
    """The names the body reads and does not bind, by the first line reading each: its own
    parameters, what it assigns and imports, and the functions it defines are its own, and a
    function or lambda it defines binds its parameters and its own names for its body alone."""
    return _read_in(statement, frozenset())


def _read_in(
    function: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda, outer: frozenset[str]
) -> dict[str, int]:
    """The names `function`'s body reads that neither it nor the scopes around it, `outer`, bind,
    the bodies of the functions it defines read in their own scopes."""
    body: list[ast.AST] = (
        list(function.body) if isinstance(function.body, list) else [function.body]
    )
    nodes = list(_own_nodes(body))
    inner = [node for node in nodes if isinstance(node, _FUNCTIONS)]
    bound = outer | {argument.arg for argument in _parameters(function.args)}
    bound |= {node.name for node in inner if not isinstance(node, ast.Lambda)}
    bound |= {
        node.id
        for node in nodes
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load)
    }
    bound |= {
        (alias.asname or alias.name).split(".")[0]
        for node in nodes
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    }
    read: dict[str, int] = {}
    for node in nodes:
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id not in bound:
            read[node.id] = min(read.get(node.id, node.lineno), node.lineno)
    for each in inner:
        for name, line in _read_in(each, frozenset(bound)).items():
            read[name] = min(read.get(name, line), line)
    return read


def _own_nodes(body: list[ast.AST]) -> Iterator[ast.AST]:
    """The nodes of `body` outside the bodies of the functions and lambdas it defines, whose
    defaults and decorators, which run where they are defined, are its own."""
    stack: list[ast.AST] = list(reversed(body))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, _FUNCTIONS):
            defaults = [
                *node.args.defaults,
                *(each for each in node.args.kw_defaults if each is not None),
            ]
            decorators = [] if isinstance(node, ast.Lambda) else node.decorator_list
            stack.extend(reversed([*defaults, *decorators]))
        else:
            stack.extend(reversed(list(ast.iter_child_nodes(node))))


def _parameters(arguments: ast.arguments) -> list[ast.arg]:
    starred = [each for each in (arguments.vararg, arguments.kwarg) if each is not None]
    return [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs, *starred]
