"""Generate the synthetic market data under fixtures/synthetic/, the only data files in git.

Run it in the project environment, since it writes Parquet through pyarrow:

    uv run python scripts/gen_fixtures.py
    uv run python scripts/gen_fixtures.py --out <folder> --seed <number>

The files follow the canonical store of docs/masterplan/02-engine-and-data.md
section 1.1, with this folder as the provider `synthetic`: Parquet with zstd,
prices as int64 in 1e-9 units, timestamps as int64 nanoseconds UTC, laid out as
`<schema>/root=…/contract=…/date=…/part.parquet` (1-minute bars per month as
`month=…`). They hold three CME-like ES sessions across the start of US
daylight saving on 2026-03-08 (the UTC open moves from 23:00 to 22:00), a 24x7
BTC perpetual-like UTC day, and the 1-second and 1-minute bars built from their
trades the way section 1.4 builds bars: bucketed by `ts_recv` into
`[t, t + width)` from the session open, sparse, with `ts_open`, `ts_close`,
and the session's `trade_date` (the first hour of an ES session falls on the UTC
day before its trade date). A session opens and closes at local times of its
product's time zone, as the calendar of `fefat.market.calendar` does: ES from
17:00 Chicago the day before its trade date to 16:00 Chicago on it, BTC from
00:00 UTC to 00:00 UTC the next day. The labels follow the SDK: the ES contract
is `ESH2026` (root, month code, four-digit year, `fefat.market.contracts`) and
the BTC root is the instrument key `BTCUSDT-PERP` (`fefat.market.instruments`).

Trades carry `ts_recv`, `ts_event`, `instrument_id`, `price`, `size` (contracts
for ES, lots of 0.001 BTC for BTC), `side` (the aggressor: `B` buys, `A` sells,
`N` for the opening print), and `sequence`. Each dataset folder
`<schema>/root=…/` holds a `dataset.json` with the unit of its sizes and volumes
(`size_unit`: one unit is `lot` of `asset`). MANIFEST.json lists every file with
the generator, the seed, its size, and its SHA-256, and each Parquet file's row
count. Each session draws from its own
`random.Random`, seeded with "<seed>/<root>/<trade date>". Times and durations
here are integer nanoseconds; instants count from the Unix epoch in UTC.

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
import hashlib
import json
import random
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from itertools import groupby
from pathlib import Path
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "fixtures" / "synthetic"
DEFAULT_SEED = 20260308
GENERATOR = "scripts/gen_fixtures.py"
MANIFEST_NAME = "MANIFEST.json"
DATASET_METADATA_NAME = "dataset.json"

NANOSECONDS_PER_SECOND = 1_000_000_000
NANOSECONDS_PER_MINUTE = 60 * NANOSECONDS_PER_SECOND
SLOT_LENGTH = 100_000_000
QUIET_BEFORE_CLOSE = NANOSECONDS_PER_SECOND
OPENING_PRINT_DELAY = (1_000_000, 50_000_000)
OPENING_PRINT_SIZE = (50, 400)
RECEIVE_LATENCY = (20_000, 400_000)
WEEKEND_GAP_FACTOR = 3
SUNDAY = 6

BUYER = "B"
SELLER = "A"
NO_AGGRESSOR = "N"
UPTICK_BELOW = 0.15
DOWNTICK_BELOW = 0.30
PRINTS_PER_EVENT = ((1, 0.75), (2, 0.90), (3, 0.97), (4, 1.0))

TRADES_SCHEMA = pa.schema(
    [
        ("ts_recv", pa.int64()),
        ("ts_event", pa.int64()),
        ("instrument_id", pa.uint32()),
        ("price", pa.int64()),
        ("size", pa.uint32()),
        ("side", pa.string()),
        ("sequence", pa.uint32()),
    ]
)
BARS_SCHEMA = pa.schema(
    [
        ("ts_open", pa.int64()),
        ("ts_close", pa.int64()),
        ("trade_date", pa.date32()),
        ("instrument_id", pa.uint32()),
        ("open", pa.int64()),
        ("high", pa.int64()),
        ("low", pa.int64()),
        ("close", pa.int64()),
        ("volume", pa.uint64()),
        ("trade_count", pa.uint32()),
    ]
)


@dataclass(frozen=True)
class ActivityWindow:
    """A stretch of the session, in minutes after the open, with the chance of a trade per slot."""

    start_minute: int
    end_minute: int
    trade_chance: float


@dataclass(frozen=True)
class FixtureProduct:
    """An instrument in the fixture set: its specification, its trading day, and its sessions."""

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
)
PRODUCTS = (ES, BTC)


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
        for window in self.product.activity:
            window_start = self.open_time() + window.start_minute * NANOSECONDS_PER_MINUTE
            window_end = self.open_time() + window.end_minute * NANOSECONDS_PER_MINUTE
            for slot_start in range(
                max(window_start, first_slot), min(window_end, last_slot), SLOT_LENGTH
            ):
                yield slot_start, window.trade_chance


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
            "volume": sum(sizes[row] for row in members),
            "trade_count": len(members),
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
    """Write a dataset's `dataset.json`, the unit of its sizes and volumes, and return its entry."""
    path = out / schema / f"root={product.root}" / DATASET_METADATA_NAME
    metadata = {"size_unit": {"lot": product.size_lot, "asset": product.size_asset}}
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


def written_product(product: FixtureProduct, out: Path, seed: int) -> list[dict[str, str | int]]:
    """Write a product's trades and 1-second bars per trade date, its 1-minute bars per month,
    and the `dataset.json` of each of its datasets."""
    entries: list[dict[str, str | int]] = []
    minute_bars: list[pa.Table] = []
    price_ticks = product.first_price_ticks
    for trade_date in product.trade_dates:
        session = Session(product, trade_date)
        random_source = random.Random(f"{seed}/{product.root}/{trade_date.isoformat()}")
        trades, price_ticks = simulate_session(
            session, random_source, opening_price_ticks(price_ticks, session, random_source)
        )
        day = f"date={trade_date.isoformat()}"
        second_bars = bars_from_trades(trades, session, NANOSECONDS_PER_SECOND)
        entries.append(
            written_partition(trades, partition_path(out, "trades", product, day), out, seed)
        )
        entries.append(
            written_partition(second_bars, partition_path(out, "ohlcv-1s", product, day), out, seed)
        )
        minute_bars.append(bars_from_trades(trades, session, NANOSECONDS_PER_MINUTE))
    month = f"month={month_of(product)}"
    month_path = partition_path(out, "ohlcv-1m", product, month)
    entries.append(written_partition(pa.concat_tables(minute_bars), month_path, out, seed))
    entries.extend(
        written_dataset_metadata(product, schema, out, seed)
        for schema in ("trades", "ohlcv-1s", "ohlcv-1m")
    )
    return entries


def write_manifest(out: Path, entries: Sequence[dict[str, str | int]]) -> None:
    ordered = sorted(entries, key=lambda entry: str(entry["path"]))
    text = json.dumps({"files": ordered}, indent=2, sort_keys=True) + "\n"
    (out / MANIFEST_NAME).write_text(text, encoding="utf-8", newline="\n")


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
    return parser.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    arguments = parse_arguments(argv)
    entries = [
        entry
        for product in PRODUCTS
        for entry in written_product(product, arguments.out, arguments.seed)
    ]
    write_manifest(arguments.out, entries)
    total_bytes = sum(int(entry["bytes"]) for entry in entries)
    print(
        f"Wrote {len(entries)} files ({total_bytes:,} bytes) and {MANIFEST_NAME} to {arguments.out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
