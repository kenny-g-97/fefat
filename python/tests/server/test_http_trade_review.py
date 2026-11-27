"""`GET /v1/runs/{run}/chart` of step 5.9 (D-93): a page of a saved run's chart, its bars at the
prices each contract traded at, the strategy's features beside them, and the trades the page
shows, each with every fill on the bar it lies on and its stop and target levels, on the breakout
run of the fixtures' 1-minute bars. Done means 2: every marker's time and price is the fills
ledger's for the window. A page of a run of 50,000 trades and 200,000 signal bars reads its own
window alone."""

import os
import shutil
import time
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from fastapi.testclient import TestClient

import fefat as ff
from fefat.backtest import Run
from fefat.config import resolve_paths
from fefat.market.calendar import utc_text
from fefat.market.engine_units import PRICE_SCALE, price_text
from fefat.reference.units import instant_nanoseconds
from fefat_app.container import Container
from local_server import logged_in
from notebook_runs import store_with
from test_http_trades import csrf, made
from test_run_records import the_run

SECOND = 1_000_000_000
FIVE_MINUTES = 5 * 60 * SECOND
TICK = 250_000_000
"""ES's tick in 1e-9 units of its price."""
MARCH_6 = date(2026, 3, 6)
RUN_WINDOW = ("2026-03-05", "2026-03-09")
"""The breakout workspace's window, the conftest's."""
DEADLINE_SECONDS = 60
"""How long a test waits for a job a worker of the pool runs."""


@pytest.fixture
def run(client: TestClient, container: Container, breakout_workspace: Path) -> Run:
    """The saved breakout, logged in and listed, so that the index holds its row, beside the
    1-minute bars it read."""
    logged_in(client, container)
    shutil.copytree(breakout_workspace, resolve_paths(os.environ).workspace_dir)
    store_with("ohlcv-1m")
    assert client.get("/v1/runs").status_code == 200
    return the_run()


def chart_pages(client: TestClient, run: Run, start: str, end: str) -> list[dict[str, Any]]:
    """Every page of the run's chart from `start` to `end`, each `next_from` the next `from`."""
    pages: list[dict[str, Any]] = []
    start_at: str | None = start
    while start_at is not None:
        answer = client.get(f"/v1/runs/{run.hash}/chart", params={"from": start_at, "to": end})
        assert answer.status_code == 200, answer.text
        pages.append(answer.json())
        start_at = pages[-1]["next_from"]
    return pages


