"""Generate the synthetic market data under fixtures/synthetic/, the only data files in git.

Run it in the project environment, since it writes Parquet through pyarrow and DBN through
databento-dbn, and takes its columns from the SDK's (`fefat.market.schema`):

    uv run python scripts/gen_fixtures.py
    uv run python scripts/gen_fixtures.py --out <folder> --seed <number>
    uv run python scripts/gen_fixtures.py --out <folder outside the repository> \
        --dates 2026-01-02..2026-12-31 --contracts ESH2026 --planted-gaps 3

The last form writes a contract's sessions of a date range (its weekdays, or every day for a
product that trades at weekends), each with planted gaps: jumps of the price and quiet minutes
without prints, as months and years generated at test time need (step 2.7, D-51). It writes the
store's partitions, their `dataset.json`, and the manifest, but not the Databento batch or the
export samples, which belong to the committed set; never commit what it writes.

The files follow the canonical store of docs/masterplan/02-engine-and-data.md
section 1.1, with this folder as the provider `synthetic`: Parquet with zstd,
prices as int64 in 1e-9 units, timestamps as int64 nanoseconds UTC, laid out as
`<schema>/root=…/contract=…/date=…/part.parquet` (1-minute bars per month as
`month=…`). They hold three CME-like ES sessions across the start of US
daylight saving on 2026-03-08 (the UTC open moves from 23:00 to 22:00), traded by
two contracts, `ESH2026` and `ESM2026`, whose volumes cross for the roll calendar
of step 1.7 (June trades less than March on 2026-03-05, more on 03-06, and less
again on 03-09, each session's trade chances scaled by `activity_scale`), a 24x7
BTC perpetual-like UTC day, and the 1-second and 1-minute bars built from their
trades the way section 1.4 builds bars: bucketed by `ts_recv` into
`[t, t + width)` from the session open, sparse, with `ts_open`, `ts_close`,
the session's `trade_date` (the first hour of an ES session falls on the UTC
day before its trade date), and the `vwap` rounded down to 1e-9 units. Each
session also holds planted prints at the edges of bars (step 1.5): one received
exactly on a minute boundary, 90 minutes after the open, one in the last 100 ms
before the close, and, on ESH2026's Friday 2026-03-06, one received 400 ms after the
close, which keeps that trade date in bars opening at the close, as the vendor's
bars do (the importer of step 1.6 dates such prints the same way). A session
opens and closes at local times of its product's time zone, as the calendar of
`fefat.market.calendar` does: ES from
17:00 Chicago the day before its trade date to 16:00 Chicago on it, BTC from
00:00 UTC to 00:00 UTC the next day. The labels follow the SDK: the ES contracts
are `ESH2026` and `ESM2026` (root, month code, four-digit year,
`fefat.market.contracts`) and the BTC root is the instrument key `BTCUSDT-PERP`
(`fefat.market.instruments`).

Trades carry `ts_recv`, `ts_event`, `instrument_id`, `price`, `size` (contracts
for ES, lots of 0.001 BTC for BTC), `side` (the aggressor: `B` buys, `A` sells,
`N` for the opening print), and `sequence`. Each dataset folder
`<schema>/root=…/` holds a `dataset.json` with the unit of its sizes and volumes
(`size_unit`: one unit is `lot` of `asset`), its `origin`, an import, and its
`licence_scope`, which no licence limits. MANIFEST.json lists every file with
the generator, the seed, its size, and its SHA-256, and each Parquet file's row
count.

The BTC perpetual also holds its funding rates (step 2.9), the store's first funding data, as
Binance fixes them every eight hours from 00:00 UTC: one row per funding time of its day in
`funding/root=BTCUSDT-PERP/contract=BTCUSDT-PERP/part.parquet`, `ts_recv` and `ts_event` both
the funding time, and the rate in 1e-9 units with eight decimals, as Binance publishes it, drawn
from its own `random.Random` seeded with "<seed>/<contract>/funding" (ADR-0019).

Beside the provider folders, `databento-batch/<job>/` holds a Databento batch download as the
importer of step 1.6 reads one: the ES 1-minute bars as a DBN file (`ESH6`, instrument_id
1001), with a calendar spread `ESH6-ESM6` (1002) trading now and then, which the importer
skips, encoded by the vendor's own encoder; `metadata.json` with the query, `condition.json`
with each day's condition (one degraded), and `manifest.json` with each other file's size and
SHA-256, as Databento writes them. Beside them, `exports/<preset>/` holds each import preset's
sample (step 1.10): ESH2026's 1-minute bars of the three sessions in the exact layout of the
platform's export, as `docs/masterplan/appendix/research-data-sources.md` (Part D) gives it,
NinjaTrader's stamped at the close in UTC, TradingView's in Unix seconds, IBKR's in New York
time with the zone name the TWS API adds, Sierra Chart's with unpadded dates, TradeStation's
stamped at the close in Chicago time with its times as numbers, and Databento's CSV export of
the batch, spreads included. Each session draws from its own
`random.Random`, seeded with "<seed>/<contract>/<trade date>", so the two ES
contracts draw different tapes. Times and durations here are integer
nanoseconds; instants count from the Unix epoch in UTC.

The same seed gives byte-identical files: the randomness uses `random.Random`
draws, comparisons, and integer arithmetic only (no `gauss` or `expovariate`,
whose results depend on the platform's maths library), and the writer options
are fixed, so the files should match on every platform; Windows is shown, and
CI on Linux (step 0.6) is the first check elsewhere. pyarrow writes its version
into every file and is pinned for that reason: after a pyarrow upgrade the
fixtures are regenerated and committed with the manifest.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import random
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from itertools import groupby
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
from databento_dbn import Metadata, OHLCVMsg, RType, Schema, SType
from databento_dbn.metadata import MappingInterval

from fefat.market.schema import parse_schema_name, polars_schema

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "fixtures" / "synthetic"
DEFAULT_SEED = 20260308
GENERATOR = "scripts/gen_fixtures.py"
MANIFEST_NAME = "MANIFEST.json"
DATASET_METADATA_NAME = "dataset.json"
LICENCE_SCOPE = "Synthetic data of scripts/gen_fixtures.py; no licence applies"

DATABENTO_JOB = "GLBX-20260310-SYNTHETIC0"
DATABENTO_DATA_FILE = "glbx-mdp3-20260304-20260309.ohlcv-1m.dbn"
DATABENTO_QUERY = (date(2026, 3, 4), date(2026, 3, 10))
DATABENTO_PUBLISHER = 1
DATABENTO_OUTRIGHT = "ESH6"
DATABENTO_SPREAD = ("ESH6-ESM6", 1002)
DATABENTO_SPREAD_EVERY = 100
DATABENTO_DEGRADED_DAY = date(2026, 3, 6)

NANOSECONDS_PER_SECOND = 1_000_000_000
NANOSECONDS_PER_MINUTE = 60 * NANOSECONDS_PER_SECOND
SLOT_LENGTH = 100_000_000
QUIET_BEFORE_CLOSE = NANOSECONDS_PER_SECOND
OPENING_PRINT_DELAY = (1_000_000, 50_000_000)
OPENING_PRINT_SIZE = (50, 400)
RECEIVE_LATENCY = (20_000, 400_000)
WEEKEND_GAP_FACTOR = 3
SATURDAY = 5
SUNDAY = 6
BOUNDARY_PRINT_AFTER_OPEN = 90 * NANOSECONDS_PER_MINUTE
LAST_SLOT_PRINT_BEFORE_CLOSE = 50_000_000
AFTER_CLOSE_PRINT_DELAY = 400_000_000
AFTER_CLOSE_PRINT_DAY = date(2026, 3, 6)
PLANTED_PRINT_LATENCY = 150_000
PLANTED_PRINT_SIZE = 1

BUYER = "B"
SELLER = "A"
NO_AGGRESSOR = "N"
UPTICK_BELOW = 0.15
DOWNTICK_BELOW = 0.30
PRINTS_PER_EVENT = ((1, 0.75), (2, 0.90), (3, 0.97), (4, 1.0))

_ARROW_TYPES = (
    (pl.Int64, pa.int64()),
    (pl.UInt32, pa.uint32()),
    (pl.UInt64, pa.uint64()),
    (pl.String, pa.string()),
    (pl.Date, pa.date32()),
)
"""The pyarrow type each column type of the store is written as."""


def arrow_schema(schema_name: str) -> pa.Schema:
    """The columns of a store schema as the SDK defines them (`fefat.market.schema`), in order and
    with their types, as the pyarrow schema the fixtures are written in."""
    fields = []
    for name, dtype in polars_schema(parse_schema_name(schema_name)).items():
        arrow = next((arrow for polars, arrow in _ARROW_TYPES if dtype == polars), None)
        if arrow is None:
            raise ValueError(
                f"Expected a column type the fixtures can write, got {dtype} for {name} of "
                f"{schema_name}."
            )
        fields.append((name, arrow))
    return pa.schema(fields)


TRADES_SCHEMA = arrow_schema("trades")
BARS_SCHEMA = arrow_schema("ohlcv-1m")
FUNDING_SCHEMA = arrow_schema("funding")
FUNDING_TIMES = (time(0, 0), time(8, 0), time(16, 0))
"""When Binance fixes a USD-M perpetual's funding, UTC."""
FUNDING_RATE_STEPS = (-5_000, 15_000)
"""A funding rate's range in steps of 1e-8, Binance's eight decimals: -0.00005 to 0.00015."""


