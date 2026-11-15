"""What an execution runs and what it may take (step 4.5, `01-architecture.md` sections 6 and 10):
its kind and its limits, kept apart from the specs of `fefat_app.execution` so that the import
wizard's specs (`fefat_app.imports`, step 5.12), which those of every kind include, name them
without a cycle."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ExecutionKind(StrEnum):
    """What an execution runs: a feature's preview, or a snippet of Python, which the job kinds
    of the same names run (step 4.5); a strategy's code validated, a strategy version saved, or a
    feature version saved, which the library's routes run (step 5.2); a saved version's run
    looked up, which `POST /v1/runs` runs, and its backtest, which a `backtest` job runs (step
    5.3); and a file read for the import wizard, which `POST /v1/imports/preview` runs, and its
    import, which an `import` job runs (step 5.12)."""

    FEATURE_PREVIEW = "feature_preview"
    PYTHON_SNIPPET = "python_snippet"
    STRATEGY_VALIDATION = "strategy_validation"
    STRATEGY_SAVE = "strategy_save"
    FEATURE_SAVE = "feature_save"
    RUN_LOOKUP = "run_lookup"
    BACKTEST = "backtest"
    IMPORT_PREVIEW = "import_preview"
    IMPORT = "import"


MOST_SECONDS = 24 * 60 * 60
"""The longest timeout an execution takes: a day, longer than any run FEFAT starts."""
MOST_BYTES = 2**63 - 1
"""The largest memory limit an execution takes, the most a limit of 64 bits holds."""


class ExecutionLimits(BaseModel):
    """What an execution may take: the seconds of the wall clock from its start, and the bytes of
    memory its processes may commit together, past which an allocation fails."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timeout_seconds: float = Field(gt=0, le=MOST_SECONDS)
    memory_bytes: int = Field(gt=0, le=MOST_BYTES)
