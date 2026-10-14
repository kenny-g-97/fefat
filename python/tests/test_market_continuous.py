"""The roll calendar and forward-anchored continuous bars (step 1.7, ADR-0007): the fixtures'
volume crossover, prefix invariance (D-12), within-contract differences, the forced, open
interest, and calendar rules, the gap recorded for a position's transfer, and the display view."""

from collections.abc import Iterable
from datetime import date
from pathlib import Path

import polars as pl
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from polars.testing import assert_frame_equal

from fefat.market import instruments
from fefat.market.builtin_calendars import BUILT_IN
from fefat.market.calendar import SessionTable, sessions_of
from fefat.market.calendar_definition import CalendarId
from fefat.market.continuous import (
    CONTINUOUS_COLUMNS,
    CONTRACT_BAR_COLUMNS,
    STATISTICS_CONTRACT_COLUMNS,
    FrontContract,
    RollCalendar,
    RollReason,
    back_adjusted,
    calendar_rolls,
    open_interest_rolls,
    volume_rolls,
)
from fefat.market.layout import Dataset, PartitionRequest
from fefat.market.schema import parse_schema_name
from fefat.market.store import Store

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Store(ROOT / "fixtures")
ES = instruments.get("ES")
MARCH_5, MARCH_6, MARCH_9, MARCH_10 = (date(2026, 3, day) for day in (5, 6, 9, 10))
TICK = 250_000_000
INSTRUMENT_IDS = {"ESH2026": 1001, "ESM2026": 1003, "ESU2026": 1004, "ESZ2026": 1005}
PRICES = ("open", "high", "low", "close")


@pytest.fixture(scope="module")
def table(tmp_path_factory: pytest.TempPathFactory) -> SessionTable:
    return sessions_of(BUILT_IN[CalendarId.CME_EQUITY_INDEX], tmp_path_factory.mktemp("cache"))


def fixture_bars(schema: str) -> pl.DataFrame:
    """Both ES contracts' bars of `schema` on the fixtures' three trade dates."""
    dataset = Dataset(provider="synthetic", schema_name=parse_schema_name(schema), root="ES")
    request = PartitionRequest(dataset=dataset, start=MARCH_5, end=MARCH_9)
    return FIXTURES.scan_contracts(request).collect().sort("contract", "ts_open")


def last_close(bars: pl.DataFrame, contract: str, through: date) -> int:
    """`contract`'s last close by `ts_open` among its bars of trade dates up to `through`."""
    rows = bars.filter(pl.col("contract") == contract, pl.col("trade_date") <= through)
    return rows.sort("ts_open").item(-1, "close")


def the_end(table: SessionTable) -> int:
    """When every print of the fixtures is in hand: the open after their last trade date."""
    return table.following(MARCH_9).open


def test_the_fixtures_crossover_rolls_at_the_next_open_and_never_back(table: SessionTable) -> None:
    # ESM2026 out-trades ESH2026 on 03-06 only: the roll takes effect at the open of 03-09, and
    # the decision for 03-10, made from 03-09, when March leads again, keeps June.
    bars = fixture_bars("ohlcv-1m")

    calendar = volume_rolls(bars, table, ES, the_end(table))

    gap = last_close(bars, "ESM2026", MARCH_6) - last_close(bars, "ESH2026", MARCH_6)
    assert calendar.rows.rows() == [
        (MARCH_6, table.session(MARCH_6).open, "ESH2026", 0, None, None, None),
        (MARCH_9, table.session(MARCH_9).open, "ESM2026", -gap, "ESH2026", gap, "volume"),
        (MARCH_10, table.session(MARCH_10).open, "ESM2026", -gap, None, None, None),
    ]
    assert calendar.rolls().rows() == [
        (MARCH_9, table.session(MARCH_9).open, "ESH2026", "ESM2026", gap, RollReason.VOLUME)
    ]