@dataclass(frozen=True)
class ActivityWindow:
    """A stretch of the session, in minutes after the open, with the chance of a trade per slot."""

    start_minute: int
    end_minute: int
    trade_chance: float


@dataclass(frozen=True)
class FixtureProduct:
    """An instrument in the fixture set: its specification, its trading day, and its sessions,
    each with a factor on the trade chances of its activity windows (`activity_scale`), and
    whether a date range gives it weekend sessions."""

    root: str
    contract: str
    instrument_id: int
    size_lot: str
    size_asset: str
    tick: int
    first_price_ticks: int
    time_zone: ZoneInfo
    opens_at: time
    opens_on_previous_day: bool
    closes_at: time
    activity: tuple[ActivityWindow, ...]
    trade_sizes: tuple[tuple[int, float], ...]
    opening_auction: bool
    opening_gap_ticks: int
    trade_dates: tuple[date, ...]
    activity_scale: tuple[float, ...]
    trades_on_weekends: bool = False

    def __post_init__(self) -> None:
        if len(self.activity_scale) != len(self.trade_dates):
            raise ValueError(
                f"Expected an activity factor for each of the {len(self.trade_dates)} trade dates "
                f"of {self.contract}, got {len(self.activity_scale)}."
            )

    def scale_on(self, trade_date: date) -> float:
        return self.activity_scale[self.trade_dates.index(trade_date)]


