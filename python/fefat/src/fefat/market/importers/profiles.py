"""Import profiles of kind `market_data` (step 1.10, `02-engine-and-data.md` §1.8): a saved
description of a file layout that `fefat data import file` reads bar and tick files with.

A profile names the file's delimiter and header row, the columns that hold the timestamp (one
column, or a date and a time), the bar's open, high, low, close, and volume or the tick's price,
size, and side, the timestamps' format and time zone, whether a bar's timestamp marks its open
or its close, the prices' unit and scale, the unit a volume counts, the timeframe (ticks, or
bars of any timeframe), the series (dated contracts, or one continuous series, unadjusted or
back-adjusted), how the file names its contract, and the instrument: one FEFAT knows, or a new
specification entered once, which the first import saves (`fefat.market.saved_instruments`).
Its provider is the folder its datasets are stored under.

The presets for common exports ship as `presets/<id>.yaml` beside this module, each an entry of
the source guide (`fefat.market.sources`), and a trader's own profiles are YAML files in the
same form, saved under `<FEFAT_HOME>/profiles/` by their first import:

    load_profile("ninjatrader", paths.home)
    load_profile("C:/exports/fdax-5m.yaml", paths.home)  # saved as fdax-5m for later imports
"""

from datetime import date
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self

import yaml
from pydantic import BeforeValidator, Field, PlainSerializer, StringConstraints, model_validator

from fefat.market.calendar_definition import CalendarId, SessionHours, TimeZoneName
from fefat.market.instruments import Currency, InstrumentKind
from fefat.market.last_trade_rules import LastTradeRule
from fefat.market.layout import FolderName, ProviderName, SeriesKind, SizeUnit
from fefat.market.schema import FrozenModel, Timeframe
from fefat.market.store import write_atomically

PRESETS_FOLDER = Path(__file__).with_name("presets")
PROFILES_FOLDER_NAME = "profiles"
"""The folder of a trader's saved profiles, inside `FEFAT_HOME`."""
TICKS = "ticks"


class ProfileKind(StrEnum):
    """What a profile imports: market data here; trade logs arrive in Phase 7."""

    MARKET_DATA = "market_data"


class BarStamp(StrEnum):
    """Which end of a bar its timestamp marks."""

    OPEN = "open"
    CLOSE = "close"


class TimestampForm(StrEnum):
    """A timestamp written as a number since the Unix epoch, as ISO 8601 text with an offset
    or none, or as Databento writes one, ISO 8601 or integer nanoseconds."""

    UNIX_SECONDS = "unix_s"
    UNIX_MILLISECONDS = "unix_ms"
    UNIX_MICROSECONDS = "unix_us"
    UNIX_NANOSECONDS = "unix_ns"
    ISO = "iso"
    DATABENTO = "databento"


StrptimePattern = Annotated[str, StringConstraints(pattern=r"%")]
"""A strptime pattern such as `%Y%m%d %H%M%S`, as Polars reads it."""


class PriceUnit(StrEnum):
    """How a file writes a price: as a decimal, as an integer count of 1e-9 units, or as
    Databento writes one, either, the same throughout a file."""

    DECIMAL = "decimal"
    NANO_INTEGER = "nano_integer"
    DATABENTO = "databento"


ColumnName = str | int
"""A column by its header name, or by its position counting from 0 in a file without one."""


class FileLayout(FrozenModel):
    """The file's delimiter, one character (a tab for TSV), and whether a header row names its
    columns."""

    delimiter: str = Field(min_length=1, max_length=1)
    header: bool


class BarColumns(FrozenModel):
    """A bar's prices and volume, and, where the file has them, its trade count and its
    volume-weighted average price (null in the store without them)."""

    open: ColumnName
    high: ColumnName
    low: ColumnName
    close: ColumnName
    volume: ColumnName
    trade_count: ColumnName | None = None
    vwap: ColumnName | None = None


class TickColumns(FrozenModel):
    """A tick's price and size, its aggressor side (`A`, `B`, or `N`; `N` without a column),
    the event time where it differs from the timestamp, which is the receive time, and its
    sequence (the row's order without a column)."""

    price: ColumnName
    size: ColumnName
    side: ColumnName | None = None
    event_time: ColumnName | None = None
    sequence: ColumnName | None = None


class ColumnMapping(FrozenModel):
    """Which columns hold what: the timestamp in one column, or a date and a time joined with a
    space; the bars' or the ticks' values; and, where the file has them, each record's
    instrument id and contract symbol."""

    timestamp: ColumnName | None = None
    date: ColumnName | None = None
    time: ColumnName | None = None
    bars: BarColumns | None = None
    ticks: TickColumns | None = None
    instrument_id: ColumnName | None = None
    symbol: ColumnName | None = None

    @model_validator(mode="after")
    def _one_timestamp(self) -> Self:
        if (self.timestamp is None) == (self.date is None):
            raise ValueError(
                "Expected the timestamp in one column (timestamp) or in a date column (date, "
                f"with an optional time), got timestamp {self.timestamp!r} and date {self.date!r}."
            )
        if self.time is not None and self.date is None:
            raise ValueError(f"Expected a date column beside the time column {self.time!r}.")
        return self


class TimestampRule(FrozenModel):
    """How a timestamp is written: its format, its time zone (null where each import names it,
    since the file's zone is the trader's, such as the TWS login's), and the bar end it marks."""

    format: TimestampForm | StrptimePattern
    time_zone: TimeZoneName | None
    stamp: BarStamp = BarStamp.OPEN


class PriceRule(FrozenModel):
    """How a price is written, and what multiplies it into the instrument's price, such as
    0.0001 for prices stored times 10,000."""

    unit: PriceUnit = PriceUnit.DECIMAL
    scale: Decimal = Field(default=Decimal(1), gt=0)