@pytest.mark.parametrize("schema", ["ohlcv-1s", "ohlcv-1m"])
def test_removing_the_data_after_a_trade_date_changes_nothing_before_it(
    table: SessionTable, schema: str
) -> None:
    bars = fixture_bars(schema)
    calendar = volume_rolls(bars, table, ES, the_end(table))
    whole = calendar.continuous_bars(bars)

    for cut in (MARCH_5, MARCH_6, MARCH_9):
        in_hand = bars.filter(pl.col("trade_date") <= cut)
        next_open = table.following(cut)
        cut_calendar = volume_rolls(in_hand, table, ES, next_open.open)

        expected_rows = calendar.rows.filter(pl.col("trade_date") <= next_open.trade_date)
        assert_frame_equal(cut_calendar.rows, expected_rows)
        assert_frame_equal(
            cut_calendar.continuous_bars(in_hand), whole.filter(pl.col("trade_date") <= cut)
        )


def instants(table: SessionTable) -> list[int]:
    """Instants to cut the fixtures at: opens and closes and either side of them, inside a
    session, the print after the close of 03-06 and its bars' ends, the weekend, the end."""
    march_5, march_6, march_9 = (table.session(day) for day in (MARCH_5, MARCH_6, MARCH_9))
    minute = 60_000_000_000
    after_the_close = march_6.close + 400_000_000
    return [
        march_5.open + minute,
        march_5.close - 1,
        march_5.close,
        march_6.open - 1,
        march_6.open,
        march_6.open + 1,
        march_6.open + 7 * 60 * minute + 123_456_789,
        march_6.close,
        after_the_close,
        march_6.close + minute,
        march_9.open - 1,
        march_9.open,
        march_9.open + minute,
        march_9.close - 1,
        march_9.close + minute,
        the_end(table),
    ]


@pytest.mark.parametrize("schema", ["ohlcv-1s", "ohlcv-1m"])
def test_rows_and_bars_by_an_instant_stay_the_same_when_the_data_stops_there(
    table: SessionTable, schema: str
) -> None:
    bars = fixture_bars(schema)
    calendar = volume_rolls(bars, table, ES, the_end(table))
    whole = calendar.continuous_bars(bars)

    for cut in instants(table):
        in_hand = bars.filter(pl.col("ts_close") <= cut)
        cut_calendar = volume_rolls(in_hand, table, ES, cut)

        assert_frame_equal(cut_calendar.rows, calendar.rows.filter(pl.col("session_open") <= cut))
        assert_frame_equal(
            cut_calendar.continuous_bars(in_hand), whole.filter(pl.col("ts_close") <= cut)
        )


def with_raw_prices(continuous: pl.DataFrame, bars: pl.DataFrame) -> pl.DataFrame:
    """The continuous bars beside their contract's raw prices, named `<price>_raw`."""
    raw = bars.select(
        "contract", "ts_open", *(pl.col(price).alias(f"{price}_raw") for price in PRICES)
    )
    return continuous.drop("close_raw").join(raw, on=["contract", "ts_open"]).sort("ts_open")


def test_adjusted_differences_equal_raw_differences_within_a_contract(
    table: SessionTable,
) -> None:
    bars = fixture_bars("ohlcv-1m")
    continuous = volume_rolls(bars, table, ES, the_end(table)).continuous_bars(bars)
    spliced = with_raw_prices(continuous, bars)

    assert spliced.get_column("contract").unique().sort().to_list() == ["ESH2026", "ESM2026"]
    for price in PRICES:
        adjusted_step = pl.col(price).diff().over("contract")
        raw_step = pl.col(f"{price}_raw").diff().over("contract")
        assert spliced.filter(adjusted_step != raw_step).is_empty(), price
    assert_frame_equal(continuous.select("close_raw"), spliced.select(close_raw="close_raw"))


def test_across_the_roll_the_series_moves_by_the_new_contracts_own_step(
    table: SessionTable,
) -> None:
    # The gap is gone: from March's last bar of 03-06 to June's first of 03-09 the adjusted
    # close moves by June's own change from its last close of 03-06.
    bars = fixture_bars("ohlcv-1m")
    continuous = volume_rolls(bars, table, ES, the_end(table)).continuous_bars(bars)

    flagged = continuous.with_row_index().filter(pl.col("roll_flag"))
    (row,) = flagged.get_column("index").to_list()
    before, first = continuous.row(row - 1, named=True), continuous.row(row, named=True)

    assert (before["contract"], first["contract"]) == ("ESH2026", "ESM2026")
    assert first["trade_date"] == MARCH_9
    assert first["close"] - before["close"] == first["close_raw"] - last_close(
        bars, "ESM2026", MARCH_6
    )
    assert before["close"] == before["close_raw"] == last_close(bars, "ESH2026", MARCH_6)


