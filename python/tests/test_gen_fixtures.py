import hashlib
import itertools
import json
import re
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pyarrow.parquet as pq
import pytest

import gen_fixtures
from fefat.market.schema import parse_schema_name, polars_schema

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures" / "synthetic"
MANIFEST = FIXTURES / "MANIFEST.json"
NANOSECONDS_PER_SECOND = 1_000_000_000
NANOSECONDS_PER_MINUTE = 60 * NANOSECONDS_PER_SECOND
ES_TICK = 250_000_000
BTC_TICK = 100_000_000
FIXTURE_SIZE_LIMIT_BYTES = 20_000_000
# ES sessions run from 17:00 Chicago the day before their trade date to 16:00 Chicago on it:
# 23:00 to 22:00 UTC in standard time (UTC-6), 22:00 to 21:00 UTC once daylight saving starts
# on 2026-03-08 (UTC-5). Both ES contracts trade them (step 1.7). The BTC day runs from 00:00
# UTC to 00:00 UTC the next day.
ES_CONTRACTS = ("ESH2026", "ESM2026")
ES_SESSIONS = [
    ("2026-03-05", datetime(2026, 3, 4, 23, tzinfo=UTC), datetime(2026, 3, 5, 22, tzinfo=UTC)),
    ("2026-03-06", datetime(2026, 3, 5, 23, tzinfo=UTC), datetime(2026, 3, 6, 22, tzinfo=UTC)),
    ("2026-03-09", datetime(2026, 3, 8, 22, tzinfo=UTC), datetime(2026, 3, 9, 21, tzinfo=UTC)),
]
SESSIONS = [
    *(
        ("ES", contract, day, open_utc, close_utc)
        for contract in ES_CONTRACTS
        for day, open_utc, close_utc in ES_SESSIONS
    ),
    (
        "BTCUSDT-PERP",
        "BTCUSDT-PERP",
        "2026-03-07",
        datetime(2026, 3, 7, tzinfo=UTC),
        datetime(2026, 3, 8, tzinfo=UTC),
    ),
]
OPENS = [(root, contract, day, open_utc) for root, contract, day, open_utc, _ in SESSIONS]
BAR_FIELDS = ("ts_close", "open", "high", "low", "close", "volume", "trade_count", "vwap")
# Planted prints (step 1.5): one received exactly 90 minutes after each open, on a minute and a
# second boundary; one 50 ms before each close, in the session's last 100 ms slot; and one 400
# ms after the close of ES's Friday 2026-03-06, received in the break.
BOUNDARY_AFTER_OPEN = 90 * NANOSECONDS_PER_MINUTE
LAST_SLOT_BEFORE_CLOSE = 50_000_000
AFTER_THE_CLOSE = 400_000_000
AFTER_THE_CLOSE_DAY = "2026-03-06"


def nanoseconds(instant: datetime) -> int:
    return int(instant.timestamp()) * NANOSECONDS_PER_SECOND


def partition(schema: str, root: str, contract: str, key: str) -> Path:
    return FIXTURES / schema / f"root={root}" / f"contract={contract}" / key / "part.parquet"


def rows(path: Path) -> list[dict[str, int | str]]:
    return pq.read_table(path).to_pylist()


def second_bar(start: int, trades: list[dict[str, int | str]]) -> tuple[int, ...]:
    prices = [int(trade["price"]) for trade in trades]
    volume = sum(int(trade["size"]) for trade in trades)
    notional = sum(int(trade["price"]) * int(trade["size"]) for trade in trades)
    end = start + NANOSECONDS_PER_SECOND
    vwap = notional // volume
    return (end, prices[0], max(prices), min(prices), prices[-1], volume, len(trades), vwap)


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

    assert len(on_disk) == 33
    assert on_disk == listed


