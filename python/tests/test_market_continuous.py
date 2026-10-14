"""The roll calendar and forward-anchored continuous bars (step 1.7, ADR-0007): the fixtures'
volume crossover, prefix invariance (D-12) for every rule, within-contract differences, the
forced, open-interest, and calendar rules, the gap taken where both contracts traded, the span
of each front, the gap recorded for a position's transfer, and the display view."""

import re
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
    BACK_ADJUSTED_COLUMNS,
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
HOUR = 3_600_000_000_000
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


def shared_closes(bars: pl.DataFrame, old: str, new: str, roll_date: date) -> tuple[int, int]:
    """`old`'s and `new`'s closes in the latest bar, by `ts_open`, that both traded in before
    the session of `roll_date`."""
    before = bars.filter(pl.col("trade_date") < roll_date)
    old_closes = before.filter(pl.col("contract") == old).select("ts_open", old_close="close")
    new_closes = before.filter(pl.col("contract") == new).select("ts_open", new_close="close")
    shared = old_closes.join(new_closes, on="ts_open").sort("ts_open")
    return shared.item(-1, "old_close"), shared.item(-1, "new_close")


def fixture_gap(bars: pl.DataFrame) -> int:
    """The gap of the fixtures' roll from ESH2026 to ESM2026 at the open of 03-09."""
    march_close, june_close = shared_closes(bars, "ESH2026", "ESM2026", MARCH_9)
    return june_close - march_close


def the_end(table: SessionTable) -> int:
    """When every print of the fixtures is in hand: the open after their last trade date."""
    return table.following(MARCH_9).open


