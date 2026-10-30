"""`Run.report()` (step 2.12): the run's text summary prints its fidelity eras, its metrics split
by the fidelity of each trade's entry, and its fidelity check's deltas (Done means 2), or why a
run has no check; `reconcile` stops until fill exports exist (D-51)."""

import os
from pathlib import Path

import pytest

import fefat as ff
import gen_fixtures
from fefat.config import resolve_paths
from notebook_runs import breakout, store_with


@pytest.fixture(name="ticks_for_the_last_sessions")
def fixture_ticks_for_the_last_sessions() -> None:
    """ESH2026's sessions from 2026-03-02 to 03-13, with ticks from 03-10 alone."""
    synthetic = resolve_paths(os.environ).data_dir / "synthetic"
    dates = ["--dates", "2026-03-02..2026-03-13", "--contracts", "ESH2026"]
    assert gen_fixtures.main(["--out", str(synthetic), *dates, "--ticks-from", "2026-03-10"]) == 0


@pytest.mark.usefixtures("ticks_for_the_last_sessions")
def test_the_report_prints_the_metrics_split_by_era_and_the_fidelity_checks_deltas(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Done means 2.
    run = ff.backtest.run(breakout(), "2026-03-02", "2026-03-13")
    capsys.readouterr()

    run.report()

    lines = capsys.readouterr().out.splitlines()
    eras = lines.index("Fidelity eras")
    assert lines[eras + 1 : eras + 3] == [
        "  2026-03-03 to 2026-03-09     5 trade dates  1m",
        "  2026-03-10 to 2026-03-13     4 trade dates  trades",
    ]
    split = lines.index("Trades by the fidelity of their entry")
    groups = run.metrics.breakdowns.fidelity
    assert len(groups) == 2
    for line, (level, group) in zip(lines[split + 1 : split + 3], groups.items(), strict=True):
        assert line.startswith(f"  {level!s:<7} {group.trades} trades, {group.wins} wins")
        assert f"P&L {group.pnl:,.2f}" in line
    check = run.metrics.fidelity_check
    assert isinstance(check, ff.backtest.FidelityCheck)
    assert "Fidelity check from 2026-03-10 to 2026-03-13, each run from flat" in lines
    for rerun, level in ((check.at_one_second, "1s"), (check.at_one_minute, "1m")):
        outcome = rerun.outcome
        assert (
            f"  at {level}: {outcome.trades} trades ({rerun.trades_delta:+d}), "
            f"P&L {outcome.pnl:,.2f} ({rerun.pnl_delta:+,.2f}), maximum drawdown "
            f"{outcome.max_drawdown:,.2f} ({rerun.max_drawdown_delta:+,.2f})"
        ) in lines


def test_a_report_of_a_run_at_one_minute_fidelity_says_why_it_has_no_check(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The amendment of 2026-10-21: a run on 1-minute bars alone, as on your MES, says so.
    store_with("ohlcv-1m")
    run = ff.backtest.run(breakout(), "2026-03-05", "2026-03-09")
    capsys.readouterr()

    run.report()

    assert run.metrics.fidelity_check is None
    assert (
        "No fidelity check: every trade date ran at 1-minute fidelity, so nothing finer measures "
        "the error of the coarser days; it needs a trades or 1-second file in the store."
    ) in capsys.readouterr().out.splitlines()


def test_reconcile_stops_until_fill_exports_exist() -> None:
    store_with("ohlcv-1m")
    run = ff.backtest.run(breakout(), "2026-03-05", "2026-03-09")

    with pytest.raises(NotImplementedError, match=r"got none: reconcile waits .* BACKLOG\.md"):
        ff.backtest.reconcile(run, Path("fills.csv"))