def test_a_position_across_the_roll_has_its_transfer_and_gap_recorded(table: SessionTable) -> None:
    # A long ESH2026 position still open at the open of 03-09 is transferred there (step 2.9):
    # the roll names both contracts and the gap, and a stop held as an adjusted level moves by
    # the gap in raw prices when it passes to ESM2026.
    bars = fixture_bars("ohlcv-1m")
    calendar = volume_rolls(bars, table, ES, the_end(table))
    roll_open = table.session(MARCH_9).open
    ((trade_date, at, rolled_from, contract, gap, reason),) = calendar.rolls().rows()
    stop = 6_800 * 1_000_000_000

    assert (trade_date, at, rolled_from, contract, reason) == (
        MARCH_9,
        roll_open,
        "ESH2026",
        "ESM2026",
        "volume",
    )
    assert calendar.front(roll_open - 1) == FrontContract(
        trade_date=MARCH_6, contract="ESH2026", adj_offset=0
    )
    assert calendar.front(roll_open) == FrontContract(
        trade_date=MARCH_9, contract="ESM2026", adj_offset=-gap
    )
    assert (
        calendar.to_raw_price(stop, roll_open) - calendar.to_raw_price(stop, roll_open - 1) == gap
    )


def test_an_adjusted_level_converts_to_its_bars_raw_price(table: SessionTable) -> None:
    bars = fixture_bars("ohlcv-1m")
    calendar = volume_rolls(bars, table, ES, the_end(table))
    continuous = calendar.continuous_bars(bars)

    for close, ts_open, close_raw in continuous.select("close", "ts_open", "close_raw").rows():
        assert calendar.to_raw_price(close, ts_open) == close_raw


def test_an_instant_outside_the_calendar_is_refused(table: SessionTable) -> None:
    calendar = volume_rolls(fixture_bars("ohlcv-1m"), table, ES, the_end(table))
    first_open = table.session(MARCH_6).open

    with pytest.raises(ValueError, match="Expected an instant from 2026-03-05T23:00:00Z"):
        calendar.front(first_open - 1)
    with pytest.raises(ValueError, match="Expected an instant by 2026-03-09T22:00:00Z"):
        calendar.to_raw_price(1, the_end(table) + 1)


def session_bars(rows: Iterable[tuple[date, str, int, int]], table: SessionTable) -> pl.DataFrame:
    """A bar spanning each session for each (trade date, contract, close in ticks, volume)."""
    bars = []
    for trade_date, contract, ticks, volume in rows:
        session, price = table.session(trade_date), ticks * TICK
        prices = (price, price, price, price)
        identity = (session.open, session.close, trade_date, INSTRUMENT_IDS[contract])
        bars.append((*identity, *prices, volume, 1, price, contract))
    return pl.DataFrame(bars, schema=CONTRACT_BAR_COLUMNS, orient="row")


def trade_dates(table: SessionTable, first: date, last: date) -> list[date]:
    return table.between(first, last).get_column("trade_date").to_list()


def test_a_front_that_reaches_its_last_trade_date_is_rolled_at_that_open(
    table: SessionTable,
) -> None:
    # ESH2026 out-trades ESM2026 to the end, but its last trade date, Friday 2026-03-20, is a
    # session it cannot serve: the roll is forced at that session's open.
    days = trade_dates(table, date(2026, 3, 16), date(2026, 3, 20))
    bars = session_bars(
        [(day, "ESH2026", 27_000, 100) for day in days]
        + [(day, "ESM2026", 27_100, 10) for day in days],
        table,
    )

    calendar = volume_rolls(bars, table, ES, table.following(days[-1]).open)

    assert calendar.rows.select("trade_date", "contract", "reason").rows() == [
        (date(2026, 3, 17), "ESH2026", None),
        (date(2026, 3, 18), "ESH2026", None),
        (date(2026, 3, 19), "ESH2026", None),
        (date(2026, 3, 20), "ESM2026", "expiry"),
        (date(2026, 3, 23), "ESM2026", None),
    ]


