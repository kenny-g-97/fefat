"""Simulated fills against real ones (step 2.12, `02` §8 item 6): `reconcile(run, fills_csv)`
is to match a run's fills with a broker's or prop platform's export of the trader's own by time
and compare their slippage. No fill export is on this PC (D-51), so it says so and stops until
the first export arrives (`docs/masterplan/BACKLOG.md`, "Real fill exports for `reconcile`")."""

from pathlib import Path
from typing import TYPE_CHECKING, NoReturn

if TYPE_CHECKING:
    from fefat.backtest.runs import Run


def reconcile(run: "Run", fills_csv: Path) -> NoReturn:
    """Refuses with the reason: no fill exports to reconcile with yet."""
    raise NotImplementedError(
        f"Expected fill exports to reconcile run {run.hash[:12]} with {fills_csv}, got none: "
        "reconcile waits for the first broker or prop-platform export (D-51, BACKLOG.md, "
        "'Real fill exports for reconcile')."
    )