@pytest.mark.parametrize(
    ("sample", "header", "first_line"),
    [
        # semicolons, no header, yyyyMMdd HHmmss in UTC, stamped at the close
        ("ninjatrader/ES 03-26.Last.txt", None, r"20260304 230100;6850;6850;6849;6849;248"),
        # time,open,high,low,close,Volume with Unix seconds, stamped at the open
        (
            "tradingview/CME_MINI_ESH2026, 1.csv",
            "time,open,high,low,close,Volume",
            r"1772665200,6850,6850,6849,6849,248",
        ),
        # the TWS API's fields, yyyymmdd hh:mm:ss in New York with the zone's name
        (
            "ibkr/ESH2026-1min.csv",
            "date,open,high,low,close,volume,average,barCount",
            r"20260304 18:00:00 US/Eastern,6850,6850,6849,6849,248,[0-9.]+,[0-9]+",
        ),
        # a space after each comma, an unpadded date, hh:mm:ss in UTC, stamped at the open
        (
            "sierra-chart/ESH26-CME.txt",
            "Date, Time, Open, High, Low, Last, Volume, NumberOfTrades, BidVolume, AskVolume",
            r"2026/3/4, 23:00:00, 6850, 6850, 6849, 6849, 248, [0-9]+, 0, 0",
        ),
        # MM/DD/YYYY and the time as a number, in Chicago, stamped at the close
        (
            "tradestation/ESH26.txt",
            "Date,Time,Open,High,Low,Close,Vol,OI",
            r"03/04/2026,1701,6850,6850,6849,6849,248,0",
        ),
        # ts_event first in ISO 8601 with nanoseconds, nine decimals, the mapped symbol
        (
            "databento-csv/glbx-mdp3-20260304-20260309.ohlcv-1m.csv",
            "ts_event,rtype,publisher_id,instrument_id,open,high,low,close,volume,symbol",
            r"2026-03-04T23:00:00\.000000000Z,33,1,1001,6850\.000000000,6850\.000000000,"
            r"6849\.000000000,6849\.000000000,248,ESH6",
        ),
    ],
)
def test_each_preset_sample_has_the_layout_of_its_platforms_export(
    sample: str, header: str | None, first_line: str
) -> None:
    lines = (FIXTURES / "exports" / sample).read_bytes().decode("utf-8").split("\n")

    assert lines[-1] == ""
    assert lines[:1] == ([header] if header else lines[:1])
    assert re.fullmatch(first_line, lines[1] if header else lines[0])
    assert len(lines) - 1 - (header is not None) >= 4_141


def test_the_databento_batch_lists_each_files_size_and_sha256_as_the_vendor_does() -> None:
    folder = FIXTURES / "databento-batch" / gen_fixtures.DATABENTO_JOB
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    listed = {entry["filename"]: (entry["size"], entry["hash"]) for entry in manifest["files"]}

    assert manifest["job_id"] == gen_fixtures.DATABENTO_JOB
    assert listed == {
        path.name: (path.stat().st_size, f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}")
        for path in folder.iterdir()
        if path.name != "manifest.json"
    }


def test_the_fixtures_take_their_columns_from_the_sdk() -> None:
    for schema, written in (
        ("trades", gen_fixtures.TRADES_SCHEMA),
        ("ohlcv-1m", gen_fixtures.BARS_SCHEMA),
    ):
        assert written.names == polars_schema(parse_schema_name(schema)).names()


def test_a_date_range_writes_each_weekday_and_its_minutes_per_month(tmp_path: Path) -> None:
    arguments = ["--dates", "2026-02-27..2026-03-03", "--contracts", "ESH2026"]

    assert gen_fixtures.main(["--out", str(tmp_path), *arguments]) == 0

    written = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*.parquet"))
    contract = "root=ES/contract=ESH2026"
    weekdays = ["2026-02-27", "2026-03-02", "2026-03-03"]
    by_date = [
        f"{schema}/{contract}/date={day}/part.parquet"
        for schema in ("ohlcv-1s", "trades")
        for day in weekdays
    ]
    by_month = [
        f"ohlcv-1m/{contract}/month={month}/part.parquet" for month in ("2026-02", "2026-03")
    ]
    assert written == sorted([*by_date, *by_month])
    assert not (tmp_path / "databento-batch").exists()
    assert not (tmp_path / "exports").exists()


