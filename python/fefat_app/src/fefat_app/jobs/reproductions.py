"""A saved run's reproduction as a job (step 5.10, D-93, D-126, `01-architecture.md` section 6):
its payload a `BacktestSpec` that names the run it makes again, run by the worker's executor
through the `backtest` spec kind, since the strategy is built from its version's code there
(D-91), each stage the runner reports a `progress` event of the job's stream; the runner makes
the run again into FEFAT's cache folder (`ff.backtest.reproduce`), and the job's result is its
verdict, the run's trades matched or not, or its refusal in words that name no folder of this PC
(D-80). A refusal is an answer, so the job succeeds; a reproduction indexes nothing, since the
saved run stays the record."""

from collections.abc import Mapping
from typing import Any

from fefat.config import FefatPaths
from fefat_app.execution import BacktestOutput, BacktestSpec
from fefat_app.jobs.executions import advancing, executed
from fefat_app.jobs.progress import JobProgress
from fefat_app.jobs.trade_explanations import without_folders
from fefat_app.ports import Executor
from fefat_app.reproductions import ReproductionRefused


def run_reproduction(
    executor: Executor, paths: FefatPaths, payload: Mapping[str, Any], progress: JobProgress
) -> dict[str, Any]:
    """Make the saved run of `payload` again, reporting through `progress`; its verdict, or why
    it was refused, the runs, data, and home folders of `paths` named in words."""
    spec = BacktestSpec.model_validate(payload)
    run_key = spec.reproduces
    if run_key is None:
        raise ValueError(
            "Expected the spec of a reproduction, which names the run it makes again, got a "
            "backtest's."
        )
    output = executed(executor, spec, advancing(progress), progress.check).output
    if not isinstance(output, BacktestOutput) or output.reproduction is None:
        raise ValueError(
            f"Expected the verdict of a reproduction, got the output of a {output.kind}."
        )
    verdict = output.reproduction
    if isinstance(verdict, ReproductionRefused):
        verdict = ReproductionRefused(reason=without_folders(verdict.reason, paths, run_key))
    return verdict.model_dump(mode="json")
