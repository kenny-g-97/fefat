"""The merge of a file's rows into a stored partition (step 5.14, ADR-0021): a record's place is
its instant and its position among the records of that instant; a record at a place the store
lacks is added, one it holds there alike is held, and an instant the two disagree on is disputed
whole. The frames are made up: prices and sizes only tell the records apart."""

from datetime import date

import polars as pl
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fefat.market.importers.partition_merge import (
    DifferingRecords,
    PartitionMerge,
    RecordIdentity,
    merged_partition,
)
from fefat.market.layout import Dataset, Partition, YearMonth
from fefat.market.schema import parse_schema_name, polars_schema

TRADES = parse_schema_name("trades")
MINUTE_BARS = parse_schema_name("ohlcv-1m")
MARCH_30 = Partition(
    dataset=Dataset(provider="ibkr", schema_name=TRADES, root="ES"),
    contract="ESM2026",
    key=date(2026, 3, 30),
)
MARCH = Partition(
    dataset=Dataset(provider="databento", schema_name=MINUTE_BARS, root="ES"),
    contract="ESM2026",
    key=YearMonth(year=2026, month=3),
)
DEFINITIONS = Partition(
    dataset=Dataset(provider="databento", schema_name=parse_schema_name("definitions"), root="ES"),
    contract="ESM2026",
    key=None,
)
BY_RECEIVE_TIME = RecordIdentity(clock="ts_recv")
BY_PLACE = RecordIdentity(clock="ts_recv", numbered_by_place=True)
BY_OPEN = RecordIdentity(clock="ts_open")
REFUSE, TAKE_THE_FILE = DifferingRecords.REFUSE, DifferingRecords.TAKE_THE_FILE


def prints(
    *records: tuple[int, int] | tuple[int, int, int], instrument_id: int = 1003
) -> pl.DataFrame:
    """Trade prints as (instant, price) or (instant, price, sequence), a sequence of 0 where
    none is given."""
    padded = [(*record, 0)[:3] for record in records]
    return pl.DataFrame(
        {
            "ts_recv": [instant for instant, _, _ in padded],
            "ts_event": [instant for instant, _, _ in padded],
            "instrument_id": [instrument_id] * len(padded),
            "price": [price for _, price, _ in padded],
            "size": [1] * len(padded),
            "side": ["N"] * len(padded),
            "sequence": [sequence for _, _, sequence in padded],
        },
        schema=polars_schema(TRADES),
    )


def bars(*records: tuple[int, int], day: date = date(2026, 3, 30)) -> pl.DataFrame:
    """One-minute bars as (minute, close), a vendor's, without a trade count or a vwap."""
    return pl.DataFrame(
        {
            "ts_open": [60 * minute for minute, _ in records],
            "ts_close": [60 * minute + 60 for minute, _ in records],
            "trade_date": [day] * len(records),
            "instrument_id": [1003] * len(records),
            "open": [close for _, close in records],
            "high": [close for _, close in records],
            "low": [close for _, close in records],
            "close": [close for _, close in records],
            "volume": [1] * len(records),
            "trade_count": [None] * len(records),
            "vwap": [None] * len(records),
        },
        schema=polars_schema(MINUTE_BARS),
    )


def counts(merge: PartitionMerge) -> tuple[int, int, int]:
    """The records added, already held, and differing."""
    return merge.added.height, merge.held, merge.differing.height


def test_a_bar_the_store_lacks_is_added_in_clock_order_and_one_it_holds_is_held() -> None:
    stored = bars((1, 10), (2, 11), (4, 13))

    merge = merged_partition(MARCH, stored, bars((2, 11), (3, 12), (5, 14)), BY_OPEN)

    assert counts(merge) == (2, 1, 0)
    assert merge.changes(REFUSE)
    assert merge.rows(REFUSE).equals(bars((1, 10), (2, 11), (3, 12), (4, 13), (5, 14)))


def test_a_partition_the_store_lacks_takes_the_files_rows() -> None:
    incoming = bars((1, 10), (2, 11))

    merge = merged_partition(MARCH, None, incoming, BY_OPEN)

    assert counts(merge) == (2, 0, 0)
    assert merge.rows(REFUSE).equals(incoming)
    assert merge.held_days().to_list() == []