def test_the_calendar_ends_where_no_contract_may_serve_the_session(table: SessionTable) -> None:
    days = trade_dates(table, date(2026, 3, 16), date(2026, 3, 20))
    bars = session_bars([(day, "ESH2026", 27_000, 100) for day in days], table)

    calendar = volume_rolls(bars, table, ES, table.following(days[-1]).open)

    assert calendar.rows.get_column("trade_date").to_list() == days[1:-1]
    assert calendar.continuous_bars(bars).get_column("trade_date").to_list() == days[1:-1]


def open_interest(rows: Iterable[tuple[int, str, int]]) -> pl.DataFrame:
    """Open-interest statistics (stat_type 9), each (ts_recv, contract, open interest)."""
    return pl.DataFrame(
        [
            (
                ts_recv,
                ts_recv,
                ts_recv,
                INSTRUMENT_IDS[contract],
                9,
                None,
                quantity,
                1,
                0,
                1,
                contract,
            )
            for ts_recv, contract, quantity in rows
        ],
        schema=STATISTICS_CONTRACT_COLUMNS,
        orient="row",
    )


def test_open_interest_rolls_by_the_latest_figure_received_by_each_open(
    table: SessionTable,
) -> None:
    # June's open interest passes March's in a figure received an hour after the open of
    # 03-11 and in one received exactly at the open of 03-12: the roll takes effect at 03-12,
    # though June out-trades March throughout.
    days = trade_dates(table, date(2026, 3, 9), date(2026, 3, 13))
    bars = session_bars(
        [(day, "ESH2026", 27_000, 10) for day in days]
        + [(day, "ESM2026", 27_100, 100) for day in days],
        table,
    )
    hour = 3_600_000_000_000
    march_11, march_12 = table.session(date(2026, 3, 11)), table.session(date(2026, 3, 12))
    statistics = open_interest(
        [
            (table.session(days[0]).open, "ESH2026", 2_000),
            (table.session(days[0]).open, "ESM2026", 1_000),
            (march_11.open + hour, "ESM2026", 2_500),
            (march_12.open, "ESH2026", 2_400),
        ]
    )

    calendar = open_interest_rolls(bars, statistics, table, ES, table.following(days[-1]).open)

    assert calendar.rows.select("trade_date", "contract", "reason").rows() == [
        (date(2026, 3, 10), "ESH2026", None),
        (date(2026, 3, 11), "ESH2026", None),
        (date(2026, 3, 12), "ESM2026", "open-interest"),
        (date(2026, 3, 13), "ESM2026", None),
        (date(2026, 3, 16), "ESM2026", None),
    ]


def test_the_calendar_rule_rolls_a_set_number_of_sessions_before_the_last_trade_date(
    table: SessionTable,
) -> None:
    days = trade_dates(table, date(2026, 3, 13), date(2026, 3, 19))
    bars = session_bars(
        [(day, "ESH2026", 27_000, 100) for day in days]
        + [(day, "ESM2026", 27_100, 10) for day in days],
        table,
    )

    calendar = calendar_rolls(bars, table, ES, table.following(days[-1]).open, 2)

    assert calendar.rows.select("trade_date", "contract", "reason").rows() == [
        (date(2026, 3, 16), "ESH2026", None),
        (date(2026, 3, 17), "ESH2026", None),
        (date(2026, 3, 18), "ESM2026", "calendar"),
        (date(2026, 3, 19), "ESM2026", None),
        (date(2026, 3, 20), "ESM2026", None),
    ]


def test_the_back_adjusted_view_shows_the_newest_contract_raw(table: SessionTable) -> None:
    bars = fixture_bars("ohlcv-1m")
    continuous = volume_rolls(bars, table, ES, the_end(table)).continuous_bars(bars)
    gap = last_close(bars, "ESM2026", MARCH_6) - last_close(bars, "ESH2026", MARCH_6)

    display = back_adjusted(continuous)

    by_contract = display.group_by("contract").agg(
        shift=(pl.col("close") - pl.col("close_raw")).unique()
    )
    assert sorted(by_contract.rows()) == [("ESH2026", [gap]), ("ESM2026", [0])]
    assert display.filter(pl.col("close") != pl.col("close_raw") + pl.col("adj_offset")).is_empty()
    assert display.schema == CONTINUOUS_COLUMNS