ES = FixtureProduct(
    root="ES",
    contract="ESH2026",
    instrument_id=1001,
    size_lot="1",
    size_asset="contract",
    tick=250_000_000,
    first_price_ticks=27_400,
    time_zone=ZoneInfo("America/Chicago"),
    opens_at=time(17, 0),
    opens_on_previous_day=True,
    closes_at=time(16, 0),
    activity=(
        ActivityWindow(0, 930, 0.02),
        ActivityWindow(930, 940, 0.40),
        ActivityWindow(940, 1315, 0.15),
        ActivityWindow(1315, 1335, 0.30),
        ActivityWindow(1335, 1380, 0.03),
    ),
    trade_sizes=(
        (1, 0.40),
        (2, 0.60),
        (3, 0.70),
        (4, 0.77),
        (5, 0.85),
        (10, 0.91),
        (20, 0.96),
        (50, 0.99),
        (100, 1.0),
    ),
    opening_auction=True,
    opening_gap_ticks=12,
    trade_dates=(date(2026, 3, 5), date(2026, 3, 6), date(2026, 3, 9)),
    activity_scale=(1.0, 1.0, 1.0),
)
ES_JUNE = replace(
    ES,
    contract="ESM2026",
    instrument_id=1003,
    first_price_ticks=27_500,
    activity_scale=(0.3, 1.5, 0.6),
)
BTC = FixtureProduct(
    root="BTCUSDT-PERP",
    contract="BTCUSDT-PERP",
    instrument_id=2001,
    size_lot="0.001",
    size_asset="BTC",
    tick=100_000_000,
    first_price_ticks=980_000,
    time_zone=ZoneInfo("UTC"),
    opens_at=time(0, 0),
    opens_on_previous_day=False,
    closes_at=time(0, 0),
    activity=(
        ActivityWindow(0, 810, 0.04),
        ActivityWindow(810, 1200, 0.08),
        ActivityWindow(1200, 1440, 0.04),
    ),
    trade_sizes=(
        (1, 0.25),
        (2, 0.40),
        (5, 0.55),
        (10, 0.70),
        (25, 0.80),
        (50, 0.88),
        (100, 0.95),
        (250, 0.98),
        (1000, 1.0),
    ),
    opening_auction=False,
    opening_gap_ticks=0,
    trade_dates=(date(2026, 3, 7),),
    activity_scale=(1.0,),
    trades_on_weekends=True,
)
PRODUCTS = (ES, ES_JUNE, BTC)


def in_date_range(product: FixtureProduct, first: date, last: date) -> FixtureProduct:
    """`product` trading every session from `first` to `last`, weekdays only unless it trades at
    weekends, each at its full activity."""
    days = (first + timedelta(days=offset) for offset in range((last - first).days + 1))
    trade_dates = tuple(
        day for day in days if product.trades_on_weekends or day.weekday() < SATURDAY
    )
    if not trade_dates:
        raise ValueError(
            f"Expected a session of {product.contract} from {first} to {last}, got none."
        )
    return replace(product, trade_dates=trade_dates, activity_scale=(1.0,) * len(trade_dates))


@dataclass(frozen=True)
class Session:
    """One trading session of a product, from its local open to its local close, as UTC instants."""

    product: FixtureProduct
    trade_date: date

    def opening_day(self) -> date:
        if self.product.opens_on_previous_day:
            return self.trade_date - timedelta(days=1)
        return self.trade_date

    def open_time(self) -> int:
        local_open = datetime.combine(
            self.opening_day(), self.product.opens_at, tzinfo=self.product.time_zone
        )
        return int(local_open.timestamp()) * NANOSECONDS_PER_SECOND

    def closing_day(self) -> date:
        if self.product.opens_on_previous_day or self.product.closes_at > self.product.opens_at:
            return self.trade_date
        return self.trade_date + timedelta(days=1)

    def close_time(self) -> int:
        local_close = datetime.combine(
            self.closing_day(), self.product.closes_at, tzinfo=self.product.time_zone
        )
        return int(local_close.timestamp()) * NANOSECONDS_PER_SECOND

    def opens_after_weekend(self) -> bool:
        return self.opening_day().weekday() == SUNDAY

    def trading_slots(self) -> Iterator[tuple[int, float]]:
        """Yield each 100 ms slot after the opening print with the chance of a trade in it."""
        first_slot = self.open_time() + SLOT_LENGTH
        last_slot = self.close_time() - QUIET_BEFORE_CLOSE
        scale = self.product.scale_on(self.trade_date)
        for window in self.product.activity:
            window_start = self.open_time() + window.start_minute * NANOSECONDS_PER_MINUTE
            window_end = self.open_time() + window.end_minute * NANOSECONDS_PER_MINUTE
            for slot_start in range(
                max(window_start, first_slot), min(window_end, last_slot), SLOT_LENGTH
            ):
                yield slot_start, window.trade_chance * scale


class TapeRecorder:
    """Collects one session's prints as columns, keeping `ts_recv` non-decreasing."""

    def __init__(self, product: FixtureProduct) -> None:
        self._product = product
        self._columns: dict[str, list[int | str]] = {name: [] for name in TRADES_SCHEMA.names}
        self._last_receive_time = 0

    def record(
        self, event_time: int, latency: int, price_ticks: int, side: str, sizes: Sequence[int]
    ) -> None:
        receive_time = max(self._last_receive_time, event_time + latency)
        for size in sizes:
            print_row = {
                "ts_recv": receive_time,
                "ts_event": event_time,
                "instrument_id": self._product.instrument_id,
                "price": price_ticks * self._product.tick,
                "size": size,
                "side": side,
                "sequence": len(self._columns["sequence"]) + 1,
            }
            for name, value in print_row.items():
                self._columns[name].append(value)
        self._last_receive_time = receive_time

    def tape(self) -> pa.Table:
        return pa.table(self._columns, schema=TRADES_SCHEMA)