def test_planted_gaps_leave_quiet_minutes_and_jumps_in_each_session(tmp_path: Path) -> None:
    def session(gaps: int) -> list[dict[str, int | str]]:
        out = tmp_path / f"gaps-{gaps}"
        arguments = ["--dates", "2026-03-10..2026-03-10", "--contracts", "ESH2026"]
        assert gen_fixtures.main(["--out", str(out), *arguments, "--planted-gaps", str(gaps)]) == 0
        return rows(
            out / "trades" / "root=ES" / "contract=ESH2026" / "date=2026-03-10" / "part.parquet"
        )

    def longest_quiet(trades: list[dict[str, int | str]]) -> int:
        received = [int(trade["ts_recv"]) for trade in trades]
        return max(later - earlier for earlier, later in itertools.pairwise(received))

    def largest_move(trades: list[dict[str, int | str]]) -> int:
        prices = [int(trade["price"]) for trade in trades]
        return max(abs(later - earlier) for earlier, later in itertools.pairwise(prices))

    plain, gapped = session(0), session(3)

    assert largest_move(plain) == ES_TICK
    assert largest_move(gapped) >= 2 * ES_TICK
    assert longest_quiet(gapped) > max(longest_quiet(plain), NANOSECONDS_PER_MINUTE)
    assert len(gapped) < len(plain)
    assert [int(trade["sequence"]) for trade in gapped] == list(range(1, len(gapped) + 1))


def test_the_fixtures_stay_under_20_mb() -> None:
    total = sum(path.stat().st_size for path in FIXTURES.rglob("*") if path.is_file())

    assert total < FIXTURE_SIZE_LIMIT_BYTES


@pytest.mark.parametrize(
    ("trade_date", "open_utc", "close_utc"),
    [
        (
            date(2026, 3, 5),
            datetime(2026, 3, 4, 23, tzinfo=UTC),
            datetime(2026, 3, 5, 22, tzinfo=UTC),
        ),
        (
            date(2026, 3, 6),
            datetime(2026, 3, 5, 23, tzinfo=UTC),
            datetime(2026, 3, 6, 22, tzinfo=UTC),
        ),
        (
            date(2026, 3, 9),
            datetime(2026, 3, 8, 22, tzinfo=UTC),
            datetime(2026, 3, 9, 21, tzinfo=UTC),
        ),
    ],
)
def test_each_es_session_runs_from_17_00_to_16_00_chicago_across_the_clock_change(
    trade_date: date, open_utc: datetime, close_utc: datetime
) -> None:
    trades = rows(partition("trades", "ES", "ESH2026", f"date={trade_date.isoformat()}"))
    session = gen_fixtures.Session(gen_fixtures.ES, trade_date)
    open_time = nanoseconds(open_utc)
    close_time = nanoseconds(close_utc)
    after_the_close = [
        int(trade["ts_recv"]) for trade in trades if int(trade["ts_recv"]) >= close_time
    ]

    assert (session.open_time(), session.close_time()) == (open_time, close_time)
    assert trades[0]["side"] == "N"
    assert open_time <= int(trades[0]["ts_event"]) < open_time + NANOSECONDS_PER_SECOND
    planted = (
        [close_time + AFTER_THE_CLOSE] if trade_date.isoformat() == AFTER_THE_CLOSE_DAY else []
    )
    assert after_the_close == planted


