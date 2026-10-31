"""Step 2.13's trade paths through `ff.backtest.run` on the fixtures' store: every saved run holds
`trade_paths` and `fills` with their schemas and records the mix of its paths' fidelities in
`run.json` (Done means 1); each trade's path runs from its entry's fill to the fill that closes it
through its most adverse point, its MAE (Your checks, on the fixtures); a run saved before the
step is refused as having no trade paths; and `Run.report()` counts the trades by the fidelity of
their paths."""

import json
import shutil

import polars as pl
import pytest

import fefat as ff
from fefat.backtest import FILLS, TRADE_PATHS, Run
from fefat.market import instruments
from fefat.market.calendar import counted
from fefat.market.engine_units import instrument_parameters
from fefat.strategy.signal_frame import require_column_types
from notebook_runs import breakout, store_with

WINDOW = ("2026-03-05", "2026-03-09")


@pytest.fixture(name="fixture_store")
def fixture_fixture_store() -> None:
    """The fixtures' ES and BTC trades, 1-second, and 1-minute bars, and BTC's funding, in
    `FEFAT_DATA_DIR`."""
    store_with("trades", "ohlcv-1s", "ohlcv-1m", "funding")


@pytest.mark.usefixtures("fixture_store")
def test_every_saved_run_holds_its_trades_paths_and_the_mix_of_their_fidelities() -> None:
    # Done means 1: the fixtures' days all fill on trades, so every path's fidelity is trades.
    run = ff.backtest.run(breakout(), *WINDOW)

    for name, schema in (("trade_paths", TRADE_PATHS), ("fills", FILLS)):
        frame = pl.read_parquet(run.folder / f"{name}.parquet")
        require_column_types(frame, schema, f"the {name} artifact's")
    trades, paths = run.trades, run.trade_paths
    assert trades.height > 1
    assert paths.get_column("trade").unique().sort().to_list() == list(range(trades.height))
    recorded = json.loads((run.folder / "run.json").read_bytes())["path_fidelities"]
    assert recorded == [{"fidelity": "trades", "trades": trades.height}]
    assert run.record.path_fidelities[0].trades == trades.height


@pytest.mark.usefixtures("fixture_store")
def test_each_trades_path_runs_from_its_entry_to_the_fill_that_closes_it_through_its_mae() -> None:
    # Your checks: a path starts at its entry's fill and ends at the fill that closes it, the
    # trade's exit price when one fill closed it, and its most adverse price is the trade's MAE.
    # A roll's legs, which no excursion counts, and a bar's possible adverse extreme are left out.
    run = ff.backtest.run(breakout(), *WINDOW)
    tick = instrument_parameters(instruments.get("ES")).tick
    roles = run.fills.select("order", "role")
    points = run.trade_paths.join(roles, on="order", how="left", maintain_order="left")
    of_the_market = (~pl.col("role").str.starts_with("roll_")).fill_null(True) & (
        pl.col("kind") != "possible_adverse"
    )
    for trade, row in enumerate(run.trades.iter_rows(named=True)):
        path = points.filter(pl.col("trade") == trade)
        first, last = path.row(0, named=True), path.row(-1, named=True)
        assert (first["kind"], first["order"]) == ("fill", row["entry_order"])
        assert (first["ts"], first["price"]) == (row["entry_ts"], row["entry_price"])
        assert (last["kind"], last["ts"]) == ("fill", row["exit_ts"])
        if row["exits"] == 1:
            assert last["price"] == row["exit_price"]
        prices = path.filter(of_the_market).get_column("price")
        sign = 1 if row["side"] == "long" else -1
        worst = prices.min() if sign == 1 else prices.max()
        assert worst == row["entry_price"] - sign * row["mae_ticks"] * tick, row


@pytest.mark.usefixtures("fixture_store")
def test_a_run_saved_before_trade_paths_is_refused_as_having_none() -> None:
    # The step's prompt: runs saved before it show that they have no trade paths, and the
    # artifact schema in their key keeps them from new requests.
    run = ff.backtest.run(breakout(), *WINDOW)
    older = run.folder.with_name("older")
    shutil.copytree(run.folder, older)
    (older / "trade_paths.parquet").unlink()
    record = json.loads((older / "run.json").read_bytes())
    record["versions"]["artifact_schema"] = 1
    del record["path_fidelities"]
    (older / "run.json").write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(ValueError, match=r"got one of schema 1 in .*, which has no trade paths:"):
        Run.open(older)


@pytest.mark.usefixtures("fixture_store")
def test_the_report_counts_the_trades_by_the_fidelity_of_their_paths(
    capsys: pytest.CaptureFixture[str],
) -> None:
    run = ff.backtest.run(breakout(), *WINDOW)
    capsys.readouterr()

    run.report()

    lines = capsys.readouterr().out.splitlines()
    heading = lines.index("Trade paths by their fidelity, the coarsest data each path came from")
    assert lines[heading + 1] == f"  trades  {counted(run.trades.height, 'trade')}"