def drawn_from(table: Sequence[tuple[int, float]], random_source: random.Random) -> int:
    """Draw a value from a table of (value, cumulative chance) rows ending at 1.0."""
    chance = random_source.random()
    return next(value for value, cumulative in table if chance < cumulative)


def price_move(random_source: random.Random) -> int:
    chance = random_source.random()
    if chance < UPTICK_BELOW:
        return 1
    if chance < DOWNTICK_BELOW:
        return -1
    return 0


def aggressor(move: int, random_source: random.Random) -> str:
    if move > 0:
        return BUYER
    if move < 0:
        return SELLER
    return BUYER if random_source.random() < 0.5 else SELLER


def opening_price_ticks(
    previous_close_ticks: int, session: Session, random_source: random.Random
) -> int:
    gap_ticks = session.product.opening_gap_ticks
    if session.opens_after_weekend():
        gap_ticks *= WEEKEND_GAP_FACTOR
    return previous_close_ticks + random_source.randrange(-gap_ticks, gap_ticks + 1)


def simulate_session(
    session: Session, random_source: random.Random, price_ticks: int
) -> tuple[pa.Table, int]:
    """Return the session's trades and its last price in ticks."""
    product = session.product
    recorder = TapeRecorder(product)
    if product.opening_auction:
        opening_time = session.open_time() + random_source.randrange(*OPENING_PRINT_DELAY)
        opening_size = random_source.randrange(*OPENING_PRINT_SIZE)
        recorder.record(
            opening_time,
            random_source.randrange(*RECEIVE_LATENCY),
            price_ticks,
            NO_AGGRESSOR,
            (opening_size,),
        )
    for slot_start, trade_chance in session.trading_slots():
        if random_source.random() >= trade_chance:
            continue
        move = price_move(random_source)
        price_ticks += move
        sizes = [
            drawn_from(product.trade_sizes, random_source)
            for _ in range(drawn_from(PRINTS_PER_EVENT, random_source))
        ]
        event_time = slot_start + random_source.randrange(SLOT_LENGTH)
        recorder.record(
            event_time,
            random_source.randrange(*RECEIVE_LATENCY),
            price_ticks,
            aggressor(move, random_source),
            sizes,
        )
    return recorder.tape(), price_ticks


def planted_receive_times(session: Session) -> list[int]:
    """When the planted prints of a session arrive: on a minute boundary, in the last slot
    before the close, and on ES's 2026-03-06 after the close."""
    receive_times = [
        session.open_time() + BOUNDARY_PRINT_AFTER_OPEN,
        session.close_time() - LAST_SLOT_PRINT_BEFORE_CLOSE,
    ]
    if session.product is ES and session.trade_date == AFTER_CLOSE_PRINT_DAY:
        receive_times.append(session.close_time() + AFTER_CLOSE_PRINT_DELAY)
    return receive_times


def with_planted_prints(trades: pa.Table, session: Session) -> pa.Table:
    """The session's tape with its planted prints, each at the price of the print received
    before it, sorted by `ts_recv` (a planted print follows a print received at the same
    instant) and numbered again. The planted prints draw nothing from the session's random
    source, so the rest of the tape stays as it was."""
    prints = trades.to_pylist()
    received = [int(trade["ts_recv"]) for trade in prints]
    for receive_time in planted_receive_times(session):
        received_before = bisect.bisect_right(received, receive_time)
        if received_before == 0:
            raise ValueError(
                f"Expected a print before the one planted at {receive_time} in the session of "
                f"{session.product.root} {session.trade_date}, got none."
            )
        previous = prints[received_before - 1]
        prints.append(
            previous
            | {
                "ts_recv": receive_time,
                "ts_event": receive_time - PLANTED_PRINT_LATENCY,
                "size": PLANTED_PRINT_SIZE,
                "side": BUYER,
            }
        )
    ordered = sorted(prints, key=lambda trade: int(trade["ts_recv"]))
    numbered = [trade | {"sequence": number} for number, trade in enumerate(ordered, start=1)]
    return pa.Table.from_pylist(numbered, schema=TRADES_SCHEMA)


QUIET_MINUTES = (1, 6)
"""How long a planted quiet stretch lasts, in whole minutes, from the first to just before the
second."""
JUMP_TICKS = (2, 61)
"""How far a planted jump moves the price, in ticks, from the first to just before the second."""


def with_planted_gaps(trades: pa.Table, session: Session, seed: int, count: int) -> pa.Table:
    """The session's tape with `count` quiet stretches of one to five minutes without prints and
    `count` jumps of 2 to 60 ticks, up or down, from which every later print of the session is
    moved, so that bars of a minute go missing (F-BAR-07) and gaps pass stops and limits. They
    draw from a random source of their own, so the rest of the tape stays as it was."""
    if count == 0:
        return trades
    random_source = random.Random(
        f"{seed}/{session.product.contract}/{session.trade_date.isoformat()}/gaps"
    )
    first, last = session.open_time(), session.close_time()
    frame = pl.DataFrame(trades)
    received, price = pl.col("ts_recv"), pl.col("price")
    for _ in range(count):
        start = random_source.randrange(first, last)
        length = random_source.randrange(*QUIET_MINUTES) * NANOSECONDS_PER_MINUTE
        frame = frame.filter(~received.is_between(start, start + length, closed="left"))
        jump_at = random_source.randrange(first, last)
        ticks = random_source.choice((-1, 1)) * random_source.randrange(*JUMP_TICKS)
        moved = pl.when(received >= jump_at).then(price + ticks * session.product.tick)
        frame = frame.with_columns(price=moved.otherwise(price))
    numbered = frame.with_columns(sequence=pl.int_range(1, pl.len() + 1, dtype=pl.UInt32))
    return numbered.to_arrow().cast(TRADES_SCHEMA)