def test_a_file_that_carries_on_an_instant_adds_the_rest() -> None:
    # The store holds the first three prints of second 5, where an earlier file stopped.
    stored = prints((5, 101, 1), (5, 102, 2), (5, 103, 3))
    incoming = prints((5, 101, 1), (5, 102, 2), (5, 103, 3), (5, 104, 4), (6, 105, 5))

    merge = merged_partition(MARCH_30, stored, incoming, BY_RECEIVE_TIME)

    assert counts(merge) == (2, 3, 0)
    assert merge.rows(REFUSE).equals(incoming)


def test_a_file_that_stops_sooner_in_an_instant_adds_nothing_there() -> None:
    stored = prints((5, 101, 1), (5, 102, 2), (5, 103, 3), (6, 104, 4))

    merge = merged_partition(MARCH_30, stored, prints((5, 101, 1), (5, 102, 2)), BY_RECEIVE_TIME)

    assert counts(merge) == (0, 2, 0)
    assert not merge.changes(REFUSE)
    assert not merge.changes(TAKE_THE_FILE)


def test_bars_alike_but_for_their_empty_columns_are_held() -> None:
    # A vendor's bars carry no trade count and no vwap: two nulls are the same value.
    stored = bars((1, 10), (2, 11))

    merge = merged_partition(MARCH, stored, bars((1, 10), (2, 11)), BY_OPEN)

    assert counts(merge) == (0, 2, 0)
    assert not merge.changes(REFUSE)


def test_a_bar_with_other_values_differs_and_stands_only_where_the_files_do() -> None:
    stored = bars((1, 10), (2, 11), (3, 12))
    incoming = bars((2, 99), (3, 12), (4, 13))

    merge = merged_partition(MARCH, stored, incoming, BY_OPEN)

    assert counts(merge) == (1, 1, 1)
    assert merge.stored_records_disputed() == 1
    assert merge.rows(REFUSE).equals(bars((1, 10), (2, 11), (3, 12), (4, 13)))
    assert merge.rows(TAKE_THE_FILE).equals(bars((1, 10), (2, 99), (3, 12), (4, 13)))


def test_an_instant_the_two_disagree_on_is_disputed_whole() -> None:
    # One print of second 5 differs: the file's four prints there all differ, none is held or
    # added, and where the file's stand the store's three give way to them.
    stored = prints((5, 101, 1), (5, 102, 2), (5, 103, 3), (6, 104, 4))
    incoming = prints((5, 101, 1), (5, 999, 2), (5, 103, 3), (5, 105, 5))

    merge = merged_partition(MARCH_30, stored, incoming, BY_RECEIVE_TIME)

    assert counts(merge) == (0, 0, 4)
    assert merge.stored_records_disputed() == 3
    assert not merge.changes(REFUSE)
    assert merge.changes(TAKE_THE_FILE)
    assert merge.rows(TAKE_THE_FILE).equals(
        prints((5, 101, 1), (5, 999, 2), (5, 103, 3), (5, 105, 5), (6, 104, 4))
    )


def test_prints_in_another_order_within_an_instant_differ() -> None:
    stored = prints((5, 101, 1), (5, 102, 2))

    merge = merged_partition(MARCH_30, stored, prints((5, 102, 2), (5, 101, 1)), BY_RECEIVE_TIME)

    assert counts(merge) == (0, 0, 2)


def test_a_venues_sequence_is_part_of_a_print() -> None:
    stored = prints((5, 101, 1), (5, 102, 2))

    merge = merged_partition(MARCH_30, stored, prints((5, 101, 1), (5, 102, 7)), BY_RECEIVE_TIME)

    assert counts(merge) == (0, 0, 2)


def test_prints_without_a_sequence_of_their_own_are_compared_without_it() -> None:
    # The store holds a session imported before step 5.14, numbered by its file's rows; the
    # file's numbers, whatever they are, tell nothing apart and are made anew by place.
    stored = prints((5, 101, 1000), (5, 102, 1001), (5, 103, 1002), (6, 104, 1003))
    incoming = prints(
        (5, 101, 40), (5, 102, 41), (5, 103, 42), (5, 105, 43), (7, 106, 44), (7, 107, 45)
    )

    merge = merged_partition(MARCH_30, stored, incoming, BY_PLACE)

    assert counts(merge) == (3, 3, 0)
    assert merge.rows(REFUSE).equals(
        prints(
            (5, 101, 1000),
            (5, 102, 1001),
            (5, 103, 1002),
            (5, 105, 1003),
            (6, 104, 1003),
            (7, 106, 0),
            (7, 107, 1),
        )
    )


