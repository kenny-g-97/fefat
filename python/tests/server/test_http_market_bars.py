"""`GET /v1/market/bars` of step 5.1 (D-93, `01-architecture.md` section 7): `load`'s bars of a
window, a page of at most 20,000 at a time, column by column, with no number past 2^53, and the
instant the next page opens at. Done means 2: a day of 5-minute ES bars in under 300 ms warm, on
the synthetic fixtures."""

import time
from typing import Any

import polars as pl
import pytest
from fastapi.testclient import TestClient

import fefat as ff
from fefat_app.container import Container
from local_server import logged_in
from notebook_runs import store_with

PROBLEM = "application/problem+json"
BARS = "/v1/market/bars"
ONE_DAY_OF_ES = {"instrument": "ES", "timeframe": "5m", "from": "2026-03-06", "to": "2026-03-06"}
PRICE_SCALE = 1_000_000_000


def as_sent(bars: pl.DataFrame) -> dict[str, list[Any]]:
    """`load`'s bars as the API sends them: by open, then contract, their opens in seconds, their
    trade dates as text, and their prices in the instrument's units."""
    return (
        bars.sort("ts_open", "contract")
        .select(
            time=pl.col("ts_open") // PRICE_SCALE,
            trade_date=pl.col("trade_date").dt.to_string("%Y-%m-%d"),
            open=pl.col("open") / PRICE_SCALE,
            high=pl.col("high") / PRICE_SCALE,
            low=pl.col("low") / PRICE_SCALE,
            close=pl.col("close") / PRICE_SCALE,
            volume=pl.col("volume"),
            contract=pl.col("contract"),
        )
        .to_dict(as_series=False)
    )


def pages_of(client: TestClient, asked: dict[str, str]) -> list[dict[str, Any]]:
    """Every page of the window `asked`, each page's `next_from` the next one's `from`."""
    pages = [client.get(BARS, params=asked).json()]
    while pages[-1]["next_from"] is not None:
        pages.append(client.get(BARS, params={**asked, "from": pages[-1]["next_from"]}).json())
    return pages


def joined(pages: list[dict[str, Any]]) -> dict[str, list[Any]]:
    return {
        name: [value for page in pages for value in page["bars"][name]] for name in pages[0]["bars"]
    }


def test_a_day_of_five_minute_es_bars_comes_as_load_gives_them_column_by_column(
    client: TestClient, container: Container
) -> None:
    store_with("trades", "ohlcv-1s", "ohlcv-1m")
    logged_in(client, container)

    response = client.get(BARS, params=ONE_DAY_OF_ES)

    page = response.json()
    numbers = [page["bars"][name] for name in ("time", "open", "high", "low", "close", "volume")]
    assert response.status_code == 200
    assert {name: page[name] for name in ("instrument", "timeframe", "provider", "next_from")} == {
        "instrument": "ES",
        "timeframe": "5m",
        "provider": "synthetic",
        "next_from": None,
    }
    assert page["bars"] == as_sent(ff.market.load("ES", "5m", "2026-03-06", "2026-03-06").collect())
    assert len(page["bars"]["time"]) == 276
    assert all(abs(value) < 2**53 for column in numbers for value in column)


def test_a_day_of_five_minute_es_bars_answers_in_under_300_ms_warm(
    client: TestClient, container: Container
) -> None:
    # Done means 2: the fastest of three requests after one that warms the session table and
    # the roll calendar, which a server keeps between requests.
    store_with("trades", "ohlcv-1s", "ohlcv-1m")
    logged_in(client, container)
    warming = client.get(BARS, params=ONE_DAY_OF_ES)
    took: list[float] = []
    answers = []
    for _ in range(3):
        began = time.perf_counter()
        answers.append(client.get(BARS, params=ONE_DAY_OF_ES))
        took.append(time.perf_counter() - began)

    print(f"a day of 5-minute ES bars answered in {', '.join(f'{each:.3f}' for each in took)} s")
    assert [each.status_code for each in (warming, *answers)] == [200] * 4
    assert {len(each.json()["bars"]["time"]) for each in answers} == {276}
    assert min(took) < 0.3