def bars_from_trades(trades: pa.Table, session: Session, width: int) -> pa.Table:
    """Bucket trades by `ts_recv` into [t, t + width) from the session open; only buckets with trades."""
    anchor = session.open_time()
    received = trades.column("ts_recv").to_pylist()
    prices = trades.column("price").to_pylist()
    sizes = trades.column("size").to_pylist()
    instrument_ids = trades.column("instrument_id").to_pylist()
    columns: dict[str, list[int | date]] = {name: [] for name in BARS_SCHEMA.names}
    for bucket, rows in groupby(
        range(len(received)), key=lambda row: (received[row] - anchor) // width
    ):
        members = list(rows)
        bucket_prices = [prices[row] for row in members]
        volume = sum(sizes[row] for row in members)
        ts_open = anchor + bucket * width
        bar = {
            "ts_open": ts_open,
            "ts_close": ts_open + width,
            "trade_date": session.trade_date,
            "instrument_id": instrument_ids[members[0]],
            "open": bucket_prices[0],
            "high": max(bucket_prices),
            "low": min(bucket_prices),
            "close": bucket_prices[-1],
            "volume": volume,
            "trade_count": len(members),
            "vwap": sum(prices[row] * sizes[row] for row in members) // volume,
        }
        for name, value in bar.items():
            columns[name].append(value)
    return pa.table(columns, schema=BARS_SCHEMA)


def partition_path(out: Path, schema: str, product: FixtureProduct, key: str) -> Path:
    return (
        out
        / schema
        / f"root={product.root}"
        / f"contract={product.contract}"
        / key
        / "part.parquet"
    )


def written_partition(table: pa.Table, path: Path, out: Path, seed: int) -> dict[str, str | int]:
    """Write one Parquet partition and return its manifest entry."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        table, path, compression="zstd", compression_level=9, version="2.6", data_page_version="1.0"
    )
    return manifest_entry(path, out, seed) | {"rows": table.num_rows}


def written_dataset_metadata(
    product: FixtureProduct, schema: str, out: Path, seed: int
) -> dict[str, str | int]:
    """Write a dataset's `dataset.json`, the unit of its sizes and volumes, its origin, and its
    licence scope, and return its entry."""
    path = out / schema / f"root={product.root}" / DATASET_METADATA_NAME
    metadata = {
        "size_unit": {"lot": product.size_lot, "asset": product.size_asset},
        "origin": "import",
        "licence_scope": LICENCE_SCOPE,
    }
    path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8", newline="\n")
    return manifest_entry(path, out, seed)


def manifest_entry(path: Path, out: Path, seed: int) -> dict[str, str | int]:
    content = path.read_bytes()
    return {
        "path": path.relative_to(out).as_posix(),
        "generator": GENERATOR,
        "seed": seed,
        "bytes": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def month_of(product: FixtureProduct) -> str:
    months = {trade_date.strftime("%Y-%m") for trade_date in product.trade_dates}
    if len(months) != 1:
        raise ValueError(
            f"Expected the trade dates of {product.root} in one month (1-minute bars are stored per month), got {sorted(months)}."
        )
    return months.pop()


def written_product(
    product: FixtureProduct, out: Path, seed: int, planted_gaps: int = 0
) -> list[dict[str, str | int]]:
    """Write a contract's trades and 1-second bars per trade date and its 1-minute bars per
    month, each session with `planted_gaps` quiet stretches and jumps."""
    entries: list[dict[str, str | int]] = []
    minute_bars: dict[str, list[pa.Table]] = {}
    price_ticks = product.first_price_ticks
    for trade_date in product.trade_dates:
        session = Session(product, trade_date)
        random_source = random.Random(f"{seed}/{product.contract}/{trade_date.isoformat()}")
        tape, price_ticks = simulate_session(
            session, random_source, opening_price_ticks(price_ticks, session, random_source)
        )
        trades = with_planted_gaps(with_planted_prints(tape, session), session, seed, planted_gaps)
        if planted_gaps:
            price_ticks = trades.column("price")[-1].as_py() // product.tick
        day = f"date={trade_date.isoformat()}"
        second_bars = bars_from_trades(trades, session, NANOSECONDS_PER_SECOND)
        entries.append(
            written_partition(trades, partition_path(out, "trades", product, day), out, seed)
        )
        entries.append(
            written_partition(second_bars, partition_path(out, "ohlcv-1s", product, day), out, seed)
        )
        month_bars = minute_bars.setdefault(trade_date.strftime("%Y-%m"), [])
        month_bars.append(bars_from_trades(trades, session, NANOSECONDS_PER_MINUTE))
    for month, tables in minute_bars.items():
        month_path = partition_path(out, "ohlcv-1m", product, f"month={month}")
        entries.append(written_partition(pa.concat_tables(tables), month_path, out, seed))
    return entries


def written_funding(product: FixtureProduct, out: Path, seed: int) -> list[dict[str, str | int]]:
    """Write a perpetual's funding rates, one at each funding time of each of its trade dates, and
    their `dataset.json`, and return their manifest entries."""
    random_source = random.Random(f"{seed}/{product.contract}/funding")
    columns: dict[str, list[int]] = {name: [] for name in FUNDING_SCHEMA.names}
    for trade_date in product.trade_dates:
        for clock in FUNDING_TIMES:
            instant = datetime.combine(trade_date, clock, tzinfo=ZoneInfo("UTC"))
            ts = int(instant.timestamp()) * NANOSECONDS_PER_SECOND
            columns["ts_recv"].append(ts)
            columns["ts_event"].append(ts)
            columns["instrument_id"].append(product.instrument_id)
            columns["funding_rate"].append(random_source.randint(*FUNDING_RATE_STEPS) * 10)
    path = (
        out / "funding" / f"root={product.root}" / f"contract={product.contract}" / "part.parquet"
    )
    table = pa.table(columns, schema=FUNDING_SCHEMA)
    partition = written_partition(table, path, out, seed)
    return [partition, written_dataset_metadata(product, "funding", out, seed)]


@dataclass
class DatabentoInterval:
    """A symbology interval as the DBN encoder takes it: the symbol is the instrument_id."""

    start_date: date
    end_date: date
    symbol: str


@dataclass
class DatabentoMapping:
    raw_symbol: str
    intervals: Sequence[MappingInterval]


def utc_midnight(day: date) -> int:
    return int(datetime.combine(day, time(), tzinfo=ZoneInfo("UTC")).timestamp()) * (
        NANOSECONDS_PER_SECOND
    )


def databento_metadata() -> Metadata:
    """The header of a batch download of the parent `ES.FUT` with the vendor's symbology."""
    start, end = DATABENTO_QUERY
    spread = DATABENTO_SPREAD[0]
    mappings = [
        DatabentoMapping(raw_symbol, [DatabentoInterval(start, end, str(instrument_id))])
        for raw_symbol, instrument_id in ((DATABENTO_OUTRIGHT, ES.instrument_id), DATABENTO_SPREAD)
    ]
    return Metadata(
        dataset="GLBX.MDP3",
        start=utc_midnight(start),
        stype_in=SType("parent"),
        stype_out=SType("instrument_id"),
        schema=Schema("ohlcv-1m"),
        symbols=[f"{ES.root}.FUT"],
        partial=[DATABENTO_OUTRIGHT, spread],
        not_found=[],
        mappings=mappings,
        end=utc_midnight(end),
    )


