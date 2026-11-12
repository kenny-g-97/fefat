"""`GET /v1/market/bars` of step 5.1 (D-93, `01-architecture.md` section 7): `load`'s bars of a
window, a page of at most 20,000 at a time, column by column, with no number past 2^53, and the
instant the next page opens at. Done means 2: a day of 5-minute ES bars in under 300 ms warm, on
the synthetic fixtures."""

import os
import time
from typing import Any

import polars as pl
import pytest
from fastapi.testclient import TestClient

import fefat as ff
from fefat.config import resolve_paths
from fefat.market.layout import Dataset, SeriesKind
from fefat.market.schema import parse_schema_name
from fefat.market.store import Store
from fefat_app.container import Container
from fefat_app.services import market_bars
from generated_minutes import SPRING, write_minutes
from local_server import logged_in
from notebook_runs import store_with

PROBLEM = "application/problem+json"
BARS = "/v1/market/bars"
SPAN = "/v1/market/bars/span"
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
    named = client.get(BARS, params={**ONE_DAY_OF_ES, "provider": "synthetic", "origin": "import"})

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
    assert (named.status_code, named.json()) == (200, page)


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


def test_a_page_that_ends_at_a_close_under_its_cap_hands_over_to_the_next_open(
    client: TestClient, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Step 5.1's review: with a cap of 1,000, a session of 1,380 one-minute bars takes two
    # pages, the second of 380 ending at its close, whose `next_from` is the next session's open.
    monkeypatch.setattr(market_bars, "BARS_PER_PAGE", 1_000)
    store_with("ohlcv-1m")
    logged_in(client, container)
    asked = {"instrument": "ES", "timeframe": "1m", "from": "2026-03-05", "to": "2026-03-09"}

    pages = pages_of(client, asked)

    whole = ff.market.load("ES", "1m", "2026-03-05", "2026-03-09").collect()
    assert [len(page["bars"]["time"]) for page in pages] == [0, 1_000, 380, 1_000, 380]
    assert [page["next_from"] for page in pages] == [
        "2026-03-05T23:00:00Z",
        "2026-03-06T15:40:00Z",
        "2026-03-08T22:00:00Z",
        "2026-03-09T14:40:00Z",
        None,
    ]
    assert joined(pages) == as_sent(whole)


def test_a_page_reads_a_capped_number_of_sessions_of_prints_and_hands_over_at_a_close(
    client: TestClient, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Step 5.4 (from `BACKLOG.md`): a page counted the bars it sends, not the data it reads, so a
    # page of coarse bars built from trades read every print of its window. With one session of
    # prints a page, ES's three sessions come one a page, the first spliced one empty.
    monkeypatch.setattr(market_bars, "FINE_SESSIONS_PER_PAGE", 1)
    store_with("trades", "ohlcv-1m")
    logged_in(client, container)
    asked = {"instrument": "ES", "timeframe": "5m", "from": "2026-03-05", "to": "2026-03-09"}

    pages = pages_of(client, asked)

    whole = ff.market.load("ES", "5m", "2026-03-05", "2026-03-09").collect()
    assert [len(page["bars"]["time"]) for page in pages] == [0, 276, 275]
    assert [page["next_from"] for page in pages] == [
        "2026-03-05T23:00:00Z",
        "2026-03-08T22:00:00Z",
        None,
    ]
    assert joined(pages) == as_sent(whole)


def test_minutes_kept_by_month_count_no_session_of_prints(
    client: TestClient, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Step 5.4: a month's minutes are read by the month, so they count against the sessions of
    # any data alone, and four months of daily bars come in one page.
    monkeypatch.setattr(market_bars, "FINE_SESSIONS_PER_PAGE", 1)
    write_minutes(SPRING)
    logged_in(client, container)
    asked = {"instrument": "ES", "timeframe": "1d", "from": "2026-01-02", "to": "2026-04-30"}

    pages = pages_of(client, asked)

    assert len(pages) == 1
    assert len(pages[0]["bars"]["time"]) > 60


def test_a_page_reads_a_capped_number_of_sessions_of_any_data(
    client: TestClient, container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Step 5.4: a page of daily bars from minutes read every session of its window, 1,861 of
    # them and 1.7 GB on the builder's MES; with one session a page, each comes alone.
    monkeypatch.setattr(market_bars, "SESSIONS_PER_PAGE", 1)
    store_with("ohlcv-1m")
    logged_in(client, container)
    asked = {"instrument": "ES", "timeframe": "1d", "from": "2026-03-05", "to": "2026-03-09"}

    pages = pages_of(client, asked)

    whole = ff.market.load("ES", "1d", "2026-03-05", "2026-03-09").collect()
    assert len(pages) == 3
    assert joined(pages) == as_sent(whole)


def test_a_contracts_window_starts_at_its_first_trade_date(
    client: TestClient, container: Container
) -> None:
    # Step 5.1's review: ESM2026 trades from 2026-02-23 in a dataset ESH2026 holds from 01-02, so
    # a window cut to the dataset's dates paged through seven weeks of empty pages first.
    write_minutes(SPRING)
    logged_in(client, container)
    asked = {"instrument": "ESM2026", "timeframe": "1m", "from": "2026-01-02", "to": "2026-03-31"}

    pages = pages_of(client, asked)

    whole = ff.market.load("ESM2026", "1m", "2026-01-02", "2026-03-31").collect()
    assert all(page["bars"]["time"] for page in pages)
    assert pages[0]["bars"]["trade_date"][0] == "2026-02-23"
    assert set(joined(pages)["contract"]) == {"ESM2026"}
    assert joined(pages) == as_sent(whole)


def test_a_contracts_window_ends_at_its_last_trade_date_which_its_span_names(
    client: TestClient, container: Container
) -> None:
    # Found at step 5.4's plan: ESH2026 stops on 2026-03-20 in a dataset ESM2026 holds to 04-30,
    # so its later pages came empty and joined to no load; a contract's window is cut to its own
    # last trade date as to its first, and the span the chart asks first says where both are.
    write_minutes(SPRING)
    logged_in(client, container)
    asked = {"instrument": "ESH2026", "timeframe": "1m", "from": "2026-01-02", "to": "2026-04-30"}

    pages = pages_of(client, asked)
    span = client.get(SPAN, params={"instrument": "ESH2026", "timeframe": "1m"})

    whole = ff.market.load("ESH2026", "1m", "2026-01-02", "2026-03-20").collect()
    assert all(page["bars"]["time"] for page in pages)
    assert joined(pages) == as_sent(whole)
    assert (span.status_code, span.json()) == (
        200,
        {
            "instrument": "ESH2026",
            "timeframe": "1m",
            "provider": "synthetic",
            "held": {"first": "2026-01-02", "last": "2026-03-20"},
        },
    )


def test_a_roots_span_is_its_datasets_and_none_is_held_of_one_it_lacks(
    client: TestClient, container: Container
) -> None:
    # Step 5.4: the chart walks back from the span's last trade date to its first; the fixtures'
    # spliced ES has its 1-minute bars from 2026-03-05 to 03-09.
    store_with("ohlcv-1m")
    logged_in(client, container)

    es = client.get(SPAN, params={"instrument": "ES", "timeframe": "5m"}).json()
    seconds = client.get(SPAN, params={"instrument": "ES", "timeframe": "1s"})
    unknown = client.get(SPAN, params={"instrument": "ZZ", "timeframe": "5m"})

    assert es["held"] == {"first": "2026-03-05", "last": "2026-03-09"}
    assert (seconds.status_code, unknown.status_code) == (400, 404)
    assert "Expected a timeframe of 1m or coarser" in seconds.json()["detail"]


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


def continuous_bitcoin(series: SeriesKind = SeriesKind.CONTINUOUS) -> None:
    """The fixtures' bitcoin bars in the data folder described as a continuous series, which
    every load warns of, or as `series`."""
    store = Store(resolve_paths(os.environ).data_dir)
    bitcoin = Dataset(
        provider="synthetic", schema_name=parse_schema_name("ohlcv-1m"), root="BTCUSDT-PERP"
    )
    continuous = store.dataset_metadata(bitcoin).model_copy(update={"series": series})
    store.write_dataset_metadata(bitcoin, continuous)


def test_raw_prices_are_the_prices_each_bars_contract_traded_at_across_a_roll(
    client: TestClient, container: Container
) -> None:
    # Step 5.4, the builder's answer: Raw is the spliced series at the prices each session's
    # front contract traded at, so the roll of 2026-03-09 shows its gap, where the adjusted
    # prices, which every feature reads, add the offset.
    store_with("ohlcv-1m")
    logged_in(client, container)
    asked = {"instrument": "ES", "timeframe": "5m", "from": "2026-03-06", "to": "2026-03-09"}

    raw = client.get(BARS, params={**asked, "prices": "raw"}).json()
    adjusted = client.get(BARS, params={**asked, "prices": "adjusted"}).json()

    whole = ff.market.load("ES", "5m", "2026-03-06", "2026-03-09").collect()
    traded = whole.with_columns(pl.col("open", "high", "low", "close") - pl.col("adj_offset"))
    assert raw["bars"] == as_sent(traded)
    assert raw["bars"]["close"] == [
        close / PRICE_SCALE for close in whole.sort("ts_open")["close_raw"].to_list()
    ]
    assert adjusted == client.get(BARS, params=asked).json()
    assert raw["bars"]["close"][-1] != adjusted["bars"]["close"][-1]


def test_raw_prices_of_a_back_adjusted_series_are_refused(
    client: TestClient, container: Container
) -> None:
    # A back-adjusted import's prices hold the gaps of later rolls and keep no raw ones (D-49).
    store_with("ohlcv-1m")
    continuous_bitcoin(SeriesKind.CONTINUOUS_BACK_ADJUSTED)
    logged_in(client, container)
    asked = {"instrument": "BTCUSDT-PERP", "timeframe": "5m", "from": "2026-03-07"}

    refused = client.get(BARS, params={**asked, "to": "2026-03-07", "prices": "raw"})

    assert (refused.status_code, refused.headers["content-type"]) == (400, PROBLEM)
    assert "Expected adjusted prices of the back-adjusted series" in refused.json()["detail"]


def test_a_page_says_what_load_warns_of_its_bars(client: TestClient, container: Container) -> None:
    # Step 5.4 (from `BACKLOG.md`): the chart says what a notebook's load warns of, which the
    # server only wrote to its console.
    store_with("ohlcv-1m")
    continuous_bitcoin()
    logged_in(client, container)
    saturday = {"timeframe": "5m", "from": "2026-03-07", "to": "2026-03-07"}

    warned = client.get(BARS, params={"instrument": "BTCUSDT-PERP", **saturday}).json()
    plain = client.get(BARS, params=ONE_DAY_OF_ES).json()

    assert warned["warnings"] == [
        "synthetic/ohlcv-1m/root=BTCUSDT-PERP is a continuous series, one synthetic contract "
        "with roll handling off"
    ]
    assert len(warned["bars"]["time"]) == 288
    assert plain["warnings"] == []


@pytest.mark.parametrize(
    ("asked", "status", "detail"),
    [
        ({"instrument": "ZZ"}, 404, "or a contract such as MESH2024, got 'ZZ'"),
        ({"instrument": "ZZH2026"}, 404, "or a contract such as MESH2024, got 'ZZH2026'"),
        ({"provider": "vendor"}, 400, "Expected a provider of ES in the store (synthetic)"),
        ({"timeframe": "1s"}, 400, "Expected a timeframe of 1m or coarser"),
        ({"from": "2026-03-09", "to": "2026-03-06"}, 400, "Expected the start 2026-03-09 on"),
        ({"from": "2026-02-30"}, 400, "day is out of range for month"),
        ({"from": "2300-01-01T00:00:00Z", "to": "2300-01-02"}, 400, "Expected an instant from"),
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
        {"prices": "settled"},
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