@pytest.mark.parametrize(("root", "contract", "day", "open_utc", "close_utc"), SESSIONS)
def test_each_session_has_a_print_on_a_minute_boundary_and_one_in_its_last_slot(
    root: str, contract: str, day: str, open_utc: datetime, close_utc: datetime
) -> None:
    trades = rows(partition("trades", root, contract, f"date={day}"))
    received = [int(trade["ts_recv"]) for trade in trades]
    boundary = nanoseconds(open_utc) + BOUNDARY_AFTER_OPEN
    close_time = nanoseconds(close_utc)
    last_slot = [
        instant for instant in received if close_time - 100_000_000 <= instant < close_time
    ]

    assert boundary in received
    assert boundary % NANOSECONDS_PER_MINUTE == 0
    assert last_slot == [close_time - LAST_SLOT_BEFORE_CLOSE]
    assert [int(trade["sequence"]) for trade in trades] == list(range(1, len(trades) + 1))


def test_a_session_closes_at_its_local_close_time_on_the_day_the_clocks_change() -> None:
    # A product trading from 01:00 to 16:00 Chicago on 2026-03-08, when 02:00 CST becomes
    # 03:00 CDT: it opens at 01:00 CST (UTC-6), 07:00 UTC, and closes at 16:00 CDT (UTC-5),
    # 21:00 UTC, fourteen hours later. An open plus a fixed length cannot see the lost hour.
    product = replace(gen_fixtures.ES, opens_at=time(1), opens_on_previous_day=False)
    session = gen_fixtures.Session(product, date(2026, 3, 8))

    assert session.open_time() == nanoseconds(datetime(2026, 3, 8, 7, tzinfo=UTC))
    assert session.close_time() == nanoseconds(datetime(2026, 3, 8, 21, tzinfo=UTC))


def test_the_crypto_day_trades_around_the_clock_on_a_saturday() -> None:
    trades = rows(partition("trades", "BTCUSDT-PERP", "BTCUSDT-PERP", "date=2026-03-07"))
    day_start = nanoseconds(datetime(2026, 3, 7, tzinfo=UTC))
    day_end = nanoseconds(datetime(2026, 3, 8, tzinfo=UTC))
    hours = {
        (int(trade["ts_recv"]) - day_start) // (3600 * NANOSECONDS_PER_SECOND) for trade in trades
    }

    assert date(2026, 3, 7).weekday() == 5
    assert gen_fixtures.Session(gen_fixtures.BTC, date(2026, 3, 7)).close_time() == day_end
    assert day_start <= int(trades[0]["ts_recv"])
    assert int(trades[-1]["ts_recv"]) < day_end
    assert hours == set(range(24))


@pytest.mark.parametrize(("root", "tick"), [("ES", ES_TICK), ("BTCUSDT-PERP", BTC_TICK)])
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


@pytest.mark.parametrize(("root", "contract", "day", "open_utc"), OPENS)
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


@pytest.mark.parametrize(
    ("root", "contract"),
    [("ES", "ESH2026"), ("ES", "ESM2026"), ("BTCUSDT-PERP", "BTCUSDT-PERP")],
)
def test_minute_bars_carry_exactly_the_volume_of_their_trades(root: str, contract: str) -> None:
    bars = rows(partition("ohlcv-1m", root, contract, "month=2026-03"))
    trades_folder = FIXTURES / "trades" / f"root={root}" / f"contract={contract}"
    traded = sum(
        int(trade["size"]) for path in trades_folder.rglob("*.parquet") for trade in rows(path)
    )

    assert sum(int(bar["volume"]) for bar in bars) == traded
    assert all(int(bar["ts_close"]) - int(bar["ts_open"]) == NANOSECONDS_PER_MINUTE for bar in bars)
    assert all(int(bar["low"]) <= int(bar["open"]) <= int(bar["high"]) for bar in bars)
    assert all(int(bar["low"]) <= int(bar["close"]) <= int(bar["high"]) for bar in bars)
    assert all(int(bar["low"]) <= int(bar["vwap"]) <= int(bar["high"]) for bar in bars)