def databento_bars(bars: list[dict[str, int]], random_source: random.Random) -> list[OHLCVMsg]:
    """The ES 1-minute bars as the vendor's records, with a spread bar beside every hundredth,
    sorted by bar open as the vendor sorts them."""
    minute = int(RType.from_str("ohlcv-1m"))
    records: list[OHLCVMsg] = []
    for index, bar in enumerate(bars):
        prices = (bar["open"], bar["high"], bar["low"], bar["close"])
        records.append(
            OHLCVMsg(
                minute,
                DATABENTO_PUBLISHER,
                ES.instrument_id,
                bar["ts_open"],
                *prices,
                bar["volume"],
            )
        )
        if index % DATABENTO_SPREAD_EVERY == 0:
            spread_price = random_source.randrange(-200, -150) * ES.tick
            spread_prices = (spread_price, spread_price + ES.tick, spread_price, spread_price)
            records.append(
                OHLCVMsg(
                    minute,
                    DATABENTO_PUBLISHER,
                    DATABENTO_SPREAD[1],
                    bar["ts_open"],
                    *spread_prices,
                    random_source.randrange(1, 6),
                )
            )
    return records


def written_json(path: Path, content: object) -> Path:
    path.write_text(json.dumps(content, indent=4) + "\n", encoding="utf-8", newline="\n")
    return path


def databento_query() -> dict[str, object]:
    start, end = DATABENTO_QUERY
    return {
        "version": 1,
        "job_id": DATABENTO_JOB,
        "query": {
            "dataset": "GLBX.MDP3",
            "schema": "ohlcv-1m",
            "symbols": [f"{ES.root}.FUT"],
            "stype_in": "parent",
            "stype_out": "instrument_id",
            "start": utc_midnight(start),
            "end": utc_midnight(end),
            "limit": None,
            "encoding": "dbn",
            "compression": None,
        },
        "customizations": {"map_symbols": False, "pretty_px": False, "pretty_ts": False},
    }


def databento_conditions() -> list[dict[str, str]]:
    """A condition per date of the query, Saturdays left out, as the vendor lists them."""
    start, end = DATABENTO_QUERY
    days = [start + timedelta(days=offset) for offset in range((end - start).days)]
    return [
        {
            "date": day.isoformat(),
            "condition": "degraded" if day == DATABENTO_DEGRADED_DAY else "available",
            "last_modified_date": max(day, date(2026, 3, 8)).isoformat(),
        }
        for day in days
        if day.weekday() != SATURDAY
    ]


def vendor_manifest(paths: Sequence[Path]) -> dict[str, object]:
    files = [
        {
            "filename": path.name,
            "size": path.stat().st_size,
            "hash": f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}",
        }
        for path in paths
    ]
    return {"job_id": DATABENTO_JOB, "files": files}


