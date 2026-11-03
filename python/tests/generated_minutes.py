"""A store of dense 1-minute bars of a futures root written at test time (steps 3.3 and 3.4): each
contract a walk of up to four ticks a minute, leading by volume for a stretch so that the roll
calendar rolls where the volumes cross, and with `quiet` a share of its minutes left without
trades, whose buckets the session grid holds empty (`zero_volume`), as sparse data does."""

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from fefat.config import resolve_paths
from fefat.market import instruments
from fefat.market.calendar import sessions_of
from fefat.market.layout import Dataset, Partition, YearMonth
from fefat.market.schema import parse_schema_name
from fefat.market.store import Store

FIXTURES = Store(Path(__file__).resolve().parents[2] / "fixtures")
MINUTES = Dataset(provider="synthetic", schema_name=parse_schema_name("ohlcv-1m"), root="ES")
MINUTE = 60_000_000_000
TICK = 250_000_000


@dataclass(frozen=True)
class Listing:
    """A contract of a written store: the trade dates it trades and those it leads by volume."""

    contract: str
    instrument_id: int
    trades: tuple[date, date]
    leads: tuple[date, date]


def listing(contract: str, number: int, trades: tuple[str, str], leads: tuple[str, str]) -> Listing:
    first, last = (date.fromisoformat(day) for day in trades)
    leading = tuple(date.fromisoformat(day) for day in leads)
    return Listing(contract, number, (first, last), (leading[0], leading[1]))


SPRING = (
    listing("ESH2026", 1001, ("2026-01-02", "2026-03-20"), ("2026-01-02", "2026-03-10")),
    listing("ESM2026", 1003, ("2026-02-23", "2026-04-30"), ("2026-03-11", "2026-04-30")),
)
"""ES from 2026-01-02 to 04-30, rolling from March to June at the open of 2026-03-12."""

YEAR = (
    listing("ESM2025", 2001, ("2025-04-01", "2025-06-20"), ("2025-04-01", "2025-06-10")),
    listing("ESU2025", 2002, ("2025-05-27", "2025-09-19"), ("2025-06-11", "2025-09-09")),
    listing("ESZ2025", 2003, ("2025-08-25", "2025-12-19"), ("2025-09-10", "2025-12-09")),
    listing("ESH2026", 2004, ("2025-11-24", "2026-03-20"), ("2025-12-10", "2026-03-10")),
    listing("ESM2026", 2005, ("2026-02-23", "2026-03-31"), ("2026-03-11", "2026-03-31")),
)
"""A year of ES from 2025-04-01 to 2026-03-31, rolling each quarter."""


def write_minutes(listings: tuple[Listing, ...], *, root: str = "ES", quiet: float = 0.0) -> Store:
    """The 1-minute bars of `listings`, contracts of `root`, in `FEFAT_DATA_DIR`, a partition a
    contract-month, each close a step of up to four ticks from the one before, drawn from a hash
    of its row, and a `quiet` share of the minutes, drawn alike, without a bar."""
    paths = resolve_paths(os.environ)
    store = Store(paths.data_dir)
    dataset = Dataset(provider=MINUTES.provider, schema_name=MINUTES.schema_name, root=root)
    store.write_dataset_metadata(dataset, FIXTURES.dataset_metadata(MINUTES))
    sessions = sessions_of(instruments.get(root).session_calendar(), paths.cache_dir)
    for each in listings:
        bars = minutes_of(each, sessions.between(*each.trades), quiet)
        months = bars.get_column("trade_date").dt.strftime("%Y-%m").unique().sort()
        for month in months.to_list():
            rows = bars.filter(pl.col("trade_date").dt.strftime("%Y-%m") == month)
            key = YearMonth.parse(month)
            store.write_partition(Partition(dataset=dataset, contract=each.contract, key=key), rows)
    return store


def minutes_of(each: Listing, days: pl.DataFrame, quiet: float = 0.0) -> pl.DataFrame:
    """The listing's bars at every minute of the sessions of `days` outside their halts, but a
    `quiet` share of them."""
    opens = days.select("trade_date", ts_open=pl.int_ranges("open", "close", MINUTE))
    opens = opens.explode("ts_open")
    for start, end in days.select("halts").explode("halts").drop_nulls().unnest("halts").rows():
        opens = opens.filter(~pl.col("ts_open").is_between(start, end, closed="left"))
    step = (pl.int_range(pl.len()).hash(seed=each.instrument_id) % 9).cast(pl.Int64) - 4
    traded = pl.int_range(pl.len()).hash(seed=31 * each.instrument_id) % 1000 >= round(1000 * quiet)
    walked = opens.with_columns(step=step, traded=traded).with_columns(
        close=5_000_000_000_000 + TICK * pl.col("step").cum_sum()
    )
    volume = pl.when(pl.col("trade_date").is_between(*each.leads)).then(100).otherwise(10)
    return (
        walked.filter("traded")
        .with_columns(open=pl.col("close") - TICK * pl.col("step"))
        .select(
            "ts_open",
            ts_close=pl.col("ts_open") + MINUTE,
            trade_date=pl.col("trade_date"),
            instrument_id=pl.lit(each.instrument_id, dtype=pl.UInt32),
            open=pl.col("open"),
            high=pl.max_horizontal("open", "close") + TICK,
            low=pl.min_horizontal("open", "close") - TICK,
            close=pl.col("close"),
            volume=volume.cast(pl.UInt64),
            trade_count=volume.cast(pl.UInt32),
            vwap=pl.col("close"),
        )
    )
