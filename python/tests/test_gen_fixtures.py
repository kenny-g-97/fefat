import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pyarrow.parquet as pq
import pytest

import gen_fixtures

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures" / "synthetic"
MANIFEST = FIXTURES / "MANIFEST.json"
NANOSECONDS_PER_SECOND = 1_000_000_000
NANOSECONDS_PER_MINUTE = 60 * NANOSECONDS_PER_SECOND
ES_TICK = 250_000_000
BTC_TICK = 100_000_000
ES_SESSION_LENGTH = timedelta(hours=23)
FIXTURE_SIZE_LIMIT_BYTES = 20_000_000
SESSIONS = [
    ("ES", "ESH6", "2026-03-05", datetime(2026, 3, 4, 23, tzinfo=UTC)),
    ("ES", "ESH6", "2026-03-06", datetime(2026, 3, 5, 23, tzinfo=UTC)),
    ("ES", "ESH6", "2026-03-09", datetime(2026, 3, 8, 22, tzinfo=UTC)),
    ("BTC", "BTCUSDT-PERP", "2026-03-07", datetime(2026, 3, 7, tzinfo=UTC)),
]
BAR_FIELDS = ("ts_close", "open", "high", "low", "close", "volume", "trade_count")


def nanoseconds(instant: datetime) -> int:
    return int(instant.timestamp()) * NANOSECONDS_PER_SECOND


def partition(schema: str, root: str, contract: str, key: str) -> Path:
    return FIXTURES / schema / f"root={root}" / f"contract={contract}" / key / "part.parquet"


def rows(path: Path) -> list[dict[str, int | str]]:
    return pq.read_table(path).to_pylist()


def second_bar(start: int, trades: list[dict[str, int | str]]) -> tuple[int, ...]:
    prices = [int(trade["price"]) for trade in trades]
    volume = sum(int(trade["size"]) for trade in trades)
    end = start + NANOSECONDS_PER_SECOND
    return (end, prices[0], max(prices), min(prices), prices[-1], volume, len(trades))


def manifest_entries() -> list[dict[str, str | int]]:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["files"]