def written_databento_batch(out: Path, seed: int) -> list[dict[str, str | int]]:
    """Write the Databento batch download of the ES 1-minute bars, after the ES files, and
    return the entries of its four files."""
    folder = out / "databento-batch" / DATABENTO_JOB
    folder.mkdir(parents=True, exist_ok=True)
    month = f"month={month_of(ES)}"
    bars = pq.read_table(partition_path(out, "ohlcv-1m", ES, month)).to_pylist()
    records = databento_bars(bars, random.Random(f"{seed}/databento-batch"))
    data_file = folder / DATABENTO_DATA_FILE
    data_file.write_bytes(
        databento_metadata().encode() + b"".join(bytes(record) for record in records)
    )
    sidecars = [
        written_json(folder / "condition.json", databento_conditions()),
        written_json(folder / "metadata.json", databento_query()),
    ]
    manifest = written_json(folder / "manifest.json", vendor_manifest([*sidecars, data_file]))
    return [manifest_entry(path, out, seed) for path in (data_file, *sidecars, manifest)]


def decimal_text(nano: int, decimals: int | None = None) -> str:
    """A price in 1e-9 units as a decimal: with exactly `decimals` decimals, or as few as it
    needs, as most platforms write prices."""
    whole, part = divmod(abs(nano), NANOSECONDS_PER_SECOND)
    sign = "-" if nano < 0 else ""
    written = f"{sign}{whole}.{part:09d}"
    if decimals is not None:
        return written[: len(written) - 9 + decimals]
    return written.rstrip("0").rstrip(".")


