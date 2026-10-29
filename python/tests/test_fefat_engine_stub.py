"""The stub `fefat_engine.pyi` declares what the compiled module holds (step 2.10, from
BACKLOG.md): each function with its parameters in their order, and each constant, so that pyright
checks the SDK's calls against the module the build makes."""

import ast
import inspect
from pathlib import Path

import fefat_engine

STUB = Path(__file__).resolve().parents[2] / "engine" / "crates" / "fefat-py" / "fefat_engine.pyi"


def stub_names() -> tuple[dict[str, list[str]], set[str]]:
    """The stub's functions, each with its parameters' names, and its constants."""
    tree = ast.parse(STUB.read_text(encoding="utf-8"))
    functions = {
        node.name: [argument.arg for argument in node.args.args]
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }
    constants = {
        node.target.id
        for node in tree.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    return functions, constants


def module_names() -> tuple[dict[str, list[str]], set[str]]:
    """The compiled module's functions, each with its parameters' names as PyO3 writes their
    signature, and its integer constants."""
    public = {name: getattr(fefat_engine, name) for name in dir(fefat_engine)}
    public = {name: value for name, value in public.items() if not name.startswith("_")}
    functions = {
        name: list(inspect.signature(value).parameters)
        for name, value in public.items()
        if inspect.isbuiltin(value)
    }
    constants = {name for name, value in public.items() if isinstance(value, int)}
    return functions, constants


def test_the_stub_declares_every_function_and_constant_of_the_compiled_module() -> None:
    declared_functions, declared_constants = stub_names()
    compiled_functions, compiled_constants = module_names()

    assert declared_functions == compiled_functions
    assert declared_constants == compiled_constants
    assert {"run_signal_backtest", "run_batch", "run_key", "table_hash"} <= set(compiled_functions)
    assert declared_constants == {"ENGINE_VERSION", "FILL_MODEL_VERSION", "ARTIFACT_SCHEMA_VERSION"}
