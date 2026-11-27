"""A saved run's trades over the API (step 5.8, D-124). `GET /v1/runs/{run}/trades` reads the
trades artifact through DuckDB a page at a time after a keyset cursor, sorted and filtered as
Polars sorts and filters the same artifacts, on the breakout run and on runs of 3,000 and of
50,000 trades made here, whose pages never hold the whole table (Done means 1); `trades.csv`
holds every trade the pages hold under the same filter and order (Done means 3) and
`executions.csv` the run's fills in the order the run made them; and `POST /v1/runs/{run}/query`
answers one SELECT over the run's artifacts in the instrument's units, refusing every other
statement, a file beside them, and an answer past its caps, and naming no folder of this PC."""

import base64
import csv
import io
import json
import os
import shutil
import time
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from fastapi.testclient import TestClient

from fefat.backtest import FILLS, TRADES, Run
from fefat.backtest.schemas import UNIT_COLUMNS, Unit
from fefat.config import resolve_paths
from fefat.market.calendar import utc_text
from fefat.market.engine_units import PRICE_SCALE, micro_units, money_text, price_text
from fefat.reference.units import instant_nanoseconds
from fefat_app.container import Container
from fefat_app.services.trade_table import _in_units
from local_server import logged_in
from test_run_records import the_run

FIFTY_THOUSAND = 50_000
PAGE = 500
SORTS = ["entry_ts", "exit_ts", "pnl", "r_multiple", "held", "mae_ticks", "mfe_ticks"]
SECOND = 1_000_000_000
TICK = 250_000_000
"""ES's tick in 1e-9 units of its price."""
TICK_WORTH = 12_500_000
"""What ES's tick is worth on one lot, in micro-units."""
LOT_FEE = 2_870_000
"""What a fill of the runs made here pays a lot, in micro-units."""
REASONS = {0: "stop", 1: "target_1", 2: "exit", 3: "flat_by"}