def local_time(instant: int, time_zone: str) -> datetime:
    return datetime.fromtimestamp(instant // NANOSECONDS_PER_SECOND, ZoneInfo(time_zone))


def ninjatrader_line(bar: dict[str, int]) -> str:
    """NinjaTrader 8's minute bar: stamped at its close, in UTC, separated by semicolons."""
    stamp = local_time(bar["ts_close"], "UTC").strftime("%Y%m%d %H%M%S")
    prices = ";".join(decimal_text(bar[price]) for price in ("open", "high", "low", "close"))
    return f"{stamp};{prices};{bar['volume']}"


def tradingview_line(bar: dict[str, int]) -> str:
    """TradingView's bar: its open in Unix seconds, prices, and the Volume column."""
    prices = ",".join(decimal_text(bar[price]) for price in ("open", "high", "low", "close"))
    return f"{bar['ts_open'] // NANOSECONDS_PER_SECOND},{prices},{bar['volume']}"


def ibkr_line(bar: dict[str, int]) -> str:
    """A TWS API bar saved as CSV: its open in the login's zone, here New York, with the zone
    name the API adds after the time, and the bar's average price and trade count."""
    stamp = local_time(bar["ts_open"], "America/New_York").strftime("%Y%m%d %H:%M:%S")
    prices = ",".join(decimal_text(bar[price]) for price in ("open", "high", "low", "close"))
    return f"{stamp} US/Eastern,{prices},{bar['volume']},{decimal_text(bar['vwap'])},{bar['trade_count']}"


def sierra_chart_line(bar: dict[str, int]) -> str:
    """Sierra Chart's intraday export: its open in UTC, an unpadded date, a space after each
    comma, and its number of trades."""
    stamp = local_time(bar["ts_open"], "UTC")
    day = f"{stamp.year}/{stamp.month}/{stamp.day}"
    prices = ", ".join(decimal_text(bar[price]) for price in ("open", "high", "low", "close"))
    return f"{day}, {stamp:%H:%M:%S}, {prices}, {bar['volume']}, {bar['trade_count']}, 0, 0"


def tradestation_line(bar: dict[str, int]) -> str:
    """TradeStation's ASCII bar: stamped at its close in the chart's zone, here Chicago, the
    time written as a number (930, 0 at midnight), open interest 0."""
    stamp = local_time(bar["ts_close"], "America/Chicago")
    prices = ",".join(decimal_text(bar[price]) for price in ("open", "high", "low", "close"))
    return f"{stamp:%m/%d/%Y},{stamp.hour * 100 + stamp.minute},{prices},{bar['volume']},0"


def databento_csv_lines(bars: list[dict[str, int]], seed: int) -> list[str]:
    """The records of the Databento batch download, with the spread beside every hundredth
    bar, as a CSV export with pretty prices and timestamps and mapped symbols writes them."""
    symbols = {ES.instrument_id: DATABENTO_OUTRIGHT, DATABENTO_SPREAD[1]: DATABENTO_SPREAD[0]}
    records = databento_bars(bars, random.Random(f"{seed}/databento-batch"))
    lines = []
    for record in records:
        stamp = local_time(record.ts_event, "UTC").strftime("%Y-%m-%dT%H:%M:%S")
        nanoseconds = record.ts_event % NANOSECONDS_PER_SECOND
        prices = ",".join(
            decimal_text(getattr(record, price), decimals=9)
            for price in ("open", "high", "low", "close")
        )
        lines.append(
            f"{stamp}.{nanoseconds:09d}Z,{int(record.rtype)},{record.publisher_id},"
            f"{record.instrument_id},{prices},{record.volume},{symbols[record.instrument_id]}"
        )
    return lines


PRESET_SAMPLES = (
    ("ninjatrader", "ES 03-26.Last.txt", None, ninjatrader_line),
    ("tradingview", "CME_MINI_ESH2026, 1.csv", "time,open,high,low,close,Volume", tradingview_line),
    ("ibkr", "ESH2026-1min.csv", "date,open,high,low,close,volume,average,barCount", ibkr_line),
    (
        "sierra-chart",
        "ESH26-CME.txt",
        "Date, Time, Open, High, Low, Last, Volume, NumberOfTrades, BidVolume, AskVolume",
        sierra_chart_line,
    ),
    ("tradestation", "ESH26.txt", "Date,Time,Open,High,Low,Close,Vol,OI", tradestation_line),
)
"""Each preset's sample of the ES March bars: its folder, file name, header, and line."""
DATABENTO_CSV_SAMPLE = "glbx-mdp3-20260304-20260309.ohlcv-1m.csv"
DATABENTO_CSV_HEADER = "ts_event,rtype,publisher_id,instrument_id,open,high,low,close,volume,symbol"


def written_text(path: Path, lines: Sequence[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("".join(f"{line}\n" for line in lines).encode("utf-8"))
    return path


def written_preset_samples(out: Path, seed: int) -> list[dict[str, str | int]]:
    """Write each import preset's sample of ESH2026's 1-minute bars of all three sessions,
    across the start of US daylight saving, in the exact layout of its platform's export
    (docs/masterplan/appendix/research-data-sources.md, Part D), under `exports/<preset>/`, and
    return their entries."""
    month = f"month={month_of(ES)}"
    bars = pq.read_table(partition_path(out, "ohlcv-1m", ES, month)).to_pylist()
    folder = out / "exports"
    paths = [
        written_text(
            folder / preset / name,
            [*([header] if header else []), *(line(bar) for bar in bars)],
        )
        for preset, name, header, line in PRESET_SAMPLES
    ]
    databento = [DATABENTO_CSV_HEADER, *databento_csv_lines(bars, seed)]
    paths.append(written_text(folder / "databento-csv" / DATABENTO_CSV_SAMPLE, databento))
    return [manifest_entry(path, out, seed) for path in paths]


def write_manifest(out: Path, entries: Sequence[dict[str, str | int]]) -> None:
    ordered = sorted(entries, key=lambda entry: str(entry["path"]))
    text = json.dumps({"files": ordered}, indent=2, sort_keys=True) + "\n"
    (out / MANIFEST_NAME).write_text(text, encoding="utf-8", newline="\n")


def date_range(text: str) -> tuple[date, date]:
    """`2026-01-02..2026-12-31`: the first and the last date of a range, both included."""
    first, separator, last = text.partition("..")
    try:
        dates = (date.fromisoformat(first), date.fromisoformat(last))
    except ValueError:
        dates = None
    if not separator or dates is None or dates[1] < dates[0]:
        raise argparse.ArgumentTypeError(
            f"Expected a date range written FIRST..LAST, such as 2026-01-02..2026-12-31, got {text!r}"
        )
    return dates


def parse_arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate the synthetic market-data fixtures and their manifest."
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help="folder to write (default: fixtures/synthetic)",
    )
    parser.add_argument(
        "--seed", type=int, default=DEFAULT_SEED, help=f"base seed (default: {DEFAULT_SEED})"
    )
    parser.add_argument(
        "--dates",
        type=date_range,
        help="the sessions of a range instead of the fixtures' own, such as 2026-01-02..2026-12-31",
    )
    parser.add_argument(
        "--contracts",
        type=lambda text: tuple(text.split(",")),
        help=f"the contracts to write, of {', '.join(product.contract for product in PRODUCTS)}",
    )
    parser.add_argument(
        "--planted-gaps",
        type=int,
        default=0,
        help="quiet stretches and price jumps planted in each session (default: 0)",
    )
    arguments = parser.parse_args(argv)
    generated = arguments.dates is not None or arguments.contracts is not None
    if (generated or arguments.planted_gaps > 0) and arguments.out.resolve().is_relative_to(ROOT):
        parser.error(
            "Expected --out outside the repository with --dates, --contracts, or "
            f"--planted-gaps, whose tapes are never committed (D-51), got {arguments.out}"
        )
    return arguments


def chosen_products(arguments: argparse.Namespace) -> tuple[FixtureProduct, ...]:
    """The products the arguments name, each over the date range they give."""
    products = PRODUCTS
    if arguments.contracts is not None:
        known = {product.contract: product for product in PRODUCTS}
        unknown = sorted(set(arguments.contracts) - set(known))
        if unknown:
            raise SystemExit(f"Expected contracts among {sorted(known)}, got {unknown}.")
        products = tuple(known[contract] for contract in arguments.contracts)
    if arguments.dates is not None:
        products = tuple(in_date_range(product, *arguments.dates) for product in products)
    return products


def main(argv: Sequence[str]) -> int:
    arguments = parse_arguments(argv)
    products = chosen_products(arguments)
    entries = [
        entry
        for product in products
        for entry in written_product(product, arguments.out, arguments.seed, arguments.planted_gaps)
    ]
    one_product_a_root = {product.root: product for product in products}.values()
    entries.extend(
        written_dataset_metadata(product, schema, arguments.out, arguments.seed)
        for product in one_product_a_root
        for schema in ("trades", "ohlcv-1s", "ohlcv-1m")
    )
    if arguments.dates is None and arguments.contracts is None:
        entries.extend(written_funding(BTC, arguments.out, arguments.seed))
        entries.extend(written_databento_batch(arguments.out, arguments.seed))
        entries.extend(written_preset_samples(arguments.out, arguments.seed))
    write_manifest(arguments.out, entries)
    total_bytes = sum(int(entry["bytes"]) for entry in entries)
    print(
        f"Wrote {len(entries)} files ({total_bytes:,} bytes) and {MANIFEST_NAME} to {arguments.out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