def trades_of(pages: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """The trades the pages show, by their entry order: a trade on two pages is the same one."""
    return {trade["entry_order"]: trade for page in pages for trade in page["trades"]}


def ledger(run: Run) -> pl.DataFrame:
    """Each fill of each trade of the run, worked out in Polars from its paths and its fills."""
    points = run.trade_paths.filter(pl.col("kind") == "fill").select("trade", "order", "ts")
    return points.join(run.fills, on=["order", "ts"]).sort("trade", "ts", "order")


def test_every_marker_is_the_fills_ledger_for_the_window(client: TestClient, run: Run) -> None:
    # Done means 2: every marker's time and price equals the fills ledger for the window, and
    # every fill of each trade the chart shows is there.
    pages = chart_pages(client, run, *RUN_WINDOW)

    shown = trades_of(pages)

    expected = ledger(run)
    assert sorted(shown) == sorted(run.trades.get_column("entry_order").to_list())
    for trade in shown.values():
        fills = expected.filter(pl.col("trade") == trade["trade"])
        assert [(fill["order"], fill["time"], fill["price"]) for fill in trade["fills"]] == [
            (row["order"], utc_text(row["ts"]), price_text(row["price"]))
            for row in fills.iter_rows(named=True)
        ], trade["trade"]
        assert [(fill["side"], fill["role"], fill["lots"]) for fill in trade["fills"]] == [
            (row["side"], row["role"], row["lots"]) for row in fills.iter_rows(named=True)
        ]


def test_each_fill_stands_on_the_bar_its_fidelity_places_it_on(
    client: TestClient, run: Run
) -> None:
    # F-BAR-06, the step's "one bar late": a fill on a bar carries the bar's close, so a
    # 1-minute bar's fill lies on the 5-minute bar with ts_open < ts <= ts_close.
    pages = chart_pages(client, run, *RUN_WINDOW)

    bars = ff.market.load("ES", "5m", *RUN_WINDOW).collect()

    spans = {
        opened // SECOND: (opened, closed)
        for opened, closed in bars.select("ts_open", "ts_close").iter_rows()
    }
    drawn = {time for page in pages for time in page["bars"]["time"]}
    fills = [fill for trade in trades_of(pages).values() for fill in trade["fills"]]
    assert {fill["fidelity"] for fill in fills} == {"1m"}
    for fill in fills:
        opened, closed = spans[fill["bar_time"]]
        assert fill["bar_time"] in drawn
        assert opened < instant_nanoseconds(fill["time"]) <= closed, fill


def test_a_trade_carries_its_stop_and_its_target_as_the_orders_hold_them(
    client: TestClient, run: Run
) -> None:
    shown = trades_of(chart_pages(client, run, *RUN_WINDOW))

    for trade in run.trades.iter_rows(named=True):
        legs = run.orders.filter(pl.col("bracket_of") == trade["entry_order"]).sort("id")
        stop = legs.filter(pl.col("role") == "stop").get_column("price").to_list()
        target = legs.filter(pl.col("role") == "target_1").get_column("price").to_list()
        first = trade["entry_price"] - trade["initial_risk_ticks"] * TICK
        drawn = shown[trade["entry_order"]]
        assert drawn["stop"] == {"first": price_text(first), "last": price_text(stop[-1])}
        assert drawn["targets"] == [price_text(target[-1])]


def test_the_atr_its_stop_reads_is_in_points_and_the_highest_as_the_signals_hold_it(
    client: TestClient, run: Run
) -> None:
    # The builder's answer at the plan: a feature the exit rules read as a distance is in the
    # instrument's units, every other as the signals hold it.
    (page,) = chart_pages(client, run, "2026-03-06", "2026-03-06")

    features = {feature["name"]: feature for feature in page["features"]}

    bars = ff.market.load("ES", "5m", "2026-03-06", "2026-03-06").collect()
    signals = bars.select("ts_close").join(
        run.signals.select("ts_close", "highest", "atr"), on="ts_close", how="left"
    )
    assert [(name, feature["unit"]) for name, feature in features.items()] == [
        ("highest", "as_stored"),
        ("atr", "price"),
    ]
    assert features["atr"]["values"] == [
        None if value is None else value / PRICE_SCALE for value in signals.get_column("atr")
    ]
    assert features["highest"]["values"] == [
        None if value is None else float(value) for value in signals.get_column("highest")
    ]
    assert len(page["bars"]["time"]) == bars.height
    assert page["tick_size"] == "0.25"


def test_a_window_of_one_day_shows_the_trades_on_its_bars_alone(
    client: TestClient, run: Run
) -> None:
    (page,) = chart_pages(client, run, "2026-03-06", "2026-03-06")

    shown = {trade["entry_order"] for trade in page["trades"]}

    on_the_day = run.trades.with_row_index("trade").join(
        ledger(run).filter(pl.col("trade_date") == MARCH_6).select(pl.col("trade").cast(pl.UInt32)),
        on="trade",
        how="semi",
    )
    assert shown == set(on_the_day.get_column("entry_order").to_list())
    assert len(shown) < run.trades.height


def long_signals(run: Run, count: int) -> None:
    """The run's signals with `count` rows, its own last, the rest 5-minute bars before them, as
    a run of years would hold them."""
    signals = run.signals
    earlier = count - signals.height
    first = signals.item(0, "ts_close")
    before = (
        signals.head(1)
        .select(pl.all().repeat_by(earlier).explode())
        .with_columns(ts_close=first - FIVE_MINUTES * pl.int_range(earlier, 0, -1, dtype=pl.Int64))
    )
    pl.concat([before, signals]).write_parquet(run.folder / "signals.parquet", compression="zstd")


def test_a_page_of_a_long_run_reads_its_window_alone(client: TestClient, run: Run) -> None:
    # The step's prompt: "a 200,000-bar run stays responsive". A page reads its own bars and the
    # signals of its window, beside the fills of every trade, never a whole run's bars.
    made(run, 50_000)
    long_signals(run, 200_000)
    asked = {"from": "2026-03-06", "to": "2026-03-06"}

    took: list[float] = []
    answers = []
    for _ in range(3):
        began = time.perf_counter()
        answers.append(client.get(f"/v1/runs/{run.hash}/chart", params=asked))
        took.append(time.perf_counter() - began)

    print(
        f"a page of a run of 50,000 trades answered in {', '.join(f'{each:.3f}' for each in took)} s"
    )
    assert [answer.status_code for answer in answers] == [200] * 3
    page = answers[-1].json()
    assert page["trades"] == []
    assert {len(feature["values"]) for feature in page["features"]} == {len(page["bars"]["time"])}
    assert min(took) < 3.0


def test_an_unknown_run_answers_404_and_a_damaged_path_409(client: TestClient, run: Run) -> None:
    asked = {"from": "2026-03-06", "to": "2026-03-06"}
    unknown = client.get(f"/v1/runs/{'0' * 64}/chart", params=asked)
    (run.folder / "trade_paths.parquet").write_bytes(b"not a parquet file")

    damaged = client.get(f"/v1/runs/{run.hash}/chart", params=asked)

    assert (unknown.status_code, damaged.status_code) == (404, 409)
    assert str(resolve_paths(os.environ).home) not in damaged.json()["detail"]


def test_a_window_the_sdk_refuses_answers_400_and_a_malformed_one_422(
    client: TestClient, run: Run
) -> None:
    backwards = client.get(
        f"/v1/runs/{run.hash}/chart", params={"from": "2026-03-09", "to": "2026-03-06"}
    )
    malformed = client.get(
        f"/v1/runs/{run.hash}/chart", params={"from": "March", "to": "2026-03-06"}
    )

    assert (backwards.status_code, malformed.status_code) == (400, 422)
    assert "on or before the end" in backwards.json()["detail"]


def test_the_chart_needs_a_login(client: TestClient) -> None:
    answer = client.get(
        f"/v1/runs/{'0' * 64}/chart", params={"from": "2026-03-06", "to": "2026-03-06"}
    )

    assert answer.status_code == 401


def finished(client: TestClient, job_id: str) -> dict[str, Any]:
    """The job `job_id` as it ended, read until then, which a worker of the pool runs."""
    deadline = time.monotonic() + DEADLINE_SECONDS
    job = client.get(f"/v1/jobs/{job_id}").json()
    while job["status"] in ("queued", "running") and time.monotonic() < deadline:
        time.sleep(0.1)
        job = client.get(f"/v1/jobs/{job_id}").json()
    return job


def test_an_explanation_is_a_job_whose_fills_are_the_ledgers(client: TestClient, run: Run) -> None:
    # Done means 2: the explain endpoint's fills equal the ledger. D-93: it answers 202 with an
    # `explain` job, whose result is the explanation, the reference engine's log as data.
    trade = run.trades.row(2, named=True)

    started = client.post(
        f"/v1/runs/{run.hash}/explain/{trade['entry_order']}", headers=csrf(client)
    )
    ended = finished(client, started.json()["id"])

    assert started.status_code == 202
    assert {name: started.json()[name] for name in ("kind", "payload", "status")} == {
        "kind": "explain",
        "payload": {"run_key": run.hash, "trade_id": trade["entry_order"]},
        "status": "queued",
    }
    assert (ended["status"], ended["error"]) == ("succeeded", None)
    explained = ended["result"]
    fills = ledger(run).filter(pl.col("trade") == 2)
    assert [(fill["order"], fill["time"], fill["price"]) for fill in explained["fills"]] == [
        (row["order"], utc_text(row["ts"]), price_text(row["price"]))
        for row in fills.iter_rows(named=True)
    ]
    filled = {
        (event["order"], event["time"])
        for event in explained["events"]
        if event["kind"] == "filled"
    }
    assert {(fill["order"], fill["time"]) for fill in explained["fills"]} <= filled
    assert explained["kind"] == "explained"
    assert explained["heading"].startswith(f"Trade {trade['entry_order']}: long 1 ES")
    assert explained["replayed"].startswith("Replayed through the reference engine on 1-minute")


def test_a_replay_refused_is_explained_in_words_that_name_no_folder_of_this_pc(
    client: TestClient, run: Run
) -> None:
    # The amendment: a refusal reads in the trader's words; D-80: no local path leaves the PC.
    paths = resolve_paths(os.environ)
    shutil.rmtree(paths.data_dir / "synthetic" / "ohlcv-1m")
    trade_id = run.trades.item(0, "entry_order")

    started = client.post(f"/v1/runs/{run.hash}/explain/{trade_id}", headers=csrf(client))
    ended = finished(client, started.json()["id"])

    assert ended["status"] == "succeeded"
    refused = ended["result"]
    assert (refused["kind"], refused["trade_id"]) == ("refused", trade_id)
    assert "its data was deleted since the run" in refused["reason"]
    assert refused["reason"].endswith("The store read: your data folder.")
    assert str(paths.home) not in refused["reason"]


def test_an_id_that_is_no_trades_is_refused_and_queues_no_job(client: TestClient, run: Run) -> None:
    unknown = client.post(f"/v1/runs/{run.hash}/explain/2", headers=csrf(client))
    unsigned = client.post(f"/v1/runs/{run.hash}/explain/{run.trades.item(0, 'entry_order')}")

    assert (unknown.status_code, unsigned.status_code) == (404, 403)
    assert "its entry order, such as 1, " in unknown.json()["detail"]
    assert [job for job in client.get("/v1/jobs").json() if job["kind"] == "explain"] == []