@pytest.fixture(scope="module")
def regenerated(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("regenerated")
    assert gen_fixtures.main(["--out", str(folder)]) == 0
    return folder


def test_running_the_generator_twice_gives_identical_manifest_hashes(
    regenerated: Path, tmp_path: Path
) -> None:
    assert gen_fixtures.main(["--out", str(tmp_path)]) == 0

    first = (regenerated / "MANIFEST.json").read_text(encoding="utf-8")
    second = (tmp_path / "MANIFEST.json").read_text(encoding="utf-8")
    assert '"sha256"' in first
    assert second == first


def test_the_committed_fixtures_are_what_the_generator_writes(regenerated: Path) -> None:
    fresh = (regenerated / "MANIFEST.json").read_text(encoding="utf-8")

    assert MANIFEST.read_text(encoding="utf-8") == fresh


def test_every_committed_fixture_file_is_listed_with_its_hash() -> None:
    listed = {entry["path"]: entry["sha256"] for entry in manifest_entries()}
    on_disk = {
        path.relative_to(FIXTURES).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in FIXTURES.rglob("*")
        if path.is_file() and path != MANIFEST
    }

    assert len(on_disk) == 16
    assert on_disk == listed


def test_the_fixtures_stay_under_20_mb() -> None:
    total = sum(path.stat().st_size for path in FIXTURES.rglob("*") if path.is_file())

    assert total < FIXTURE_SIZE_LIMIT_BYTES


@pytest.mark.parametrize(
    ("trade_date", "open_utc"),
    [
        (date(2026, 3, 5), datetime(2026, 3, 4, 23, tzinfo=UTC)),
        (date(2026, 3, 6), datetime(2026, 3, 5, 23, tzinfo=UTC)),
        (date(2026, 3, 9), datetime(2026, 3, 8, 22, tzinfo=UTC)),
    ],
)
def test_each_es_session_runs_from_17_00_to_16_00_chicago_across_the_clock_change(
    trade_date: date, open_utc: datetime
) -> None:
    trades = rows(partition("trades", "ES", "ESH6", f"date={trade_date.isoformat()}"))
    open_time = nanoseconds(open_utc)
    close_time = nanoseconds(open_utc + ES_SESSION_LENGTH)

    assert trades[0]["side"] == "N"
    assert open_time <= int(trades[0]["ts_event"]) < open_time + NANOSECONDS_PER_SECOND
    assert int(trades[-1]["ts_recv"]) < close_time


def test_the_crypto_day_trades_around_the_clock_on_a_saturday() -> None:
    trades = rows(partition("trades", "BTC", "BTCUSDT-PERP", "date=2026-03-07"))
    day_start = nanoseconds(datetime(2026, 3, 7, tzinfo=UTC))
    day_end = nanoseconds(datetime(2026, 3, 8, tzinfo=UTC))
    hours = {
        (int(trade["ts_recv"]) - day_start) // (3600 * NANOSECONDS_PER_SECOND) for trade in trades
    }

    assert date(2026, 3, 7).weekday() == 5
    assert day_start <= int(trades[0]["ts_recv"])
    assert int(trades[-1]["ts_recv"]) < day_end
    assert hours == set(range(24))


@pytest.mark.parametrize(("root", "tick"), [("ES", ES_TICK), ("BTC", BTC_TICK)])
def test_trade_prices_sit_on_the_tick_grid(root: str, tick: int) -> None:
    paths = sorted((FIXTURES / "trades" / f"root={root}").rglob("*.parquet"))
    prices = [int(trade["price"]) for path in paths for trade in rows(path)]

    assert paths
    assert [price for price in prices if price % tick != 0] == []


def test_ts_recv_never_decreases_and_never_precedes_ts_event() -> None:
    for path in sorted((FIXTURES / "trades").rglob("*.parquet")):
        trades = rows(path)
        received = [int(trade["ts_recv"]) for trade in trades]

        assert received == sorted(received), path
        assert all(int(trade["ts_recv"]) >= int(trade["ts_event"]) for trade in trades), path


@pytest.mark.parametrize(("root", "contract", "day", "open_utc"), SESSIONS)
def test_second_bars_hold_the_trades_received_in_their_second(
    root: str, contract: str, day: str, open_utc: datetime
) -> None:
    open_time = nanoseconds(open_utc)

    def second_of(instant: int | str) -> int:
        return int(instant) - (int(instant) - open_time) % NANOSECONDS_PER_SECOND

    trades = rows(partition("trades", root, contract, f"date={day}"))
    received: dict[int, list[dict[str, int | str]]] = {}
    for trade in trades:
        received.setdefault(second_of(trade["ts_recv"]), []).append(trade)
    bars = rows(partition("ohlcv-1s", root, contract, f"date={day}"))

    assert {int(bar["ts_open"]): tuple(int(bar[name]) for name in BAR_FIELDS) for bar in bars} == {
        start: second_bar(start, group) for start, group in received.items()
    }
    # The fixture tells the clocks apart, so bars bucketed by ts_event would fail the line above.
    assert any(second_of(trade["ts_event"]) != second_of(trade["ts_recv"]) for trade in trades)


@pytest.mark.parametrize(("root", "contract"), [("ES", "ESH6"), ("BTC", "BTCUSDT-PERP")])
def test_minute_bars_carry_exactly_the_volume_of_their_trades(root: str, contract: str) -> None:
    bars = rows(partition("ohlcv-1m", root, contract, "month=2026-03"))
    trades_folder = FIXTURES / "trades" / f"root={root}"
    traded = sum(
        int(trade["size"]) for path in trades_folder.rglob("*.parquet") for trade in rows(path)
    )

    assert sum(int(bar["volume"]) for bar in bars) == traded
    assert all(int(bar["ts_close"]) - int(bar["ts_open"]) == NANOSECONDS_PER_MINUTE for bar in bars)
    assert all(int(bar["low"]) <= int(bar["open"]) <= int(bar["high"]) for bar in bars)
    assert all(int(bar["low"]) <= int(bar["close"]) <= int(bar["high"]) for bar in bars)


@pytest.mark.parametrize(("root", "contract", "day", "open_utc"), SESSIONS)
def test_bars_carry_the_session_trade_date_not_the_utc_date_of_ts_open(
    root: str, contract: str, day: str, open_utc: datetime
) -> None:
    trade_date = date.fromisoformat(day)
    session_open = nanoseconds(open_utc)
    next_session_open = nanoseconds(open_utc + timedelta(days=1))
    utc_midnight = nanoseconds(datetime.combine(trade_date, time(), tzinfo=UTC))
    second_bars = pq.read_table(partition("ohlcv-1s", root, contract, f"date={day}")).to_pylist()
    minute_bars = [
        bar
        for bar in pq.read_table(partition("ohlcv-1m", root, contract, "month=2026-03")).to_pylist()
        if session_open <= bar["ts_open"] < next_session_open
    ]
    opened_the_evening_before = [bar for bar in second_bars if bar["ts_open"] < utc_midnight]

    assert {bar["trade_date"] for bar in second_bars} == {trade_date}
    assert {bar["trade_date"] for bar in minute_bars} == {trade_date}
    assert bool(opened_the_evening_before) == (session_open < utc_midnight)


@pytest.mark.parametrize(
    ("root", "lot", "asset"), [("ES", "1", "contract"), ("BTC", "0.001", "BTC")]
)
@pytest.mark.parametrize("schema", ["trades", "ohlcv-1s", "ohlcv-1m"])
def test_each_dataset_states_the_unit_of_its_sizes_and_volumes(
    schema: str, root: str, lot: str, asset: str
) -> None:
    metadata = FIXTURES / schema / f"root={root}" / "dataset.json"

    assert json.loads(metadata.read_text(encoding="utf-8")) == {
        "size_unit": {"lot": lot, "asset": asset}
    }


@pytest.mark.parametrize(("root", "contract", "day", "open_utc"), SESSIONS)
def test_every_bar_lies_inside_the_session_of_its_trade_date(
    root: str, contract: str, day: str, open_utc: datetime
) -> None:
    length = timedelta(days=1) if root == "BTC" else ES_SESSION_LENGTH
    session_open, session_close = nanoseconds(open_utc), nanoseconds(open_utc + length)
    bars = [
        bar
        for schema, key in (("ohlcv-1s", f"date={day}"), ("ohlcv-1m", "month=2026-03"))
        for bar in pq.read_table(partition(schema, root, contract, key)).to_pylist()
        if bar["trade_date"] == date.fromisoformat(day)
    ]

    assert bars
    assert all(session_open <= bar["ts_open"] < bar["ts_close"] <= session_close for bar in bars)
