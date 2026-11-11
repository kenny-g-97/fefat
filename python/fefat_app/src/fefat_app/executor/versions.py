"""The library's executions in the runner (step 5.2, D-93): a strategy's code validated, a strategy
version saved, and a feature version saved, each through the SDK as a notebook calls it
(`ff.strategy.from_source`, `ff.strategy.save`, `ff.features.save`), so that the trader's code
runs here, never in the server. What the SDK refuses comes back as the runner's answer, with the
line of the code the refusal is at where it has one, rather than as a failure, so that the editor
of step 5.5 underlines it; a message is kept to its first `ERROR_CHARS` characters."""

import traceback

import fefat as ff
from fefat.features import FeatureDef
from fefat.features.source_code import SOURCE_FILENAME_PREFIX
from fefat.strategy import StrategyCodeError
from fefat_app.execution import (
    FeatureSaveOutput,
    FeatureSaveSpec,
    LibraryOutput,
    LibrarySpec,
    RefusedCode,
    SavedVersion,
    StrategySaveOutput,
    StrategySaveSpec,
    StrategyValidationOutput,
    StrategyValidationSpec,
    ValidStrategy,
)
from fefat_app.executor.protocol import ERROR_CHARS


def library_output(spec: LibrarySpec) -> LibraryOutput:
    """What the execution of `spec`, of one of the library's kinds, gives."""
    if isinstance(spec, StrategyValidationSpec):
        return StrategyValidationOutput(answer=_validated(spec.code))
    if isinstance(spec, StrategySaveSpec):
        return StrategySaveOutput(answer=_strategy_saved(spec))
    return FeatureSaveOutput(answer=_feature_saved(spec))


def _validated(code: str) -> ValidStrategy | RefusedCode:
    try:
        definition = ff.strategy.from_source(code)
    except StrategyCodeError as refused:
        return _refused(str(refused), refused.line)
    strategy = definition.with_defaults
    return ValidStrategy(
        instrument=strategy.instrument,
        timeframe=strategy.timeframe,
        parameter_schema=definition.parameter_schema,
        lint=ff.strategy.lint(definition.code),
    )


def _strategy_saved(spec: StrategySaveSpec) -> SavedVersion | RefusedCode:
    """The version `spec` saves; a refusal of its code with the line it is at, and one of its
    name, its words, or a save another process made first without one."""
    try:
        saved = ff.strategy.save(
            spec.name, spec.code, hypothesis=spec.hypothesis, changelog=spec.changelog
        )
    except StrategyCodeError as refused:
        return _refused(str(refused), refused.line)
    except ValueError as refused:
        return _refused(str(refused), None)
    return SavedVersion(name=saved.name, version=saved.version)


def _feature_saved(spec: FeatureSaveSpec) -> SavedVersion | RefusedCode:
    """The version `spec` saves, or the refusal of its code, with the line of the code it is at
    where it has one: whatever the code raises is the code's."""
    try:
        saved = ff.features.save(_feature_of(spec))
    except (Exception, SystemExit) as refused:
        return _refused(_described(refused), _feature_line(refused))
    return SavedVersion(name=saved.name, version=saved.version)


def _feature_of(spec: FeatureSaveSpec) -> FeatureDef:
    definition = ff.features.from_source(spec.code)
    if definition.name != spec.name:
        raise ValueError(
            f"Expected the code of feature {spec.name}, got that of feature {definition.name}."
        )
    return definition


def _feature_line(error: BaseException) -> int | None:
    """The line of a feature's code `error` is at: a syntax error's, or the innermost of the
    code's lines in its traceback; None where neither is."""
    if isinstance(error, SyntaxError):
        return error.lineno
    frames = traceback.extract_tb(error.__traceback__)
    lines = [frame.lineno for frame in frames if frame.filename.startswith(SOURCE_FILENAME_PREFIX)]
    return lines[-1] if lines else None


def _described(error: BaseException) -> str:
    """What `error` says: an SDK's refusal in its own words, and any other error after its kind,
    as Python's own traceback ends."""
    if isinstance(error, SyntaxError):
        return f"{type(error).__name__}: {error.msg}"
    if isinstance(error, ValueError):
        return str(error)
    return f"{type(error).__name__}: {error}"


def _refused(message: str, line: int | None) -> RefusedCode:
    return RefusedCode(line=line, message=message[:ERROR_CHARS])