def test_a_new_partition_of_prints_without_a_sequence_numbers_each_by_its_place() -> None:
    incoming = prints((5, 101, 40), (5, 102, 41), (6, 103, 42))

    merge = merged_partition(MARCH_30, None, incoming, BY_PLACE)

    assert merge.rows(REFUSE).get_column("sequence").to_list() == [0, 1, 0]


def test_merging_the_same_rows_again_changes_nothing() -> None:
    stored = prints((5, 101, 1), (5, 102, 2))
    incoming = prints((5, 101, 1), (5, 102, 2), (6, 103, 3))
    merged = merged_partition(MARCH_30, stored, incoming, BY_RECEIVE_TIME).rows(REFUSE)

    again = merged_partition(MARCH_30, merged, incoming, BY_RECEIVE_TIME)

    assert counts(again) == (0, 3, 0)
    assert not again.changes(REFUSE)


def test_the_merged_rows_are_one_chunk() -> None:
    # A sort leaves as many chunks as the pool has threads, and past one row group Polars
    # writes such a frame as other bytes than the same rows in one chunk (measured on 2.1.0),
    # so a partition's hash would follow from the machine that merged it.
    stored = bars(*((minute, 10) for minute in range(0, 4000, 2)))
    incoming = bars((0, 10), *((minute, 10) for minute in range(1, 4000, 2)))

    merged = merged_partition(MARCH, stored, incoming, BY_OPEN).rows(REFUSE)

    assert merged.height == 4000
    assert merged.n_chunks() == 1
    assert merged.get_column("ts_open").is_sorted()


def test_records_under_an_instrument_id_the_partition_does_not_hold_are_refused() -> None:
    stored = prints((5, 101, 1), (6, 102, 2))

    with pytest.raises(
        ValueError,
        match=r"date=2026-03-30/part.parquet under the instrument_id it holds, 1003, got 202606",
    ):
        merged_partition(
            MARCH_30, stored, prints((7, 103, 3), instrument_id=202606), BY_RECEIVE_TIME
        )


def test_a_file_that_overlaps_the_stored_records_without_sharing_one_is_refused() -> None:
    # The same prints an instant apart, as another stamping rule or time zone reads them: every
    # one would read as added, and the partition would hold each twice.
    stored = prints((1_999, 101, 1), (2_999, 102, 2), (3_999, 103, 3))
    incoming = prints((1_000, 101, 1), (2_000, 102, 2), (3_000, 103, 3))

    with pytest.raises(ValueError, match="got none in common: the file reads its times under"):
        merged_partition(MARCH_30, stored, incoming, BY_RECEIVE_TIME)


@pytest.mark.parametrize(
    ("incoming", "added"),
    [
        (prints((4_000, 104, 4), (5_000, 105, 5)), 2),
        (prints((10, 104, 4), (20, 105, 5)), 2),
        (prints((2_100, 104, 4), (2_200, 105, 5)), 2),
        (prints((10, 104, 4), (5_000, 105, 5)), 2),
    ],
    ids=["after the last", "before the first", "in a gap", "on both sides"],
)
def test_a_file_that_shares_no_record_but_does_not_overlap_is_added(
    incoming: pl.DataFrame, added: int
) -> None:
    stored = prints((1_999, 101, 1), (2_999, 102, 2), (3_999, 103, 3))

    merge = merged_partition(MARCH_30, stored, incoming, BY_RECEIVE_TIME)

    assert counts(merge) == (added, 0, 0)


def test_added_and_differing_records_are_counted_per_trade_date() -> None:
    monday, tuesday = date(2026, 3, 30), date(2026, 3, 31)
    stored = pl.concat([bars((1, 10), (2, 11), day=monday), bars((2000, 20), day=tuesday)])
    incoming = pl.concat(
        [bars((2, 99), (3, 12), day=monday), bars((2000, 20), (2001, 21), (2002, 22), day=tuesday)]
    )

    merge = merged_partition(MARCH, stored, incoming, BY_OPEN)

    assert merge.added_days().sort("trade_date").rows() == [(monday, 1), (tuesday, 2)]
    assert merge.differing_days().rows() == [(monday, 1)]
    assert sorted(merge.held_days()) == [monday, tuesday]


