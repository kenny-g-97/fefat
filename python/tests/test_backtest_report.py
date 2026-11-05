"""`Run.report()` (step 2.12): the run's text summary prints its fidelity eras, its metrics split
by the fidelity of each trade's entry, and its fidelity check's deltas (Done means 2), or why a
run has no check; `reconcile` stops until fill exports exist (D-51); from step 3.7, the
run warns, in its record and its report, where it decides inside the bars it fills on (D-71)."""

import os
import re
from datetime import date
from pathlib import Path

import pytest

import fefat as ff
import gen_fixtures
from fefat.backtest import RunConfig
from fefat.backtest.decision_bars import inside_bar_warnings
from fefat.config import resolve_paths
from fefat.market.fidelity import ONE_MINUTE, FidelityEra
from fefat.market.schema import Timeframe
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
    # Step 3.2: each trade date's signal bars come from its finest level, in eras of their own.
    assert "signal bars built from each trade date's finest data." in lines[1]
    signal_bars = lines.index("Signal bars")
    assert lines[signal_bars + 1 : signal_bars + 3] == lines[eras + 1 : eras + 3]
    # Step 2.13: the mix of path fidelities keeps the order each first closed, so run.json is the
    # same on every run (D-11).
    assert [str(path.fidelity) for path in run.record.path_fidelities] == ["1m", "trades"]
    split = lines.index("Trades by the fidelity of their entry")
    groups = run.metrics.breakdowns.fidelity
    assert len(groups) == 2
    days = {"1m": 5, "trades": 4}
    for line, (level, group) in zip(lines[split + 1 : split + 3], groups.items(), strict=True):
        assert line.startswith(f"  {level!s:<7} {group.trades} trades, {group.wins} wins")
        assert line.endswith(f"P&L {group.pnl:,.2f}, over {days[str(level)]} trade dates")
    check = run.metrics.fidelity_check
    assert isinstance(check, ff.backtest.FidelityCheck)
    assert "Fidelity check from 2026-03-10 to 2026-03-13, each run from flat" in lines
    assert "  baseline at trades, filled on trades for 4 trade dates" in lines
    for rerun, level in ((check.at_one_second, "1s"), (check.at_one_minute, "1m")):
        assert rerun is not None
        outcome = rerun.outcome
        filled = lines.index(f"  at {level}, filled on {level} for 4 trade dates")
        assert lines[filled + 1] == (
            f"    {outcome.trades} trades ({rerun.trades_delta:+d}), "
            f"P&L {outcome.pnl:,.2f} ({rerun.pnl_delta:+,.2f}), maximum drawdown "
            f"{outcome.max_drawdown:,.2f} ({rerun.max_drawdown_delta:+,.2f})"
        )


def test_a_report_of_a_run_at_one_minute_fidelity_says_why_it_has_no_check(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The amendment of 2026-10-21: a run on 1-minute bars alone, as on your MES, says so, and
    # so does a run whose fidelity setting keeps it on 1-minute bars where ticks are stored.
    no_check = (
        "No fidelity check: every trade date ran at 1-minute fidelity, so nothing finer measures "
        "the error of the coarser days; it needs a trades or 1-second file in the store and a run "
        "whose fidelity setting reaches it, as a run without one does."
    )
    store_with("ohlcv-1m")
    on_bars = ff.backtest.run(breakout(), "2026-03-05", "2026-03-09")
    store_with("trades", "ohlcv-1s")
    capped = ff.backtest.run(breakout(), "2026-03-05", "2026-03-09", RunConfig(fidelity=ONE_MINUTE))
    capsys.readouterr()

    for run in (on_bars, capped):
        run.report()

        assert run.metrics.fidelity_check is None
        assert no_check in capsys.readouterr().out.splitlines()


def test_reconcile_stops_until_fill_exports_exist() -> None:
    store_with("ohlcv-1m")
    run = ff.backtest.run(breakout(), "2026-03-05", "2026-03-09")

    with pytest.raises(NotImplementedError, match=r"got none: reconcile waits .* BACKLOG\.md"):
        ff.backtest.reconcile(run, Path("fills.csv"))


def breakout_of(timeframe: str) -> ff.SignalStrategy:
    """The breakout of the fixtures deciding at the closes of `timeframe` bars."""
    strategy = breakout()
    return ff.SignalStrategy(
        instrument="ES",
        timeframe=timeframe,
        features=dict(strategy.features),
        long_entry=strategy.long_entry,
        short_entry=strategy.short_entry,
        execution=strategy.execution,
    )


INSIDE = "filled on 1m bars, inside which the strategy's 90s closes fall: an order decided inside"
"""The warning of a 90-second strategy filling on 1-minute bars, half of whose decisions fall
inside a minute (D-71)."""


def test_a_run_deciding_inside_the_bars_it_fills_on_warns_in_its_record_and_report(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Step 3.7's amendment (D-71): an order decided inside a coarser bar fills at its open, a
    # price from before the decision, until a fill-model version has it wait for the next bar;
    # a run capped at 1-minute bars, and the fidelity check's rerun at 1 minute of one on trades,
    # warn of it, while a 5-minute strategy, each of whose closes ends a minute, does not.
    store_with("trades", "ohlcv-1s", "ohlcv-1m")
    window = ("2026-03-06", "2026-03-09")

    with pytest.warns(UserWarning, match=re.escape(INSIDE)):
        capped = ff.backtest.run(breakout_of("90s"), *window, RunConfig(fidelity=ONE_MINUTE))
    with pytest.warns(
        UserWarning, match="the fidelity check's rerun at 1m filled 2 trade dates from 2026-03-06"
    ):
        on_trades = ff.backtest.run(breakout_of("90s"), *window)
    five = ff.backtest.run(breakout(), *window, RunConfig(fidelity=ONE_MINUTE))
    capsys.readouterr()
    capped.report()

    lines = capsys.readouterr().out.splitlines()
    warned = lines[lines.index("Warnings") + 1 :]
    assert any(INSIDE in line for line in warned)
    assert any(INSIDE in warning for warning in capped.record.warnings)
    assert any("F-ACT-02, D-71" in warning for warning in on_trades.record.warnings)
    assert not any("F-ACT-02" in warning for warning in five.record.warnings)


@pytest.mark.parametrize(
    ("timeframe", "level", "warned"),
    [
        pytest.param("30s", "1m", True, id="finer-than-its-bars"),
        pytest.param("90s", "1m", True, id="not-a-whole-number-of-them"),
        pytest.param("5m", "1m", False, id="a-whole-number-of-them"),
        pytest.param("5m", "1d", True, id="inside-a-daily-bar"),
        pytest.param("30s", "trades", False, id="prints"),
    ],
)
def test_an_era_warns_where_the_strategys_closes_fall_inside_its_bars(
    timeframe: str, level: str, warned: bool
) -> None:
    dates = {"first": date(2026, 3, 6), "last": date(2026, 3, 9), "trade_dates": 2}
    era = FidelityEra.model_validate({**dates, "fidelity": level})

    warnings = inside_bar_warnings(Timeframe.parse(timeframe), [era], None)

    assert bool(warnings) is warned
