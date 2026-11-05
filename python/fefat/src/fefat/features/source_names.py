"""What a feature's code reads from outside it (`fefat.features.source_lint`): each name its body
reads, lambdas included, and does not bind itself, with the first line reading it and the value
the function's globals or closure bind it to, which the lint judges: data, a reader of data, a
helper, or a constant."""

import ast
import inspect
from types import FunctionType


def names_read_outside(
    function: FunctionType, statement: ast.FunctionDef
) -> list[tuple[str, int, object]]:
    """Each name the body of `function`, parsed as `statement`, reads from outside it, by name,
    with the first line reading it, counted as the statement's lines, and its value."""
    outside = {**function.__globals__, **inspect.getclosurevars(function).nonlocals}
    read = names_read(statement)
    return [(name, read[name], outside[name]) for name in sorted(read) if name in outside]


def names_read(statement: ast.FunctionDef) -> dict[str, int]:
    """The names the body reads and does not bind, by the first line reading each: its own
    parameters, its lambdas', and what it assigns are its own."""
    nodes = [node for each in statement.body for node in ast.walk(each)]
    functions = [statement, *(node for node in nodes if isinstance(node, ast.Lambda))]
    bound = {argument.arg for each in functions for argument in _parameters(each.args)}
    bound |= {
        node.id
        for node in nodes
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load)
    }
    read: dict[str, int] = {}
    for node in nodes:
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id not in bound:
            read[node.id] = min(read.get(node.id, node.lineno), node.lineno)
    return read


def _parameters(arguments: ast.arguments) -> list[ast.arg]:
    starred = [each for each in (arguments.vararg, arguments.kwarg) if each is not None]
    return [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs, *starred]