class NewInstrument(FrozenModel):
    """The specification of a product FEFAT does not know, entered once: `calendar` is a
    built-in calendar's id or the hours of a calendar of its own without holidays, and
    `first_trade_date` the day it began trading, before which no record is imported."""

    root: FolderName
    kind: InstrumentKind
    tick_size: Decimal = Field(gt=0)
    point_value: Decimal = Field(gt=0)
    lot_step: Decimal = Field(default=Decimal(1), gt=0)
    currency: Currency
    last_trade_rule: LastTradeRule | None = None
    calendar: CalendarId | SessionHours
    first_trade_date: date


def _parsed_timeframe(value: object) -> object:
    if value == TICKS or not isinstance(value, str):
        return value
    return Timeframe.parse(value)


ProfileTimeframe = Annotated[
    Literal["ticks"] | Timeframe,
    BeforeValidator(_parsed_timeframe),
    PlainSerializer(str, return_type=str),
]
"""`ticks`, or a bar timeframe written as schema names write it, such as `1m` or `5m`."""


class ImportProfile(FrozenModel):
    """A file layout of market data and how its records become the store's (module docstring)."""

    kind: ProfileKind = ProfileKind.MARKET_DATA
    name: FolderName
    provider: ProviderName
    description: str = Field(min_length=1)
    layout: FileLayout
    columns: ColumnMapping
    timestamp: TimestampRule
    price: PriceRule = PriceRule()
    volume_unit: SizeUnit = SizeUnit(lot=Decimal(1), asset="contract")
    timeframe: ProfileTimeframe
    series: SeriesKind = SeriesKind.CONTRACT
    contract_in_file_name: str | None = None
    instrument: FolderName | NewInstrument | None = None
    licence_scope: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _maps_the_values_of_its_timeframe(self) -> Self:
        needed, mapped = (
            ("ticks", self.columns.ticks)
            if self.timeframe == TICKS
            else ("bars", self.columns.bars)
        )
        if mapped is None:
            raise ValueError(
                f"Expected the columns of the {needed} a profile of timeframe {self.timeframe} "
                f"reads, got no columns.{needed}."
            )
        return self

    @model_validator(mode="after")
    def _names_the_root_of_a_continuous_series(self) -> Self:
        if self.series is not SeriesKind.CONTRACT and self.instrument is None:
            raise ValueError(
                f"Expected the instrument of a {self.series} series, which names no contract, "
                "got none."
            )
        return self

    def bar_timeframe(self) -> Timeframe | None:
        """The timeframe of the bars the profile reads; None for ticks."""
        return None if isinstance(self.timeframe, str) else self.timeframe


def parse_profile(text: str, source: str) -> ImportProfile:
    """The profile written as YAML in `text`; `source` names it in the refusal."""
    try:
        return ImportProfile.model_validate(yaml.safe_load(text))
    except (ValueError, yaml.YAMLError) as error:
        raise ValueError(f"Expected {source} to hold an import profile, got: {error}") from error


def preset_profiles() -> dict[str, ImportProfile]:
    """The presets FEFAT ships, by name."""
    profiles = (
        parse_profile(path.read_text(encoding="utf-8"), str(path))
        for path in sorted(PRESETS_FOLDER.glob("*.yaml"))
    )
    return {profile.name: profile for profile in profiles}


def saved_profiles(home: Path) -> dict[str, ImportProfile]:
    """The profiles saved in `<home>/profiles/`, by name."""
    folder = home / PROFILES_FOLDER_NAME
    profiles = (
        parse_profile(path.read_text(encoding="utf-8"), str(path))
        for path in sorted(folder.glob("*.yaml"))
    )
    return {profile.name: profile for profile in profiles}


def load_profile(reference: str, home: Path, *, save: bool = True) -> ImportProfile:
    """The profile `reference` names: a preset, a profile saved in `<home>/profiles/`, or a YAML
    file, which is saved there under its name for later imports unless `save` is False, as
    for a preview (a different profile saved under that name is refused)."""
    path = Path(reference)
    if path.suffix.lower() in (".yaml", ".yml"):
        return _saved_from(path, home, save=save)
    presets = preset_profiles()
    saved = saved_profiles(home)
    if reference in presets:
        return presets[reference]
    if reference in saved:
        return saved[reference]
    known = ", ".join([*presets, *saved])
    raise ValueError(
        f"Expected a preset, a saved profile ({known}), or a profile's YAML file, got "
        f"{reference!r}."
    )


def _saved_from(path: Path, home: Path, *, save: bool) -> ImportProfile:
    if not path.is_file():
        raise FileNotFoundError(f"Expected an import profile at {path}, got no such file.")
    profile = parse_profile(path.read_text(encoding="utf-8"), str(path))
    if profile.name in preset_profiles():
        raise ValueError(
            f"Expected a profile name other than the presets', got {profile.name!r} in {path}."
        )
    saved_path = home / PROFILES_FOLDER_NAME / f"{profile.name}.yaml"
    if saved_path.is_file():
        saved = parse_profile(saved_path.read_text(encoding="utf-8"), str(saved_path))
        if saved != profile:
            raise ValueError(
                f"Expected {path} to hold the profile {profile.name} as saved in {saved_path}, "
                "got another: rename one of them."
            )
        return profile
    if not save:
        return profile
    content = path.read_bytes()
    write_atomically(saved_path, lambda temporary: temporary.write_bytes(content))
    return profile


def profile_yaml(profile: ImportProfile) -> str:
    """The profile as a YAML file holds it, to copy into a profile of one's own."""
    return yaml.safe_dump(profile.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
