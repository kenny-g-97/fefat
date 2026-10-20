"""The export samples of `scripts/gen_fixtures.py` and what the file importer's tests share
(step 1.10): each preset's sample with the time zone its import names, the fixtures' ESH2026
bars as each sample gives them, and exports written in a test's temporary folder, such as a new
product's 5-minute bars."""

from datetime import date, time
from decimal import Decimal
from pathlib import Path

import polars as pl

from fefat.market.bars import resample_bars
from fefat.market.builtin_calendars import BUILT_IN
from fefat.market.calendar import sessions_of
from fefat.market.calendar_definition import CalendarId, SessionHours, Weekday
from fefat.market.importers.file_import import FileImportRequest, import_file
from fefat.market.importers.profiles import ImportProfile, NewInstrument, preset_profiles
from fefat.market.instruments import Currency, InstrumentKind
from fefat.market.last_trade_rules import ThirdFriday
from fefat.market.layout import Dataset, Partition, YearMonth
from fefat.market.saved_instruments import instrument_table
from fefat.market.schema import Timeframe, TimeUnit, parse_schema_name
from fefat.market.store import Store

ROOT = Path(__file__).resolve().parents[2]
SYNTHETIC = ROOT / "fixtures" / "synthetic"
EXPORTS = SYNTHETIC / "exports"
ESH2026_MINUTES = (
    SYNTHETIC / "ohlcv-1m" / "root=ES" / "contract=ESH2026" / "month=2026-03" / "part.parquet"
)
ESH2026_MARCH_6_TRADES = (
    SYNTHETIC / "trades" / "root=ES" / "contract=ESH2026" / "date=2026-03-06" / "part.parquet"
)
IMPORTED_ON = date(2026, 10, 20)
HOUR = 3_600_000_000_000
MINUTE = 60_000_000_000
PRESETS = preset_profiles()
SAMPLES = {
    "ninjatrader": (EXPORTS / "ninjatrader" / "ES 03-26.Last.txt", None),
    "tradingview": (EXPORTS / "tradingview" / "CME_MINI_ESH2026, 1.csv", None),
    "databento-csv": (
        EXPORTS / "databento-csv" / "glbx-mdp3-20260304-20260309.ohlcv-1m.csv",
        None,
    ),
    "ibkr": (EXPORTS / "ibkr" / "ESH2026-1min.csv", "America/New_York"),
    "sierra-chart": (EXPORTS / "sierra-chart" / "ESH26-CME.txt", None),
    "tradestation": (EXPORTS / "tradestation" / "ESH26.txt", "America/Chicago"),
}
"""Each preset's sample of the fixtures' ESH2026 1-minute bars, and the time zone the import
names where the preset leaves it to the import."""


def sample_request(preset: str, **changes: object) -> FileImportRequest:
    path, time_zone = SAMPLES[preset]
    request = FileImportRequest(path=path, profile=PRESETS[preset], time_zone=time_zone)
    return FileImportRequest(**{**request.__dict__, **changes})


def sample_lines(preset: str) -> list[str]:
    """The lines of a preset's sample, without their line ends."""
    return SAMPLES[preset][0].read_bytes().decode().splitlines()


def written_export(folder: Path, name: str, lines: list[str]) -> Path:
    """`lines` written as the export `name` in `folder`, each ended by a line feed."""
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("".join(f"{line}\n" for line in lines).encode())
    return path


def imported(folder: Path, request: FileImportRequest) -> Store:
    store = Store(folder / "data")
    import_file(
        request,
        store,
        folder / "cache",
        imported_on=IMPORTED_ON,
        instruments=instrument_table(store.folder),
    )
    return store


def minutes_of(provider: str) -> Partition:
    dataset = Dataset(provider=provider, schema_name=parse_schema_name("ohlcv-1m"), root="ES")
    return Partition(dataset=dataset, contract="ESH2026", key=YearMonth(year=2026, month=3))


def expected_minutes(preset: str) -> pl.DataFrame:
    """The fixtures' ESH2026 1-minute bars as the preset's sample gives them: the vendor's
    instrument id from Databento's file, else the contract's, and the trade count and vwap
    only where the layout carries them."""
    bars = pl.read_parquet(ESH2026_MINUTES)
    instrument_id = 1001 if preset == "databento-csv" else 202603
    keeps_count = preset in ("ibkr", "sierra-chart")
    return bars.with_columns(
        instrument_id=pl.lit(instrument_id, dtype=pl.UInt32),
        trade_count=pl.col("trade_count") if keeps_count else pl.lit(None, dtype=pl.UInt32),
        vwap=pl.col("vwap") if preset == "ibkr" else pl.lit(None, dtype=pl.Int64),
    )


def store_files(folder: Path) -> dict[str, tuple[int, int]]:
    return {
        path.relative_to(folder).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in folder.rglob("*")
        if path.is_file()
    }


XES_HOURS = SessionHours(
    time_zone="America/Chicago",
    opens_at=time(17, 0),
    closes_at=time(16, 0),
    opens_on_previous_day=True,
    weekdays=frozenset(
        {Weekday.MONDAY, Weekday.TUESDAY, Weekday.WEDNESDAY, Weekday.THURSDAY, Weekday.FRIDAY}
    ),
)
XES = NewInstrument(
    root="XES",
    kind=InstrumentKind.FUTURES,
    tick_size=Decimal("0.25"),
    point_value=Decimal(50),
    currency=Currency.USD,
    last_trade_rule=ThirdFriday(),
    calendar=XES_HOURS,
    first_trade_date=date(2026, 3, 2),
)
"""XES, a product FEFAT does not know, on hours of its own: 17:00 to 16:00 Chicago, Monday to
Friday, without holidays."""


def a_new_product_profile(instrument: NewInstrument = XES) -> ImportProfile:
    """A TradingView export of 5-minute bars of a product FEFAT does not know, XES by default."""
    return PRESETS["tradingview"].model_copy(
        update={
            "name": "xes-5m",
            "timeframe": Timeframe(count=5, unit=TimeUnit.MINUTE),
            "instrument": instrument,
        }
    )


def five_minute_file(folder: Path) -> Path:
    """The fixtures' ESH2026 bars resampled to 5 minutes by the bar builder, written as
    TradingView writes a 5-minute chart of XES March 2026."""
    sessions = sessions_of(BUILT_IN[CalendarId.CME_EQUITY_INDEX], folder / "cache")
    minutes = pl.read_parquet(ESH2026_MINUTES)
    five = resample_bars(minutes, Timeframe(count=5, unit=TimeUnit.MINUTE), sessions, 2**62)
    rows = [
        f"{bar['ts_open'] // 1_000_000_000},{bar['open'] / 1e9},{bar['high'] / 1e9},"
        f"{bar['low'] / 1e9},{bar['close'] / 1e9},{bar['volume']}"
        for bar in five.iter_rows(named=True)
    ]
    return written_export(
        folder / "exports", "XESH2026, 5.csv", ["time,open,high,low,close,Volume", *rows]
    )


def rolled_databento_lines() -> list[str]:
    """The Databento sample's ESH6 rows, those from 2026-03-08 on under another instrument id,
    as a vendor's continuous series gives across a roll."""
    header, *rows = sample_lines("databento-csv")
    outrights = [row.split(",") for row in rows if row.endswith(",ESH6")]
    rolled = [
        [*fields[:3], "1002" if fields[0] >= "2026-03-08" else fields[3], *fields[4:]]
        for fields in outrights
    ]
    return [header, *(",".join(fields) for fields in rolled)]