def test_the_fixtures_crossover_rolls_at_the_next_open_and_never_back(table: SessionTable) -> None:
    # ESM2026 out-trades ESH2026 on 03-06 only: the roll takes effect at the open of 03-09, and
    # the decision for 03-10, made from 03-09, when March leads again, keeps June.
    bars = fixture_bars("ohlcv-1m")

    calendar = volume_rolls(bars, table, ES, the_end(table))

    gap = fixture_gap(bars)
    opens = [table.session(day).open for day in (MARCH_6, MARCH_9, MARCH_10)]
    after = table.following(MARCH_10).open
    assert calendar.rows.rows() == [
        (MARCH_6, opens[0], opens[1], "ESH2026", 0, None, None, None),
        (MARCH_9, opens[1], opens[2], "ESM2026", -gap, "ESH2026", gap, "volume"),
        (MARCH_10, opens[2], after, "ESM2026", -gap, None, None, None),
    ]
    assert calendar.rolls().rows() == [
        (MARCH_9, opens[1], "ESH2026", "ESM2026", gap, RollReason.VOLUME)
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
    columns = (*PRICES, "vwap")
    raw = bars.select(
        "contract", "ts_open", *(pl.col(column).alias(f"{column}_raw") for column in columns)
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
    assert_frame_equal(continuous.select("close_raw"), spliced.select("close_raw"))


def test_every_price_of_a_continuous_bar_is_its_raw_price_plus_the_offset(
    table: SessionTable,
) -> None:
    bars = fixture_bars("ohlcv-1m")
    continuous = volume_rolls(bars, table, ES, the_end(table)).continuous_bars(bars)
    spliced = with_raw_prices(continuous, bars)

    assert spliced.height == continuous.height
    assert not spliced.filter(pl.col("adj_offset") != 0).is_empty()
    for column in (*PRICES, "vwap"):
        offset_added = pl.col(f"{column}_raw") + pl.col("adj_offset")
        assert spliced.filter(pl.col(column) != offset_added).is_empty(), column


def test_across_the_roll_the_closes_of_the_latest_shared_bar_read_the_same(
    table: SessionTable,
) -> None:
    # The gap is gone: in the latest bar both contracts traded in before 03-09, March's close
    # and June's adjusted one are one price, and from there the series moves as June does.
    bars = fixture_bars("ohlcv-1m")
    calendar = volume_rolls(bars, table, ES, the_end(table))
    continuous = calendar.continuous_bars(bars)
    march_close, june_close = shared_closes(bars, "ESH2026", "ESM2026", MARCH_9)
    june_offset = calendar.front(table.session(MARCH_9).open).adj_offset

    flagged = continuous.filter(pl.col("roll_flag"))
    first = flagged.row(0, named=True)

    assert flagged.height == 1
    assert (first["contract"], first["trade_date"]) == ("ESM2026", MARCH_9)
    assert june_close + june_offset == march_close
    assert first["close"] - march_close == first["close_raw"] - june_close


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
    assert gap == fixture_gap(bars)
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
    with pytest.raises(ValueError, match="sessions from 2026-03-19T22:00:00Z that no contract"):
        calendar.front(table.session(days[-1]).open + HOUR)


def test_rows_run_to_received_until_past_the_last_bar(table: SessionTable) -> None:
    # The bars end on Friday 03-13, but every bar to the open of 03-24 is in hand: each session
    # to it has its front, and ESH2026 is forced off at its last trade date, 03-20.
    days = trade_dates(table, date(2026, 3, 9), date(2026, 3, 13))
    bars = session_bars(
        [(day, "ESH2026", 27_000, 100) for day in days]
        + [(day, "ESM2026", 27_100, 10) for day in days],
        table,
    )

    calendar = volume_rolls(bars, table, ES, table.session(date(2026, 3, 24)).open)

    expected_dates = trade_dates(table, date(2026, 3, 10), date(2026, 3, 24))
    assert calendar.rows.get_column("trade_date").to_list() == expected_dates
    assert calendar.front(table.session(date(2026, 3, 20)).open).contract == "ESM2026"
    assert calendar.rolls().select("trade_date", "gap", "reason").rows() == [
        (date(2026, 3, 20), 100 * TICK, "expiry")
    ]


def test_the_gap_is_taken_in_the_latest_bar_both_contracts_traded_in(table: SessionTable) -> None:
    # ESM2026 trades only on 03-16 while ESH2026 rises 100 ticks a session: the forced roll at
    # 03-20 measures the gap on 03-16, not between June's old close and March's latest.
    days = trade_dates(table, date(2026, 3, 16), date(2026, 3, 19))
    march = [(day, "ESH2026", 27_000 + 100 * index, 100) for index, day in enumerate(days)]
    bars = session_bars([*march, (days[0], "ESM2026", 27_050, 10)], table)

    calendar = volume_rolls(bars, table, ES, table.following(days[-1]).open)

    assert calendar.rolls().select("trade_date", "gap", "reason").rows() == [
        (date(2026, 3, 20), 50 * TICK, "expiry")
    ]


def test_a_roll_between_contracts_that_never_traded_together_is_refused(
    table: SessionTable,
) -> None:
    # March trades on 03-16 and 03-17 and June only from 03-18: the roll at the open of 03-19
    # has no bar in which both traded to measure its gap.
    march = [(day, "ESH2026", 27_000, 100) for day in (date(2026, 3, 16), date(2026, 3, 17))]
    june = [(day, "ESM2026", 27_100, 100) for day in (date(2026, 3, 18), date(2026, 3, 19))]
    bars = session_bars(march + june, table)

    expected = (
        "Expected a bar in which both ESH2026 and ESM2026 traded before the session of 2026-03-19"
    )
    with pytest.raises(ValueError, match=expected):
        volume_rolls(bars, table, ES, table.following(date(2026, 3, 19)).open)


def test_the_new_fronts_first_bar_is_flagged_though_it_skips_the_roll_session(
    table: SessionTable,
) -> None:
    days = trade_dates(table, date(2026, 3, 16), date(2026, 3, 19))
    june = [(days[0], "ESM2026", 27_100, 10), (date(2026, 3, 23), "ESM2026", 27_100, 10)]
    bars = session_bars([(day, "ESH2026", 27_000, 100) for day in days] + june, table)

    calendar = volume_rolls(bars, table, ES, table.session(date(2026, 3, 24)).open)

    flagged = calendar.continuous_bars(bars).filter(pl.col("roll_flag"))
    assert flagged.select("trade_date", "contract").rows() == [(date(2026, 3, 23), "ESM2026")]


def test_a_window_of_bars_after_a_roll_flags_no_roll(table: SessionTable) -> None:
    # The bars given start on 03-10, after the roll at the open of 03-09: their first ESM2026
    # bar follows no ESH2026 bar, so nothing in the window marks a roll.
    bars = fixture_bars("ohlcv-1m")
    calendar = volume_rolls(bars, table, ES, the_end(table))
    window = bars.filter(pl.col("ts_open") >= table.session(MARCH_9).open + HOUR)

    assert calendar.continuous_bars(window).filter(pl.col("roll_flag")).is_empty()


def test_a_contract_listed_past_the_session_table_does_not_stop_the_calendar(
    table: SessionTable,
) -> None:
    # A far-dated listing, ESH2032, whose last trade date lies past the session table's last
    # (2030-12-31), trades once on 03-06: it cannot stop serving within the calendar, so it
    # needs no last trade date and is never front.
    bars = fixture_bars("ohlcv-1m")
    session = table.session(MARCH_6)
    price = 28_000 * TICK
    minute_later = session.open + 60_000_000_000
    far = pl.DataFrame(
        [(session.open, minute_later, MARCH_6, 1009, *(price,) * 4, 1, 1, price, "ESH2032")],
        schema=CONTRACT_BAR_COLUMNS,
        orient="row",
    )

    calendar = volume_rolls(pl.concat([bars, far]), table, ES, the_end(table))

    assert calendar.rows.get_column("contract").to_list() == ["ESH2026", "ESM2026", "ESM2026"]


def test_of_two_figures_received_at_one_instant_the_later_in_sequence_counts(
    table: SessionTable,
) -> None:
    # Two open-interest figures of ESM2026 are received at one instant, the later in sequence
    # above March's: it counts, so June leads from the next open.
    days = trade_dates(table, date(2026, 3, 9), date(2026, 3, 11))
    bars = session_bars(
        [(day, "ESH2026", 27_000, 10) for day in days]
        + [(day, "ESM2026", 27_100, 10) for day in days],
        table,
    )
    at = table.session(days[0]).open + HOUR
    statistics = open_interest(
        [(at, "ESM2026", 3_000), (at, "ESM2026", 500), (at, "ESH2026", 2_000)]
    ).with_columns(sequence=pl.Series([2, 1, 3], dtype=pl.UInt32))

    calendar = open_interest_rolls(bars, statistics, table, ES, table.following(days[-1]).open)

    assert calendar.rows.select("trade_date", "contract").rows() == [
        (date(2026, 3, 10), "ESM2026"),
        (date(2026, 3, 11), "ESM2026"),
        (date(2026, 3, 12), "ESM2026"),
    ]


def test_a_bar_without_trades_does_not_measure_the_gap(table: SessionTable) -> None:
    # June trades on 03-16 only, and the dense grid's rows of no volume carry its close on to
    # 03-19: the forced roll at 03-20 still measures the gap on 03-16, where both traded.
    days = trade_dates(table, date(2026, 3, 16), date(2026, 3, 19))
    march = [(day, "ESH2026", 27_000 + 100 * index, 100) for index, day in enumerate(days)]
    june = [(days[0], "ESM2026", 27_050, 10)] + [(day, "ESM2026", 27_050, 0) for day in days[1:]]

    calendar = volume_rolls(
        session_bars(march + june, table), table, ES, table.following(days[-1]).open
    )

    assert calendar.rolls().select("trade_date", "gap").rows() == [(date(2026, 3, 20), 50 * TICK)]


def test_bars_of_different_widths_share_no_bar(table: SessionTable) -> None:
    # March's bars span each session and June's one bar is the first minute of 03-16: they open
    # together but close 23 hours apart, so no bar measures the gap of the roll to June.
    days = trade_dates(table, date(2026, 3, 16), date(2026, 3, 19))
    march = [(day, "ESH2026", 27_000 + 100 * index, 100) for index, day in enumerate(days)]
    session, price = table.session(days[0]), 27_050 * TICK
    first_minute = (session.open, session.open + 60_000_000_000, days[0], 1003)
    june = pl.DataFrame(
        [(*first_minute, *(price,) * 4, 10, 1, price, "ESM2026")],
        schema=CONTRACT_BAR_COLUMNS,
        orient="row",
    )

    expected = "Expected a bar in which both ESH2026 and ESM2026 traded before the session"
    with pytest.raises(ValueError, match=expected):
        volume_rolls(
            pl.concat([session_bars(march, table), june]),
            table,
            ES,
            table.following(days[-1]).open,
        )


def test_bars_of_a_contract_that_overlap_are_refused(table: SessionTable) -> None:
    # A 5-minute and a 1-minute bar of June from the open of 03-20, bars of two timeframes, count
    # the same prints twice and would flag a roll on the bar that a cut leaves first.
    days = trade_dates(table, date(2026, 3, 16), date(2026, 3, 19))
    rows = [(day, "ESH2026", 27_000, 100) for day in days]
    rows += [(day, "ESM2026", 27_100, 10) for day in days]
    march_20, minute, price = date(2026, 3, 20), 60_000_000_000, 27_100 * TICK
    open_20 = table.session(march_20).open
    june = pl.DataFrame(
        [
            (open_20, open_20 + 5 * minute, march_20, 1003, *(price,) * 4, 5, 1, price, "ESM2026"),
            (
                open_20 + minute,
                open_20 + 2 * minute,
                march_20,
                1003,
                *(price,) * 4,
                1,
                1,
                price,
                "ESM2026",
            ),
        ],
        schema=CONTRACT_BAR_COLUMNS,
        orient="row",
    )
    bars = pl.concat([session_bars(rows, table), june])
    calendar = volume_rolls(session_bars(rows, table), table, ES, open_20)

    expected = "Expected the bars of each contract one after another"
    with pytest.raises(ValueError, match=expected):
        volume_rolls(bars, table, ES, table.following(march_20).open)
    with pytest.raises(ValueError, match=expected):
        calendar.continuous_bars(bars)


def test_a_bar_closing_after_the_next_open_is_refused(table: SessionTable) -> None:
    # A 4-hour bar on UTC hours, from 20:00 to 00:00 UTC and dated 03-05, closes an hour after
    # 03-06's session opens, where a decision would read it before it is in hand.
    open_6, price = table.session(MARCH_6).open, 27_100 * TICK
    prices = (price, price, price, price)
    straddling = pl.DataFrame(
        [(open_6 - 3 * HOUR, open_6 + HOUR, MARCH_5, 1003, *prices, 1_000, 1, price, "ESM2026")],
        schema=CONTRACT_BAR_COLUMNS,
        orient="row",
    )
    bars = pl.concat([session_bars([(MARCH_5, "ESH2026", 27_000, 100)], table), straddling])

    expected = "Expected every bar to close by the open of the session after its trade date"
    with pytest.raises(ValueError, match=expected):
        volume_rolls(bars, table, ES, table.following(MARCH_6).open)


def open_interest(rows: Iterable[tuple[int, str, int]]) -> pl.DataFrame:
    """Open-interest statistics (stat_type 9), each (ts_recv, contract, open interest)."""
    return pl.DataFrame(
        [
            (*(ts_recv,) * 3, INSTRUMENT_IDS[contract], 9, None, quantity, 1, 0, number, contract)
            for number, (ts_recv, contract, quantity) in enumerate(rows, start=1)
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
    march_11, march_12 = table.session(date(2026, 3, 11)), table.session(date(2026, 3, 12))
    statistics = open_interest(
        [
            (table.session(days[0]).open, "ESH2026", 2_000),
            (table.session(days[0]).open, "ESM2026", 1_000),
            (march_11.open + HOUR, "ESM2026", 2_500),
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


def calendar_by_rule(
    rule: RollReason,
    table: SessionTable,
    bars: pl.DataFrame,
    statistics: pl.DataFrame,
    received_until: int,
) -> RollCalendar:
    if rule is RollReason.VOLUME:
        return volume_rolls(bars, table, ES, received_until)
    if rule is RollReason.OPEN_INTEREST:
        return open_interest_rolls(bars, statistics, table, ES, received_until)
    return calendar_rolls(bars, table, ES, received_until, 2)


@pytest.mark.parametrize(
    ("rule", "rolls_on", "reason"),
    [
        (RollReason.VOLUME, date(2026, 3, 20), RollReason.EXPIRY),
        (RollReason.OPEN_INTEREST, date(2026, 3, 19), RollReason.OPEN_INTEREST),
        (RollReason.CALENDAR, date(2026, 3, 18), RollReason.CALENDAR),
    ],
)
def test_every_rule_by_an_instant_stays_the_same_when_the_data_stops_there(
    table: SessionTable, rule: RollReason, rolls_on: date, reason: RollReason
) -> None:
    # ESH2026 out-trades ESM2026 to its last trade date, 03-20, so volume forces the roll there;
    # June's open interest passes March's in a figure received an hour into 03-18, beside one
    # received at the open of 03-19; the calendar rule rolls two sessions before 03-20.
    days = trade_dates(table, date(2026, 3, 16), date(2026, 3, 24))
    march = [(day, "ESH2026", 27_000 + index, 100) for index, day in enumerate(days[:4])]
    june = [(day, "ESM2026", 27_100 + index, 10) for index, day in enumerate(days)]
    bars = session_bars(march + june, table)
    march_18, march_19 = table.session(date(2026, 3, 18)), table.session(date(2026, 3, 19))
    statistics = open_interest(
        [
            (table.session(days[0]).open, "ESH2026", 2_000),
            (table.session(days[0]).open, "ESM2026", 1_000),
            (march_18.open + HOUR, "ESM2026", 2_100),
            (march_19.open, "ESH2026", 1_900),
        ]
    )
    end = table.following(days[-1]).open
    whole = calendar_by_rule(rule, table, bars, statistics, end)
    whole_bars = whole.continuous_bars(bars)
    sessions = [table.session(day) for day in days]
    edges = {
        at
        for session in sessions
        for edge in (session.open, session.close)
        for at in (edge - 1, edge, edge + 1, session.open + HOUR)
    }
    figures = {march_18.open + HOUR + step for step in (-1, 0, 1)}

    assert whole.rolls().select("trade_date", "reason").rows() == [(rolls_on, reason)]
    for cut in sorted(edges | figures | {end}):
        in_hand = bars.filter(pl.col("ts_close") <= cut)
        if in_hand.is_empty():
            continue
        received = statistics.filter(pl.col("ts_recv") <= cut)
        cut_calendar = calendar_by_rule(rule, table, in_hand, received, cut)
        assert_frame_equal(cut_calendar.rows, whole.rows.filter(pl.col("session_open") <= cut))
        assert_frame_equal(
            cut_calendar.continuous_bars(in_hand), whole_bars.filter(pl.col("ts_close") <= cut)
        )


def test_the_back_adjusted_view_shows_the_newest_contract_raw(table: SessionTable) -> None:
    bars = fixture_bars("ohlcv-1m")
    continuous = volume_rolls(bars, table, ES, the_end(table)).continuous_bars(bars)

    display = back_adjusted(continuous)

    by_contract = display.group_by("contract").agg(
        shift=(pl.col("close") - pl.col("close_raw")).unique()
    )
    assert sorted(by_contract.rows()) == [("ESH2026", [fixture_gap(bars)]), ("ESM2026", [0])]
    assert display.filter(
        pl.col("close") != pl.col("close_raw") + pl.col("back_adjustment")
    ).is_empty()
    assert display.schema == BACK_ADJUSTED_COLUMNS
    with pytest.raises(ValueError, match="Expected the columns"):
        back_adjusted(display)


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


NO_SHARED_BAR = re.compile(
    r"Expected a bar in which both (\S+) and (\S+) traded before the session of (\S+), to "
)


def traded_sessions(bars: pl.DataFrame, contract: str, before: date) -> set[date]:
    """The trade dates before `before` on which `contract` has a bar."""
    rows = bars.filter(pl.col("contract") == contract, pl.col("trade_date") < before)
    return set(rows.get_column("trade_date").to_list())


@st.composite
def random_bars(draw: st.DrawFn) -> list[tuple[int, str, int, int]]:
    """For each of the 35 sessions and each contract, a close in ticks and a volume, 0 for no
    bar: the leader moves from March to June to September, a session early or late at random,
    so the rolls fall anywhere and the leader flips back now and then."""
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
    try:
        calendar = volume_rolls(bars, table, ES, table.following(days[-1]).open)
    except ValueError as error:
        refused = NO_SHARED_BAR.match(str(error))
        assert refused is not None, str(error)
        before = date.fromisoformat(refused[3])
        old, new = (traded_sessions(bars, contract, before) for contract in refused.group(1, 2))
        assert old.isdisjoint(new)
        return
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