def test_bars_of_another_root_or_without_their_contract_are_refused(table: SessionTable) -> None:
    bars = fixture_bars("ohlcv-1m")

    with pytest.raises(ValueError, match="Expected contracts of MES, got ESH2026"):
        volume_rolls(bars, table, instruments.get("MES"), the_end(table))
    with pytest.raises(ValueError, match="Expected the columns"):
        volume_rolls(bars.drop("contract"), table, ES, the_end(table))
    with pytest.raises(ValueError, match="Expected bars of at least one contract of ES"):
        volume_rolls(bars.clear(), table, ES, the_end(table))


SESSIONS_OF_THE_PROPERTY = (date(2026, 2, 23), date(2026, 4, 10))
SESSION_COUNT_OF_THE_PROPERTY = 35
CONTRACTS_OF_THE_PROPERTY = ("ESH2026", "ESM2026", "ESU2026")


@st.composite
def random_bars(draw: st.DrawFn) -> list[tuple[int, str, int, int]]:
    """For each of the 35 sessions and each contract, a close in ticks and a volume, 0 for no bar:
    the leader moves from March to June to September, a session early or late at random, so the
    rolls fall anywhere and the leader flips back now and then."""
    rows = []
    for index in range(SESSION_COUNT_OF_THE_PROPERTY):
        leader = min(2, max(0, index // 12 + draw(st.integers(-1, 1))))
        for order, contract in enumerate(CONTRACTS_OF_THE_PROPERTY):
            volume = draw(st.integers(60, 100)) if order == leader else draw(st.integers(0, 59))
            rows.append((index, contract, draw(st.integers(26_000, 28_000)), volume))
    return rows


@settings(max_examples=40, deadline=None)
@given(drawn=random_bars(), cut=st.integers(0, SESSION_COUNT_OF_THE_PROPERTY - 1))
def test_any_volumes_give_a_calendar_that_never_rolls_back_or_changes_its_past(
    table: SessionTable, drawn: list[tuple[int, str, int, int]], cut: int
) -> None:
    days = trade_dates(table, *SESSIONS_OF_THE_PROPERTY)
    assert len(days) == SESSION_COUNT_OF_THE_PROPERTY
    rows = [(days[index], contract, ticks, volume) for index, contract, ticks, volume in drawn]
    bars = session_bars([row for row in rows if row[3] > 0], table)
    if bars.is_empty():
        return
    calendar = volume_rolls(bars, table, ES, table.following(days[-1]).open)
    fronts = calendar.rows

    contract_order = {contract: order for order, contract in enumerate(CONTRACTS_OF_THE_PROPERTY)}
    assert fronts.get_column("contract").replace_strict(contract_order).is_sorted()
    assert fronts.filter(
        pl.col("contract") == "ESH2026", pl.col("trade_date") >= date(2026, 3, 20)
    ).is_empty()
    offset_step = pl.col("adj_offset").diff().fill_null(pl.col("adj_offset"))
    expected_step = -pl.col("gap").fill_null(0)
    assert fronts.filter(offset_step != expected_step).is_empty()

    in_hand = bars.filter(pl.col("trade_date") <= days[cut])
    if not in_hand.is_empty():
        following = table.following(days[cut])
        cut_calendar = volume_rolls(in_hand, table, ES, following.open)
        expected_rows = fronts.filter(pl.col("trade_date") <= following.trade_date)
        assert_frame_equal(cut_calendar.rows, expected_rows)
    spliced = with_raw_prices(calendar.continuous_bars(bars), bars)
    for price in PRICES:
        raw_step = pl.col(f"{price}_raw").diff().over("contract")
        assert spliced.filter(pl.col(price).diff().over("contract") != raw_step).is_empty()


def test_a_calendar_takes_the_columns_of_its_rows(table: SessionTable) -> None:
    calendar = volume_rolls(fixture_bars("ohlcv-1m"), table, ES, the_end(table))

    with pytest.raises(ValueError, match="Expected the columns"):
        RollCalendar("ES", calendar.rows.drop("gap"), the_end(table))
    assert repr(calendar) == "RollCalendar('ES', 3 sessions, 2026-03-06 to 2026-03-10, 1 roll)"