def test_prints_take_their_trade_date_from_their_partition_and_definitions_have_none() -> None:
    stored = prints((5, 101, 1))
    incoming = prints((5, 101, 1), (6, 102, 2))

    by_date = merged_partition(MARCH_30, stored, incoming, BY_RECEIVE_TIME)
    undated = merged_partition(DEFINITIONS, stored, incoming, BY_RECEIVE_TIME)

    assert by_date.added_days().rows() == [(date(2026, 3, 30), 1)]
    assert by_date.held_days().to_list() == [date(2026, 3, 30)]
    assert undated.added.height == 1
    assert undated.added_days().is_empty() and undated.held_days().is_empty()


@st.composite
def streams_cut_in_two(draw: st.DrawFn) -> tuple[list[int], int, int]:
    """How many prints each instant of a stream holds, and two cuts of its records: file A
    holds those before `stop`, and may stop inside an instant, and file B those from `start`,
    the first of an instant, with `stop` at or after `start`, so that the two hold the stream."""
    per_instant = draw(st.lists(st.integers(1, 3), min_size=2, max_size=8))
    first_of_b = draw(st.integers(1, len(per_instant) - 1))
    start = sum(per_instant[:first_of_b])
    stop = draw(st.integers(start, sum(per_instant)))
    return per_instant, start, stop


def stream_of(per_instant: list[int]) -> list[tuple[int, int, int]]:
    """A stream's prints as (instant, price, place in the instant), each price its own."""
    return [
        (10 * instant, 100 * instant + place, place)
        for instant, held in enumerate(per_instant)
        for place in range(held)
    ]


@settings(max_examples=300, deadline=None)
@given(cut=streams_cut_in_two(), numbered_by_place=st.booleans())
def test_a_stream_cut_into_two_files_merges_to_itself_in_either_order(
    cut: tuple[list[int], int, int], numbered_by_place: bool
) -> None:
    # Done means 1 on the merge itself: file A is the stream's start and file B its end, the
    # two overlapping or meeting; merged in either order they leave the stream's rows, and
    # either merged again adds nothing. Where the prints carry no sequence of their own, each
    # file numbers its prints by its own rows, which the merge leaves out and makes anew.
    per_instant, start, stop = cut
    stream = stream_of(per_instant)
    whole = prints(*stream)
    identity = BY_PLACE if numbered_by_place else BY_RECEIVE_TIME

    def file_of(records: list[tuple[int, int, int]]) -> pl.DataFrame:
        if not numbered_by_place:
            return prints(*records)
        return prints(*((instant, price, row) for row, (instant, price, _) in enumerate(records)))

    a, b = file_of(stream[:stop]), file_of(stream[start:])
    a_stored = merged_partition(MARCH_30, None, a, identity).rows(REFUSE)
    b_stored = merged_partition(MARCH_30, None, b, identity).rows(REFUSE)

    a_then_b = merged_partition(MARCH_30, a_stored, b, identity)
    b_then_a = merged_partition(MARCH_30, b_stored, a, identity)

    assert a_then_b.differing.is_empty() and b_then_a.differing.is_empty()
    assert a_then_b.rows(REFUSE).equals(whole)
    assert b_then_a.rows(REFUSE).equals(whole)
    assert a_then_b.held == stop - start
    for file in (a, b):
        again = merged_partition(MARCH_30, a_then_b.rows(REFUSE), file, identity)
        assert not again.changes(REFUSE)


def test_bars_read_a_minute_late_land_on_stored_minutes_and_differ() -> None:
    # The engine accuracy review of step 5.14: the same bars stamped a minute late share the
    # stored minutes, so the refusal of a file that shares no instant does not see them. They
    # read as differing, which an import refuses unless it is told that the file's stand.
    stored, late = bars((1, 10), (2, 11), (3, 12)), bars((2, 10), (3, 11), (4, 12))

    merge = merged_partition(MARCH, stored, late, BY_OPEN)

    assert counts(merge) == (1, 0, 2)
    assert not merge.rows(REFUSE).equals(merge.rows(TAKE_THE_FILE))


