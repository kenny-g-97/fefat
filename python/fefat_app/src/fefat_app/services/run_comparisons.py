"""Saved runs side by side over the API (step 5.10, D-126): the runs' service opens each run, and
its curve is read under that run's own guard, so that a file gone or damaged is named by its run
rather than by another's folder; runs the SDK cannot set side by side, as those in two currencies
or one run twice, are refused with `ResultsRefusedError`."""

from collections.abc import Sequence

from fefat.backtest import Run
from fefat.backtest.compare import RunComparison, ShareCurve, share_curve, side_by_side
from fefat_app.runs import ResultsRefusedError
from fefat_app.services.runs import Runs


def compared(runs: Runs, addresses: Sequence[str]) -> RunComparison:
    """The saved runs of `addresses`, ids or run keys, side by side, the first the reference
    (`ff.backtest.compare_runs`), each refused as `Runs.reading` refuses it."""
    opened: list[Run] = []
    curves: list[ShareCurve] = []
    for address in addresses:
        with runs.reading(address) as run:
            opened.append(run)
            curves.append(share_curve(run))
    try:
        return side_by_side(opened, curves)
    except ValueError as refused:
        raise ResultsRefusedError(str(refused)) from refused