@pytest.mark.parametrize(("root", "contract", "day", "open_utc"), OPENS)
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

    assert minute_bars
    assert {bar["trade_date"] for bar in second_bars} == {trade_date}
    assert {bar["trade_date"] for bar in minute_bars} == {trade_date}
    assert bool(opened_the_evening_before) == (session_open < utc_midnight)


@pytest.mark.parametrize(
    ("root", "lot", "asset"), [("ES", "1", "contract"), ("BTCUSDT-PERP", "0.001", "BTC")]
)
@pytest.mark.parametrize("schema", ["trades", "ohlcv-1s", "ohlcv-1m"])
def test_each_dataset_states_its_size_unit_origin_and_licence_scope(
    schema: str, root: str, lot: str, asset: str
) -> None:
    metadata = FIXTURES / schema / f"root={root}" / "dataset.json"

    assert json.loads(metadata.read_text(encoding="utf-8")) == {
        "size_unit": {"lot": lot, "asset": asset},
        "origin": "import",
        "licence_scope": "Synthetic data of scripts/gen_fixtures.py; no licence applies",
    }


@pytest.mark.parametrize(("root", "contract", "day", "open_utc", "close_utc"), SESSIONS)
def test_every_bar_lies_inside_the_session_of_its_trade_date(
    root: str, contract: str, day: str, open_utc: datetime, close_utc: datetime
) -> None:
    session_open, session_close = nanoseconds(open_utc), nanoseconds(close_utc)
    bars = [
        bar
        for schema, key in (("ohlcv-1s", f"date={day}"), ("ohlcv-1m", "month=2026-03"))
        for bar in pq.read_table(partition(schema, root, contract, key)).to_pylist()
        if bar["trade_date"] == date.fromisoformat(day)
    ]
    outside = [
        (bar["ts_open"], bar["ts_close"] - bar["ts_open"])
        for bar in bars
        if not session_open <= bar["ts_open"] < bar["ts_close"] <= session_close
    ]

    # The print ESH2026 received after the close of 2026-03-06 keeps that trade date, in a
    # 1-second and a 1-minute bar opening at the close, as the vendor's bars do.
    opening_at_the_close = [
        (session_close, NANOSECONDS_PER_SECOND),
        (session_close, NANOSECONDS_PER_MINUTE),
    ]
    planted_after_the_close = (contract, day) == ("ESH2026", AFTER_THE_CLOSE_DAY)
    assert bars
    assert outside == (opening_at_the_close if planted_after_the_close else [])


def test_the_june_contract_trades_more_than_march_on_03_06_only() -> None:
    # Step 1.7's roll: ESM2026's volume crosses ESH2026's on 2026-03-06 and falls back below it
    # on 2026-03-09, so a volume rule rolls at the open of 03-09 and must not roll back after.
    def volume(contract: str, day: str) -> int:
        trades = rows(partition("trades", "ES", contract, f"date={day}"))
        return sum(int(trade["size"]) for trade in trades)

    june_leads = [volume("ESM2026", day) > volume("ESH2026", day) for day, _, _ in ES_SESSIONS]

    assert june_leads == [False, True, False]


def test_the_two_es_contracts_draw_different_tapes() -> None:
    # Each tape is seeded by its contract, not its root, so ESM2026 is no rescaled copy of
    # ESH2026: their prints arrive at other instants from the open on.
    def received(contract: str) -> list[int]:
        trades = rows(partition("trades", "ES", contract, "date=2026-03-05"))
        return [int(trade["ts_recv"]) for trade in trades[:50]]

    assert set(received("ESH2026")).isdisjoint(received("ESM2026"))


@pytest.mark.parametrize(
    ("nano", "decimals", "text"),
    [
        (-45_250_000_000, 9, "-45.250000000"),
        (-500_000_000, None, "-0.5"),
        (6_849_750_000_000, None, "6849.75"),
    ],
)
def test_a_price_is_written_as_its_decimal_with_its_sign(
    nano: int, decimals: int | None, text: str
) -> None:
    assert gen_fixtures.decimal_text(nano, decimals) == text