@pytest.mark.parametrize(
    ("asked", "sizes"),
    [
        pytest.param(
            {"instrument": "ES", "timeframe": "5s", "from": "2026-03-06", "to": "2026-03-09"},
            [20_000, 13_119],
            id="ES-5s",
        ),
        pytest.param(
            {
                "instrument": "BTCUSDT-PERP",
                "timeframe": "1s",
                "from": "2026-03-07",
                "to": "2026-03-07",
            },
            [20_000, 20_000, 20_000, 20_000, 6_398],
            id="bitcoin-1s",
        ),
    ],
)
def test_a_window_pages_to_its_end_and_its_pages_join_to_one_load(
    client: TestClient, container: Container, asked: dict[str, str], sizes: list[int]
) -> None:
    store_with("trades", "ohlcv-1s", "ohlcv-1m")
    logged_in(client, container)

    pages = pages_of(client, asked)

    whole = ff.market.load(asked["instrument"], asked["timeframe"], asked["from"], asked["to"])
    assert [len(page["bars"]["time"]) for page in pages] == sizes
    assert joined(pages) == as_sent(whole.collect())
    assert [page["next_from"] is None for page in pages] == [False] * (len(sizes) - 1) + [True]


def test_a_window_wider_than_the_data_is_cut_to_it_and_one_without_data_is_empty(
    client: TestClient, container: Container
) -> None:
    store_with("ohlcv-1m")
    logged_in(client, container)

    wider = pages_of(
        client, {"instrument": "ES", "timeframe": "5m", "from": "2009-06-01", "to": "2031-06-30"}
    )
    outside = client.get(
        BARS,
        params={"instrument": "ES", "timeframe": "5m", "from": "2019-01-02", "to": "2019-12-31"},
    )

    whole = ff.market.load("ES", "5m", "2026-03-05", "2026-03-09").collect()
    assert len(wider) == 1
    assert wider[0]["bars"] == as_sent(whole)
    assert outside.status_code == 200
    assert outside.json()["bars"] == {name: [] for name in as_sent(whole)}
    assert outside.json()["next_from"] is None


def test_a_page_from_an_instant_in_the_break_after_a_close_starts_at_the_next_open(
    client: TestClient, container: Container
) -> None:
    # 2026-03-06 closes at 22:00 UTC, and 03-09's session opens at 22:00 UTC on 03-08.
    store_with("ohlcv-1m")
    logged_in(client, container)

    page = client.get(
        BARS,
        params={
            "instrument": "ES",
            "timeframe": "5m",
            "from": "2026-03-06T22:30:00Z",
            "to": "2026-03-09",
        },
    ).json()

    assert page["bars"] == as_sent(ff.market.load("ES", "5m", "2026-03-09", "2026-03-09").collect())


def test_each_contract_comes_beside_the_others_at_an_open_without_splicing(
    client: TestClient, container: Container
) -> None:
    store_with("ohlcv-1m")
    logged_in(client, container)
    asked = {"instrument": "ES", "timeframe": "1m", "from": "2026-03-05", "to": "2026-03-09"}

    page = client.get(BARS, params={**asked, "continuous": "false"}).json()

    whole = ff.market.load("ES", "1m", "2026-03-05", "2026-03-09", continuous=False).collect()
    assert page["bars"] == as_sent(whole)
    assert sorted(set(page["bars"]["contract"])) == ["ESH2026", "ESM2026"]


@pytest.mark.parametrize(
    ("asked", "status", "detail"),
    [
        ({"instrument": "ZZ"}, 404, "or a contract such as MESH2024, got 'ZZ'"),
        ({"instrument": "ZZH2026"}, 404, "or a contract such as MESH2024, got 'ZZH2026'"),
        ({"provider": "vendor"}, 400, "Expected a provider of ES in the store (synthetic)"),
        ({"timeframe": "1s"}, 400, "Expected a timeframe of 1m or coarser"),
        ({"from": "2026-03-09", "to": "2026-03-06"}, 400, "Expected the start 2026-03-09 on"),
        ({"from": "2026-02-30"}, 400, "day is out of range for month"),
    ],
)
def test_a_window_the_sdk_refuses_is_a_problem_in_its_words(
    client: TestClient, container: Container, asked: dict[str, str], status: int, detail: str
) -> None:
    store_with("ohlcv-1m")
    logged_in(client, container)

    refused = client.get(BARS, params={**ONE_DAY_OF_ES, **asked})

    assert (refused.status_code, refused.headers["content-type"]) == (status, PROBLEM)
    assert detail in refused.json()["detail"]


@pytest.mark.parametrize(
    "asked",
    [
        {"from": "2026-3-6"},
        {"from": "2026-03-06T03:20:00"},
        {"timeframe": "5x"},
        {"origin": "sync"},
    ],
)
def test_a_window_the_schema_refuses_is_a_validation_problem(
    client: TestClient, container: Container, asked: dict[str, str]
) -> None:
    logged_in(client, container)

    refused = client.get(BARS, params={**ONE_DAY_OF_ES, **asked})

    assert (refused.status_code, refused.headers["content-type"]) == (422, PROBLEM)


def test_the_bars_need_a_login(client: TestClient) -> None:
    assert client.get(BARS, params=ONE_DAY_OF_ES).status_code == 401
