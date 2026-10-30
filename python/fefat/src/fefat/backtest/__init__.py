"""Backtests (step 2.10, `02-engine-and-data.md` §5 and §7): `run` backtests a signal strategy in
one call on the store's data through the engine's cache, writes its artifacts and its record,
`run.json`, under `FEFAT_HOME/workspaces/default/artifacts/runs/<run key>/`, and returns a saved
run of the same key instead of running it again:

    import fefat as ff

    run = ff.backtest.run(strategy, start="2026-03-05", end="2026-03-09")
    run.trades; run.fills; run.equity("1d"); run.config; run.hash
    run.metrics.fidelity_check; run.report()

`RunConfig` holds the run's settings (`fefat.backtest.run_config`), the artifacts' schemas are
`fefat.backtest.schemas`, and the record is `fefat.backtest.record`. `fidelity_check` works a
saved run's fidelity check out again (`fefat.backtest.fidelity`, step 2.12), and `reconcile`
waits for fill exports.
"""

from fefat.backtest.fidelity import fidelity_check
from fefat.backtest.metrics import (
    FidelityCheck,
    FidelityEra,
    FidelityRerun,
    PeriodOutcome,
    RefusedCheck,
    running_drawdown,
)
from fefat.backtest.reconcile import reconcile
from fefat.backtest.record import RunRecord
from fefat.backtest.run_config import AppliedRunConfig, RunConfig
from fefat.backtest.runs import Run, run
from fefat.backtest.schemas import (
    ARTIFACT_SCHEMAS,
    COSTS,
    EQUITY,
    EQUITY_DAILY,
    FILLS,
    LOG,
    ORDERS,
    SIGNALS,
    TRADES,
)

__all__ = [
    "ARTIFACT_SCHEMAS",
    "COSTS",
    "EQUITY",
    "EQUITY_DAILY",
    "FILLS",
    "LOG",
    "ORDERS",
    "SIGNALS",
    "TRADES",
    "AppliedRunConfig",
    "FidelityCheck",
    "FidelityEra",
    "FidelityRerun",
    "PeriodOutcome",
    "RefusedCheck",
    "Run",
    "RunConfig",
    "RunRecord",
    "fidelity_check",
    "reconcile",
    "run",
    "running_drawdown",
]