# A trade of the runs made here, the `i`th: one to three lots, long and short in turn, its
# decision 100 minutes after the last one's, longer than any is held; every tenth without a stop,
# so without R; a net P&L of each sign, zero among them; and an exit price a third of a tick off
# the tick on every third trade, as an average of exits is.
NTH = pl.col("i")
LOTS = 1 + NTH % 3
ENTRY_TS = 1_451_901_600 * SECOND + NTH * 6_000 * SECOND + SECOND
EXIT_TS = ENTRY_TS + (NTH % 97 + 1) * 60 * SECOND
ENTRY_PRICE = 5_000_000_000_000 + (NTH % 400) * TICK
EXIT_PRICE = ENTRY_PRICE + ((NTH * 7919) % 81 - 40) * TICK
AVERAGED_EXIT = EXIT_PRICE.cast(pl.Float64) + pl.when(NTH % 3 == 1).then(TICK / 3).otherwise(0.0)
PNL = ((NTH * 7919) % 1001 - 500) * TICK_WORTH
RISK_TICKS = pl.when(NTH % 10 == 0).then(None).otherwise(8 + NTH % 5)
RISK = RISK_TICKS * TICK_WORTH * LOTS
MAE_TICKS = (NTH * 31) % 40
MFE_TICKS = (NTH * 17) % 60
TRADE_DATE = pl.lit(date(2016, 1, 4)) + pl.duration(days=NTH // 14)
REASON = (NTH % 4).replace_strict(REASONS, return_dtype=pl.String)
LONG = NTH % 2 == 0


@pytest.fixture
def run(client: TestClient, container: Container, breakout_workspace: Path) -> Run:
    """The saved breakout, logged in and listed, so that the index holds its row."""
    logged_in(client, container)
    shutil.copytree(breakout_workspace, resolve_paths(os.environ).workspace_dir)
    assert client.get("/v1/runs").status_code == 200
    return the_run()


def made_trades(numbers: pl.DataFrame) -> pl.DataFrame:
    """The trades artifact of the trades `numbers` counts (the expressions above), its path's
    fidelity on trades and on 1-minute bars in turn by blocks of 500."""
    return numbers.select(
        side=pl.when(LONG).then(pl.lit("long")).otherwise(pl.lit("short")),
        lots=LOTS,
        entry_order=2 * NTH + 1,
        entry_decision=ENTRY_TS - SECOND,
        entry_ts=ENTRY_TS,
        entry_price=ENTRY_PRICE,
        entry_contract=pl.lit("ESH2026"),
        exits=pl.lit(1),
        exit_price=AVERAGED_EXIT,
        exit_ts=EXIT_TS,
        exit_reason=REASON,
        exit_contract=pl.lit("ESH2026"),
        rolls=pl.lit(0),
        gross_pnl=PNL + 2 * LOT_FEE * LOTS,
        fees=2 * LOT_FEE * LOTS,
        funding=pl.lit(0),
        pnl=PNL,
        initial_risk_ticks=RISK_TICKS,
        mae_ticks=MAE_TICKS,
        mfe_ticks=MFE_TICKS,
        mae=MAE_TICKS * TICK_WORTH * LOTS,
        mfe=MFE_TICKS * TICK_WORTH * LOTS,
        max_drawdown_ticks=MAE_TICKS,
        max_drawdown=MAE_TICKS * TICK_WORTH * LOTS,
        path_fidelity=pl.when((NTH // 500) % 2 == 0).then(pl.lit("trades")).otherwise(pl.lit("1m")),
        entry_trade_date=TRADE_DATE,
        initial_risk=RISK,
        r_multiple=PNL / RISK,
        mae_r=MAE_TICKS * TICK_WORTH * LOTS / RISK,
        mfe_r=MFE_TICKS * TICK_WORTH * LOTS / RISK,
    ).select([pl.col(name).cast(dtype) for name, dtype in TRADES.items()])


def made_fills(numbers: pl.DataFrame, entry: bool) -> pl.DataFrame:
    """The entry fills of the trades `numbers` counts, or their exit fills: on 1-minute bars and
    on trades in turn by blocks of 250 trades, which their paths' fidelity is not, and ambiguous
    on an eleventh of the entries and on a seventh of the exits."""
    buys = LONG if entry else ~LONG
    return numbers.select(
        order=2 * NTH + (1 if entry else 2),
        role=pl.lit("entry") if entry else REASON,
        side=pl.when(buys).then(pl.lit("buy")).otherwise(pl.lit("sell")),
        lots=LOTS,
        ts=ENTRY_TS if entry else EXIT_TS,
        price=ENTRY_PRICE if entry else EXIT_PRICE,
        rule=pl.lit("F-MKT-01"),
        fidelity=pl.when((NTH // 250) % 2 == 0).then(pl.lit("1m")).otherwise(pl.lit("trades")),
        liquidity=pl.lit("taker"),
        slippage_ticks=pl.lit(0),
        ambiguous=(NTH % 11 == 5) if entry else (NTH % 7 == 3),
        size_exceeded=pl.lit(False),
        fee=LOT_FEE * LOTS,
        cash=pl.lit(0),
        contract=pl.lit("ESH2026"),
        trade_date=TRADE_DATE,
    ).select([pl.col(name).cast(dtype) for name, dtype in FILLS.items()])


def made_paths(numbers: pl.DataFrame) -> pl.DataFrame:
    """Each made trade's path: its entry fill, a minute's mark, and its exit fill."""
    points = [
        (ENTRY_TS, ENTRY_PRICE, "fill", 2 * NTH + 1),
        (ENTRY_TS + 30 * SECOND, ENTRY_PRICE, "minute", pl.lit(None, dtype=pl.Int64)),
        (EXIT_TS, EXIT_PRICE, "fill", 2 * NTH + 2),
    ]
    return (
        pl.concat(
            [
                numbers.select(trade=NTH, ts=ts, price=price, kind=pl.lit(kind), order=order)
                for ts, price, kind, order in points
            ]
        )
        .sort("trade", "ts")
        .with_columns(pl.col("order").cast(pl.UInt64))
    )


def made(run: Run, count: int) -> dict[str, pl.DataFrame]:
    """The run's folder holding `count` trades made here in place of its own, with their fills
    and paths, as a run of years would hold them."""
    numbers = pl.DataFrame({"i": pl.int_range(0, count, dtype=pl.Int64, eager=True)})
    fills = pl.concat([made_fills(numbers, entry=True), made_fills(numbers, entry=False)])
    artifacts = {
        "trades": made_trades(numbers),
        "fills": fills.sort("ts"),
        "trade_paths": made_paths(numbers),
    }
    for name, frame in artifacts.items():
        frame.write_parquet(run.folder / f"{name}.parquet", compression="zstd")
    return artifacts


def shown(artifacts: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """The trades as the table shows them, worked out in Polars: each its row, its time held, its
    entry order's first fill's fidelity, and whether a fill its path names is ambiguous."""
    fills = artifacts["fills"]
    entries = fills.select(pl.col("order").alias("entry_order"), "fidelity").unique(
        "entry_order", keep="first", maintain_order=True
    )
    marks = (
        artifacts["trade_paths"]
        .filter(pl.col("kind") == "fill")
        .join(fills.select("order", "ts", "ambiguous"), on=["order", "ts"])
        .group_by("trade")
        .agg(pl.col("ambiguous").any())
    )
    return (
        artifacts["trades"]
        .with_row_index("trade")
        .with_columns(pl.col("trade").cast(pl.Int64), held=pl.col("exit_ts") - pl.col("entry_ts"))
        .join(entries, on="entry_order", how="left", maintain_order="left")
        .join(marks, on="trade", how="left", maintain_order="left")
        .with_columns(pl.col("ambiguous").fill_null(False))
    )


def walked(
    client: TestClient, run: Run, **asked: Any
) -> tuple[list[dict[str, Any]], int, list[str]]:
    """Every trade the pages of `asked` hold, read from the first page to the last, with the
    total the pages give and the cursors that asked for the pages after the first; each page at
    most its limit."""
    trades: list[dict[str, Any]] = []
    cursor: str | None = None
    limit = asked.get("limit", 200)
    cursors: list[str] = []
    while True:
        params = {**asked} if cursor is None else {**asked, "cursor": cursor}
        answer = client.get(f"/v1/runs/{run.hash}/trades", params=params)
        assert answer.status_code == 200, answer.text
        page = answer.json()
        assert len(page["trades"]) <= limit
        trades.extend(page["trades"])
        cursor = page["next_cursor"]
        if cursor is None:
            return trades, page["total"], cursors
        cursors.append(cursor)


def csrf(client: TestClient) -> dict[str, str]:
    """The CSRF header of the client's login session, which a change of state carries."""
    return {"X-CSRF-Token": client.get("/v1/me").json()["csrf_token"]}


def asked_sql(client: TestClient, run: Run, sql: str) -> Any:
    """The answer of the run's query route to `sql`."""
    return client.post(f"/v1/runs/{run.hash}/query", json={"sql": sql}, headers=csrf(client))


def test_a_page_is_the_sdks_trades_with_their_fills_in_the_runs_order(
    client: TestClient, run: Run
) -> None:
    # Done means 1: API equals SDK, every column of the trades artifact sent as the phase says.
    expected = shown({"trades": run.trades, "fills": run.fills, "trade_paths": run.trade_paths})

    page = client.get(f"/v1/runs/{run.hash}/trades").json()

    assert page["total"] == run.trades.height == len(page["trades"])
    assert page["next_cursor"] is None
    for answered, trade in zip(page["trades"], expected.iter_rows(named=True), strict=True):
        assert answered["trade"] == trade["trade"]
        for same in ("entry_order", "side", "lots", "exit_reason", "entry_contract", "rolls"):
            assert answered[same] == trade[same], same
        for instant in ("entry_ts", "exit_ts", "entry_decision"):
            assert answered[instant] == utc_text(trade[instant]), instant
        assert answered["entry_price"] == price_text(trade["entry_price"])
        assert Decimal(answered["exit_price"]).scaleb(9) == Decimal(repr(trade["exit_price"]))
        for money in ("pnl", "gross_pnl", "fees", "funding", "mae", "mfe", "max_drawdown"):
            assert answered[money] == money_text(trade[money]), money
        assert answered["initial_risk"] == money_text(trade["initial_risk"])
        for figure in ("r_multiple", "mae_r", "mfe_r", "mae_ticks", "mfe_ticks"):
            assert answered[figure] == trade[figure], figure
        assert answered["held_minutes"] == trade["held"] / (60 * SECOND)
        assert answered["fidelity"] == trade["fidelity"]
        assert answered["path_fidelity"] == trade["path_fidelity"]
        assert answered["ambiguous"] is trade["ambiguous"]
        assert answered["entry_trade_date"] == trade["entry_trade_date"].isoformat()


def test_fifty_thousand_trades_page_without_a_gap_a_repeat_or_the_whole_table(
    client: TestClient, run: Run
) -> None:
    # Done means 1: a 50,000-trade synthetic run pages without loading everything.
    made(run, FIFTY_THOUSAND)

    first = client.get(f"/v1/runs/{run.hash}/trades", params={"limit": PAGE}).json()
    trades, total, cursors = walked(client, run, limit=PAGE)

    assert (first["total"], len(first["trades"])) == (FIFTY_THOUSAND, PAGE)
    assert (total, len(cursors) + 1) == (FIFTY_THOUSAND, FIFTY_THOUSAND // PAGE)
    assert [trade["trade"] for trade in trades] == list(range(FIFTY_THOUSAND))
    timings: list[float] = []
    for _ in range(3):
        started = time.perf_counter()
        deepest = client.get(
            f"/v1/runs/{run.hash}/trades", params={"limit": PAGE, "cursor": cursors[-1]}
        )
        timings.append(time.perf_counter() - started)
        assert deepest.status_code == 200
        assert deepest.json()["trades"][-1]["trade"] == FIFTY_THOUSAND - 1
    assert min(timings) < 1.0, timings


@pytest.mark.parametrize("order", ["asc", "desc"])
@pytest.mark.parametrize("sort", SORTS)
def test_each_sort_both_ways_is_polars_with_nulls_last_and_ties_by_row(
    client: TestClient, run: Run, sort: str, order: str
) -> None:
    # Done means 1: sorting by time, P&L, R, holding time, MAE, and MFE.
    expected = shown(made(run, 3_000))

    trades, total, _ = walked(client, run, sort=sort, order=order, limit=250)

    by = expected.sort([sort, "trade"], descending=[order == "desc", False], nulls_last=True)
    assert total == 3_000
    assert [trade["trade"] for trade in trades] == by.get_column("trade").to_list()


FILTERS = {
    "long": ({"side": "long"}, pl.col("side") == "long"),
    "short": ({"side": "short"}, pl.col("side") == "short"),
    "stops": ({"exit_reason": "stop"}, pl.col("exit_reason") == "stop"),
    "dates": (
        {"start": "2016-02-01", "end": "2016-03-31"},
        pl.col("entry_trade_date").is_between(date(2016, 2, 1), date(2016, 3, 31)),
    ),
    "winning": ({"pnl_sign": "positive"}, pl.col("pnl") > 0),
    "losing": ({"pnl_sign": "negative"}, pl.col("pnl") < 0),
    "flat": ({"pnl_sign": "zero"}, pl.col("pnl") == 0),
    "on trades": ({"fidelity": "trades"}, pl.col("fidelity") == "trades"),
    "on minutes": ({"fidelity": "1m"}, pl.col("fidelity") == "1m"),
    "ambiguous": ({"ambiguous": True}, pl.col("ambiguous")),
    "not ambiguous": ({"ambiguous": False}, ~pl.col("ambiguous")),
    "one trade": ({"trade": 1_234}, pl.col("trade") == 1_234),
    "every filter": (
        {
            "side": "short",
            "exit_reason": "target_1",
            "start": "2016-01-10",
            "end": "2016-06-30",
            "pnl_sign": "negative",
            "fidelity": "trades",
            "ambiguous": False,
        },
        (pl.col("side") == "short")
        & (pl.col("exit_reason") == "target_1")
        & pl.col("entry_trade_date").is_between(date(2016, 1, 10), date(2016, 6, 30))
        & (pl.col("pnl") < 0)
        & (pl.col("fidelity") == "trades")
        & ~pl.col("ambiguous"),
    ),
}


@pytest.mark.parametrize("name", list(FILTERS))
def test_each_filter_keeps_the_trades_polars_keeps(client: TestClient, run: Run, name: str) -> None:
    # Done means 1: filters by side, exit reason, date range, P&L sign, fidelity, ambiguous flag.
    asked, kept = FILTERS[name]
    expected = shown(made(run, 3_000)).filter(kept)

    trades, total, _ = walked(client, run, **asked, limit=250)

    assert expected.height > 0, name
    assert total == expected.height
    assert [trade["trade"] for trade in trades] == expected.get_column("trade").to_list()


def test_a_trade_asked_by_its_row_is_that_trade_alone_or_none(client: TestClient, run: Run) -> None:
    # Step 5.9 (BACKLOG's "The selected trade in the address"): a link to the trade review names
    # its trade's row, which the table may not have read, so the chart reads that trade alone;
    # a row past the run's last keeps none.
    made(run, 3_000)
    trades = f"/v1/runs/{run.hash}/trades"

    one = client.get(trades, params={"trade": 2_999}).json()
    past = client.get(trades, params={"trade": 3_000}).json()
    refused = client.get(trades, params={"trade": -1})

    assert (one["total"], [trade["trade"] for trade in one["trades"]]) == (1, [2_999])
    assert past == {"trades": [], "next_cursor": None, "total": 0}
    assert refused.status_code == 422


def test_losing_stops_by_mae_put_the_worst_mae_first(client: TestClient, run: Run) -> None:
    # Your checks: filter to losing trades with exit reason stop, sort by MAE.
    made(run, 3_000)

    trades, _, _ = walked(
        client, run, pnl_sign="negative", exit_reason="stop", sort="mae_ticks", order="desc"
    )

    excursions = [trade["mae_ticks"] for trade in trades]
    assert len(excursions) > 10
    assert excursions == sorted(excursions, reverse=True)
    assert {trade["exit_reason"] for trade in trades} == {"stop"}
    assert all(Decimal(trade["pnl"]) < 0 for trade in trades)


def test_prices_keep_their_decimals_whole_or_averaged(client: TestClient, run: Run) -> None:
    artifacts = made(run, 3)

    page = client.get(f"/v1/runs/{run.hash}/trades").json()

    exits = artifacts["trades"].get_column("exit_price").to_list()
    assert [Decimal(trade["exit_price"]) for trade in page["trades"]] == [
        Decimal(repr(price)) / PRICE_SCALE for price in exits
    ]
    assert page["trades"][1]["exit_price"].endswith("3333")


def test_a_price_under_a_millionth_is_sent_as_decimal_text(client: TestClient, run: Run) -> None:
    tiny = made(run, 3)["trades"].with_columns(
        entry_price=pl.lit(123, pl.Int64), exit_price=pl.lit(700.0, pl.Float64)
    )
    tiny.write_parquet(run.folder / "trades.parquet")

    page = client.get(f"/v1/runs/{run.hash}/trades").json()

    assert {(trade["entry_price"], trade["exit_price"]) for trade in page["trades"]} == {
        ("0.000000123", "0.0000007")
    }


@pytest.mark.parametrize("cursor", ["not-a-cursor", "eyJzb3J0IjogInBubCJ9"])
def test_a_cursor_no_page_gave_is_refused(client: TestClient, run: Run, cursor: str) -> None:
    answer = client.get(f"/v1/runs/{run.hash}/trades", params={"cursor": cursor})

    assert answer.status_code == 400
    assert "Expected a cursor" in answer.json()["detail"]


@pytest.mark.parametrize(
    "cursor",
    [
        {"sort": "pnl", "order": "asc", "value": 2**63, "trade": 1},
        {"sort": "pnl", "order": "asc", "value": 1.5, "trade": 1},
        {"sort": "entry_ts", "order": "desc", "value": 1, "trade": 2**63},
        {"sort": "r_multiple", "order": "asc", "value": float("inf"), "trade": 1},
        {"sort": "r_multiple", "order": "asc", "value": 10**400, "trade": 1},
    ],
)
def test_a_cursor_whose_figure_no_trade_holds_is_refused(
    client: TestClient, run: Run, cursor: dict[str, Any]
) -> None:
    text = base64.urlsafe_b64encode(json.dumps(cursor).encode()).decode()

    answer = client.get(
        f"/v1/runs/{run.hash}/trades",
        params={"sort": cursor["sort"], "order": cursor["order"], "cursor": text},
    )

    assert answer.status_code == 400
    assert "Expected a cursor" in answer.json()["detail"]


def test_a_cursor_of_another_order_is_refused(client: TestClient, run: Run) -> None:
    made(run, 3_000)
    by_pnl = client.get(f"/v1/runs/{run.hash}/trades", params={"sort": "pnl"}).json()

    answer = client.get(
        f"/v1/runs/{run.hash}/trades", params={"sort": "held", "cursor": by_pnl["next_cursor"]}
    )

    assert answer.status_code == 400
    assert "pnl" in answer.json()["detail"]


@pytest.mark.parametrize(
    "asked",
    [{"limit": 0}, {"limit": 1001}, {"sort": "side"}, {"start": "2026-03-09", "end": "2026-03-05"}],
)
def test_a_page_asked_out_of_bounds_is_refused(
    client: TestClient, run: Run, asked: dict[str, Any]
) -> None:
    answer = client.get(f"/v1/runs/{run.hash}/trades", params=asked)

    assert answer.status_code == 422


def csv_text(value: object) -> str:
    """A value of the API's JSON as a cell of the files: None empty, a flag in lower case."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def test_the_trades_file_holds_the_pages_under_the_same_filter_and_order(
    client: TestClient, run: Run
) -> None:
    # Done means 3: the CSV export matches the API filter.
    made(run, 3_000)
    asked = {"pnl_sign": "negative", "fidelity": "1m", "sort": "pnl", "order": "desc"}
    trades, _, _ = walked(client, run, **asked, limit=250)

    answer = client.get(f"/v1/runs/{run.hash}/trades.csv", params=asked)

    assert answer.status_code == 200
    assert answer.headers["content-type"] == "text/csv; charset=utf-8"
    assert answer.headers["content-disposition"] == (
        f'attachment; filename="breakout-{run.hash[:12]}-trades.csv"'
    )
    header, *rows = list(csv.reader(io.StringIO(answer.text)))
    assert header == list(trades[0])
    assert rows == [[csv_text(value) for value in trade.values()] for trade in trades]


def test_the_executions_file_holds_every_fill_in_the_order_the_run_made_them(
    client: TestClient, run: Run
) -> None:
    answer = client.get(f"/v1/runs/{run.hash}/executions.csv")

    assert answer.status_code == 200
    assert answer.headers["content-disposition"] == (
        f'attachment; filename="breakout-{run.hash[:12]}-executions.csv"'
    )
    header, *rows = list(csv.reader(io.StringIO(answer.text)))
    assert header == list(FILLS)
    fills = run.fills
    assert len(rows) == fills.height
    for row, fill in zip(rows, fills.iter_rows(named=True), strict=True):
        cells = dict(zip(header, row, strict=True))
        assert instant_nanoseconds(cells["ts"]) == fill["ts"]
        assert Decimal(cells["price"]).scaleb(9) == fill["price"]
        assert micro_units(Decimal(cells["fee"])) == fill["fee"]
        assert micro_units(Decimal(cells["cash"])) == fill["cash"]
        assert date.fromisoformat(cells["trade_date"]) == fill["trade_date"]
        for plain in ("order", "lots", "slippage_ticks"):
            assert int(cells[plain]) == fill[plain], plain
        for flag in ("ambiguous", "size_exceeded"):
            assert cells[flag] == csv_text(fill[flag]), flag
        for word in ("role", "side", "rule", "fidelity", "liquidity", "contract"):
            assert cells[word] == fill[word], word


@pytest.mark.parametrize("result", ["trades", "trades.csv", "executions.csv"])
def test_the_trades_need_a_login(client: TestClient, result: str) -> None:
    answer = client.get(f"/v1/runs/{'a' * 64}/{result}")

    assert answer.status_code == 401


@pytest.mark.parametrize("artifact", ["trades", "fills", "trade_paths"])
def test_a_damaged_artifact_of_the_table_says_to_delete_the_folder(
    client: TestClient, run: Run, artifact: str
) -> None:
    path = run.folder / f"{artifact}.parquet"
    path.write_bytes(path.read_bytes()[:64])

    answer = client.get(f"/v1/runs/{run.hash}/trades")

    assert answer.status_code == 409
    assert "incomplete or damaged" in answer.json()["detail"]
    assert run.folder.as_posix() not in answer.json()["detail"]


def test_a_select_answers_in_the_instruments_units(client: TestClient, run: Run) -> None:
    sql = (
        "SELECT count(*) AS trades, sum(pnl) AS pnl, min(entry_price) AS lowest, "
        "min(entry_ts) AS first FROM trades"
    )

    answer = asked_sql(client, run, sql)

    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert [column["name"] for column in body["columns"]] == ["trades", "pnl", "lowest", "first"]
    ((trades, pnl, lowest, first),) = body["rows"]
    assert trades == run.trades.height
    assert Decimal(pnl) == Decimal(money_text(sum(run.trades.get_column("pnl").to_list())))
    assert Decimal(lowest) == Decimal(price_text(min(run.trades.get_column("entry_price"))))
    assert first == utc_text(min(run.trades.get_column("entry_ts")))


@pytest.mark.parametrize(
    "sql",
    [
        "COPY (SELECT * FROM trades) TO 'written.csv'",
        "CREATE TABLE kept AS SELECT * FROM trades",
        "INSERT INTO trades VALUES (1)",
        "ATTACH 'written.duckdb'",
        "INSTALL httpfs",
        "SET threads = 8",
        "PRAGMA version",
        "CALL pragma_version()",
        "EXPLAIN SELECT * FROM trades",
        "SELECT 1; SELECT 2",
        "DROP VIEW trades",
    ],
)
def test_anything_but_one_select_is_refused(client: TestClient, run: Run, sql: str) -> None:
    # The step's tests: the query endpoint rejects writes.
    before = sorted(path.name for path in run.folder.iterdir())

    answer = asked_sql(client, run, sql)

    assert answer.status_code == 400
    assert "one SELECT" in answer.json()["detail"]
    assert sorted(path.name for path in run.folder.iterdir()) == before


def test_a_file_beside_the_runs_artifacts_is_refused(client: TestClient, run: Run) -> None:
    outside = resolve_paths(os.environ).home / "outside.csv"
    outside.write_text("a,b\n1,2\n", encoding="utf-8")
    for read in (
        f"SELECT * FROM read_text('{(run.folder / 'run.json').as_posix()}')",
        f"SELECT * FROM read_csv('{outside.as_posix()}')",
        f"SELECT * FROM glob('{run.folder.as_posix()}/*')",
    ):
        answer = asked_sql(client, run, read)

        assert answer.status_code == 400, read
        assert run.folder.as_posix() not in answer.json()["detail"]
        assert str(run.folder) not in answer.json()["detail"]


def test_an_unbounded_answer_is_refused_and_a_limited_one_answers(
    client: TestClient, run: Run
) -> None:
    # The step's tests: the query endpoint rejects unbounded queries.
    made(run, FIFTY_THOUSAND)

    unbounded = asked_sql(client, run, "SELECT * FROM trades")
    one_row = asked_sql(client, run, "SELECT list(t) FROM trades t")
    limited = asked_sql(client, run, "SELECT trade, pnl FROM trades ORDER BY pnl LIMIT 100")

    assert unbounded.status_code == 400
    assert "10,000 rows" in unbounded.json()["detail"]
    assert one_row.status_code == 400
    assert "4,194,304 bytes" in one_row.json()["detail"]
    assert limited.status_code == 200
    assert len(limited.json()["rows"]) == 100


def test_an_answer_names_no_folder_of_this_pc(client: TestClient, run: Run) -> None:
    views = asked_sql(client, run, "SELECT sql FROM duckdb_views() WHERE NOT internal")
    allowed = asked_sql(client, run, "SELECT current_setting('allowed_paths') AS allowed")

    assert [views.status_code, allowed.status_code] == [200, 200], (views.text, allowed.text)
    texts = [json.dumps(row) for answer in (views, allowed) for row in answer.json()["rows"]]
    assert any(f"run {run.hash[:12]}" in text for text in texts)
    for folder in (run.folder, Path.home()):
        named = (folder.as_posix(), json.dumps(str(folder))[1:-1])
        assert not [text for text in texts if any(name in text for name in named)], folder


def test_the_trades_view_holds_the_trade_tables_figures(client: TestClient, run: Run) -> None:
    # The views' units (`UNIT_COLUMNS`) against `TradeRow`'s, which name each column's apart.
    columns = list(UNIT_COLUMNS["trades"])
    sql = f"SELECT {', '.join(columns)} FROM trades ORDER BY trade"

    answer = asked_sql(client, run, sql).json()
    page = client.get(f"/v1/runs/{run.hash}/trades").json()

    assert len(answer["rows"]) == len(page["trades"]) == run.trades.height
    for row, trade in zip(answer["rows"], page["trades"], strict=True):
        for column, value in zip(columns, row, strict=True):
            assert figure(value) == figure(trade[column]), column


def figure(value: object) -> object:
    """A decimal as the number it writes, whatever zeros end it; an instant, ending in Z, and
    anything else as it is."""
    if isinstance(value, float):
        return Decimal(repr(value))
    if isinstance(value, str) and not value.endswith("Z"):
        return Decimal(value)
    return value


def test_a_fills_value_in_engine_units_that_is_no_whole_number_is_refused() -> None:
    # The SDK's reader holds the fills' columns to their types, so no saved run reaches this.
    with pytest.raises(ValueError, match="whole number of price units in the fills' price"):
        _in_units(1.5, Unit.PRICE, "price")


def test_the_query_of_an_unknown_run_answers_404(client: TestClient, run: Run) -> None:
    assert run.hash != "e" * 64

    answer = client.post(
        f"/v1/runs/{'e' * 64}/query", json={"sql": "SELECT 1"}, headers=csrf(client)
    )

    assert answer.status_code == 404
    assert "names none" in answer.json()["detail"]
