"""The prints of each bucket by aggressor side (step 3.6, D-78): a bucket of the session grid holds
the volume bought, sold, and of no known side of the prints received in it, as a bar holds them
(D-43), and a load's source reads each trade date's prints of the contract whose bars that date
gives, the trades input of a feature."""

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from fefat.market import instruments
from fefat.market.aggressor import SIDE_VOLUME_COLUMNS, VOLUME_COLUMNS, side_volumes
from fefat.market.api import series_source
from fefat.market.calendar import SessionTable, sessions_of
from fefat.market.schema import Timeframe
from notebook_runs import store_with

SECOND, MINUTE, DAY = 1_000_000_000, 60_000_000_000, 86_400_000_000_000
FIVE = Timeframe.parse("5m")
FRIDAY, MONDAY = date(2026, 3, 6), date(2026, 3, 9)


@pytest.fixture
def sessions(tmp_path: Path) -> SessionTable:
    return sessions_of(instruments.get("ES").session_calendar(), tmp_path)


def tape(*prints: tuple[int, int, str]) -> pl.DataFrame:
    """Prints, each received at an instant with its size and aggressor side."""
    return pl.DataFrame(
        prints,
        schema={"ts_recv": pl.Int64, "size": pl.UInt32, "side": pl.String},
        orient="row",
    )


def volumes_of(frame: pl.DataFrame) -> list[tuple[int, ...]]:
    return frame.select(VOLUME_COLUMNS).rows()


def test_a_bucket_holds_the_volume_of_its_prints_by_side(sessions: SessionTable) -> None:
    # Friday's session holds 276 five-minute buckets: the first holds a buy, a sell, and the
    # opening print of no side, the second the buy received on its open, the last a sell, and
    # the buy received 400 ms after the close lies in a bucket of the break, in none of them.
    opened, closed = sessions.session(FRIDAY).open, sessions.session(FRIDAY).close
    prints = tape(
        (opened + MINUTE, 2, "B"),
        (opened + 2 * MINUTE, 1, "A"),
        (opened + 5 * MINUTE - SECOND, 3, "N"),
        (opened + 5 * MINUTE, 4, "B"),
        (closed - SECOND, 5, "A"),
        (closed + 400_000_000, 6, "B"),
    )

    volumes = side_volumes(prints, FIVE, sessions, [FRIDAY], (0, sessions.following(FRIDAY).open))

    assert volumes.schema == SIDE_VOLUME_COLUMNS
    assert volumes.height == 276
    assert volumes.get_column("ts_close").is_sorted()
    assert volumes_of(volumes.head(2)) == [(2, 1, 3), (4, 0, 0)]
    assert volumes_of(volumes.tail(1)) == [(0, 5, 0)]
    assert volumes.select(pl.col(VOLUME_COLUMNS).sum()).row(0) == (6, 6, 3)


def test_a_bucket_closing_after_the_prints_in_hand_is_held_back(sessions: SessionTable) -> None:
    opened = sessions.session(FRIDAY).open
    prints = tape((opened + MINUTE, 2, "B"), (opened + 6 * MINUTE, 4, "A"))

    volumes = side_volumes(prints, FIVE, sessions, [FRIDAY], (0, opened + 7 * MINUTE))

    assert volumes.get_column("ts_close").to_list() == [opened + 5 * MINUTE]
    assert volumes_of(volumes) == [(2, 0, 0)]


def test_a_bucket_closing_before_the_first_print_in_hand_is_held_back(
    sessions: SessionTable,
) -> None:
    # The leakage audit: prints that start an hour into the session, as a file downloaded by
    # UTC day starts at its dataset's first session, leave the buckets before the first print's
    # unknown, not empty, as the bars give none there; the bucket holding it is the first.
    opened = sessions.session(FRIDAY).open
    first = opened + 65 * MINUTE
    prints = tape((first, 3, "B"))

    volumes = side_volumes(prints, FIVE, sessions, [FRIDAY], (first, opened + DAY))

    assert volumes.get_column("ts_open").min() == first
    assert volumes_of(volumes.head(1)) == [(3, 0, 0)]
    assert volumes.height == 276 - 13


def test_a_date_held_without_prints_has_empty_buckets_and_none_held_has_no_rows(
    sessions: SessionTable,
) -> None:
    until = (0, sessions.following(FRIDAY).open)

    held = side_volumes(tape(), FIVE, sessions, [FRIDAY], until)
    none = side_volumes(tape(), FIVE, sessions, [], until)

    assert held.height == 276
    assert set(volumes_of(held)) == {(0, 0, 0)}
    assert none.schema == SIDE_VOLUME_COLUMNS
    assert none.is_empty()


def test_a_source_reads_the_prints_of_the_contract_whose_bars_each_date_gives() -> None:
    # The fixtures' 5-minute bars of 03-06 and 03-09 are built from the prints of each date's
    # front, ESH2026 then ESM2026 after the roll at the open of 03-09, so each bar's volume is
    # its bucket's volume by side, the last bucket of 03-09 held back in both; the opening print
    # of each session, of no side, lies in its first bucket.
    store_with("trades", "ohlcv-1m")
    source = series_source("ES")

    bars = source.signal_bars(FIVE, (FRIDAY, MONDAY))
    volumes = source.side_volumes(FIVE, (FRIDAY, MONDAY))

    assert volumes.select("trade_date", "ts_close").equals(bars.select("trade_date", "ts_close"))
    total = pl.sum_horizontal(VOLUME_COLUMNS)
    assert volumes.get_column("unknown_side_volume").sum() > 0
    assert volumes.select(total).to_series().equals(bars.get_column("volume").cast(pl.Int64))
    unknown = volumes.filter(pl.col("unknown_side_volume") > 0)
    firsts = volumes.group_by("trade_date").agg(pl.col("ts_close").min()).sort("trade_date")
    assert unknown.select("trade_date", "ts_close").equals(firsts)


def test_a_source_without_trades_gives_no_rows() -> None:
    store_with("ohlcv-1m")

    volumes = series_source("ES").side_volumes(FIVE, (FRIDAY, MONDAY))

    assert volumes.schema == SIDE_VOLUME_COLUMNS
    assert volumes.is_empty()