def test_a_file_that_fills_two_gaps_is_refused_and_told_to_come_a_gap_at_a_time() -> None:
    # Both of its prints lie between stored ones, in two gaps, so the stretch the two share
    # holds prints of both and none in common, as a file read under another time zone does.
    stored = prints((1_000, 101, 1), (3_000, 103, 3), (5_000, 105, 5))
    incoming = prints((2_000, 102, 2), (4_000, 104, 4))

    with pytest.raises(ValueError, match="import each gap's records as a file of their own"):
        merged_partition(MARCH_30, stored, incoming, BY_RECEIVE_TIME)
    for gap in (incoming.head(1), incoming.tail(1)):
        assert counts(merged_partition(MARCH_30, stored, gap, BY_RECEIVE_TIME)) == (1, 0, 0)


@settings(max_examples=300, deadline=None)
@given(cut=streams_cut_in_two())
def test_a_partition_numbered_by_its_files_rows_keeps_the_order_of_its_sequence(
    cut: tuple[list[int], int, int],
) -> None:
    # The sessions imported before step 5.14 number their prints by their file's rows. A later
    # file merged into one numbers the prints it adds on from the stored last, so the partition
    # still reads in its order by receive time and sequence, each pair once: the order the
    # engines take the prints in (F-CLK-03).
    per_instant, start, stop = cut
    stream = stream_of(per_instant)
    by_row = ((instant, price, 1000 + row) for row, (instant, price, _) in enumerate(stream[:stop]))
    later = prints(*((instant, price) for instant, price, _ in stream[start:]))

    merged = merged_partition(MARCH_30, prints(*by_row), later, BY_PLACE).rows(REFUSE)

    assert merged.select("ts_recv", "price").equals(prints(*stream).select("ts_recv", "price"))
    assert merged.equals(merged.sort("ts_recv", "sequence", maintain_order=True))
    assert not merged.select(pl.struct("ts_recv", "sequence").is_duplicated().any()).item()


@pytest.mark.parametrize(
    "incoming",
    [
        bars((2, 11), day=date(2026, 3, 31)),
        bars((3, 12), day=date(2026, 3, 31)),
        bars((7, 16), day=date(2026, 3, 29)),
    ],
    ids=[
        "at an instant the store holds",
        "between instants the store holds",
        "after them on an earlier date",
    ],
)
def test_a_bar_the_store_dates_otherwise_is_refused_whatever_the_import_is_told(
    incoming: pl.DataFrame,
) -> None:
    # Done means 3: under one calendar a bar's trade date follows from its instant, so a file's
    # bar dated otherwise than the stored bars around it was dated under another calendar, and
    # a merge would keep one session under two trade dates.
    stored = pl.concat([bars((1, 10), (2, 11)), bars((5, 14), (6, 15))])

    with pytest.raises(
        ValueError, match="on the trade dates the store gives their instants, got 1"
    ):
        merged_partition(MARCH, stored, incoming, BY_OPEN)


DAILY = Partition(
    dataset=Dataset(provider="ninjatrader", schema_name=parse_schema_name("ohlcv-1d"), root="ES"),
    contract="ESM2026",
    key=None,
)


def daily_bar(opened: int, day: date) -> pl.DataFrame:
    """A session's daily bar opening at `opened`, in nanoseconds since the epoch."""
    return bars((0, 10), day=day).with_columns(ts_open=pl.lit(opened), ts_close=pl.lit(opened + 1))


def test_a_daily_bar_whose_trade_date_the_store_holds_at_another_open_is_refused() -> None:
    # The design review of the plan: a daily bar opens at its session's open, so a calendar
    # change that moves the open of a trade date stores that day's bar twice, at both opens,
    # though it lies between the stored bars around it.
    stored = pl.concat([daily_bar(100, date(2026, 3, 30)), daily_bar(300, date(2026, 3, 31))])

    with pytest.raises(ValueError, match="at the opens the store gives their trade dates, got 1"):
        merged_partition(DAILY, stored, daily_bar(200, date(2026, 3, 31)), BY_OPEN)
