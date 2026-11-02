"""Reading the rows of a trader's export with an import profile (step 1.10): each row's
timestamp as an instant in nanoseconds since the Unix epoch, UTC, its prices in 1e-9 units, and
its volume, or a tick's size, in lots of the profile's volume unit
(`fefat.market.importers.profiles`).

A timestamp is read in the profile's form: seconds, milliseconds, microseconds, or nanoseconds
since the Unix epoch; ISO 8601, with a `T` or a space, fractional seconds or none, and an offset
or `Z`, which wins, or none, when it is local; Databento's, ISO 8601 or integer nanoseconds; or a
strptime pattern, local. Local times are in the import's time zone, and one that a
daylight-saving change skips or repeats is unreadable; a zone name written after a time, as the
TWS API writes its login's, must give the same instants as the import's zone. A price is a
decimal of at most nine decimals, or an integer of 1e-9 units, times the profile's scale; an
average, such as a vwap, keeps its first nine decimals. Where the profile maps Databento's
record type, each record must be of the type of the profile's timeframe. What cannot be read is
a problem (`RecordProblem`) with the rows it touches, and the rows are left out; so are bars
without volume, which the store never holds, since a bucket without trades has no bar.
"""

from dataclasses import dataclass
from enum import StrEnum

import polars as pl
from pydantic import Field

from fefat.market.calendar_definition import known_time_zone
from fefat.market.importers.profiles import ColumnName, ImportProfile, PriceUnit, TimestampForm
from fefat.market.schema import FrozenModel

_NANO = 1_000_000_000
_DECIMAL_TEXT = r"^([+-]?[0-9]+)(?:\.([0-9]{1,9}))?$"
_AVERAGE_TEXT = r"^([+-]?[0-9]+)(?:\.([0-9]{1,9})[0-9]*)?$"
"""An average's decimals, of which the first nine are kept, as the TWS API's floats write more."""
_INTEGER_TEXT = r"^[+-]?[0-9]+$"
_ZONE_NAME_AFTER_A_TIME = r"\s+([A-Za-z]+/[A-Za-z0-9_+\-/]+)$"
_SIDES = ("A", "B", "N")
_UNIT_NANOSECONDS = {
    TimestampForm.UNIX_SECONDS: _NANO,
    TimestampForm.UNIX_MILLISECONDS: 1_000_000,
    TimestampForm.UNIX_MICROSECONDS: 1_000,
    TimestampForm.UNIX_NANOSECONDS: 1,
}
_DATABENTO_RECORD_TYPES = {"ticks": 0, "1s": 32, "1m": 33, "1h": 34}
"""The `rtype` of Databento's records of each timeframe it gives; its daily bars, type 35, span
UTC days, which FEFAT never stores as sessions (`02-engine-and-data.md` §1.1)."""
_ROW_COLUMNS = ("row", "line", "instant", "symbol")


class ProblemKind(StrEnum):
    """How rows of a file fail to become the store's records."""

    UNREADABLE_TIMESTAMP = "unreadable-timestamp"
    UNREADABLE_VALUE = "unreadable-value"
    OTHER_RECORD_TYPE = "other-record-type"
    PART_VOLUME = "part-volume"
    OUTSIDE_THE_CALENDAR = "outside-the-calendar"
    OFF_THE_TICK = "off-the-tick"
    BEFORE_FIRST_TRADE_DATE = "before-first-trade-date"
    DUPLICATE_BAR = "duplicate-bar"
    OFF_THE_BUCKETS = "off-the-buckets"
    OTHER_TIMEFRAME = "other-timeframe"


class RecordProblem(FrozenModel):
    """Rows of a file that cannot become records: how many, why, and the first of them, by its
    number among the data rows (counting from 1) and its line as the file writes it."""

    kind: ProblemKind
    rows: int = Field(ge=1)
    reason: str
    first_row: int = Field(ge=1)
    first_line: str

    def describe(self) -> str:
        """One line: the kind, the rows, why, and the first of them."""
        rows = "1 row" if self.rows == 1 else f"{self.rows:,} rows"
        return (
            f"{self.kind}, {rows}: {self.reason}; the first is data row {self.first_row}, "
            f"{self.first_line!r}"
        )


def problem_of(rows: pl.DataFrame, kind: ProblemKind, reason: str) -> RecordProblem | None:
    """The problem of `rows`, which carry their `row` and `line`; None when there are none."""
    if rows.is_empty():
        return None
    first = rows.sort("row").row(0, named=True)
    return RecordProblem(
        kind=kind, rows=rows.height, reason=reason, first_row=first["row"], first_line=first["line"]
    )


@dataclass(frozen=True)
class ReadRows:
    """The rows read: their number, line, instant, values, and identity columns; the problems
    of those that could not be read; and how many bars without volume were left out."""

    values: pl.DataFrame
    problems: tuple[RecordProblem, ...]
    bars_without_volume: int


def read_rows(
    table: pl.DataFrame, profile: ImportProfile, time_zone: str, file_name: str
) -> ReadRows:
    """The rows of `table` read with `profile`, local times in `time_zone`."""
    columns = _Columns(table, file_name)
    _require_the_import_zone(table, columns, profile, time_zone, file_name)
    parsed = {
        "row": pl.int_range(1, pl.len() + 1, dtype=pl.UInt32),
        "line": pl.concat_str(pl.all(), separator=profile.layout.delimiter),
        "instant": _instants(
            _timestamp_text(columns, profile), profile.timestamp.format, time_zone
        ),
        **_values(columns, profile, _price_unit(columns, profile), time_zone),
        **_identities(columns, profile),
    }
    values = table.select(**parsed)
    unreadable_time = pl.col("instant").is_null()
    value_names = [name for name in values.columns if name not in _ROW_COLUMNS]
    unreadable_value = pl.any_horizontal(pl.col(name).is_null() for name in value_names)
    found = [
        problem_of(
            values.filter(unreadable_time),
            ProblemKind.UNREADABLE_TIMESTAMP,
            f"no timestamp of the form {profile.timestamp.format} in {time_zone}, or a local "
            "time that a daylight-saving change skips or repeats",
        ),
        problem_of(
            values.filter(~unreadable_time & unreadable_value),
            ProblemKind.UNREADABLE_VALUE,
            "a price, volume, count, side, id, or record type that is no value of the profile's "
            "form (prices with at most nine decimals, sides A, B, or N)",
        ),
    ]
    typed, other_type = _of_its_record_type(
        values.filter(~unreadable_time & ~unreadable_value), profile
    )
    in_lots, part = _in_lots(typed, profile)
    bars = profile.bar_timeframe() is not None
    traded = in_lots.filter(pl.col("volume") > 0) if bars else in_lots
    problems = tuple(problem for problem in (*found, other_type, part) if problem is not None)
    return ReadRows(traded, problems, bars_without_volume=in_lots.height - traded.height)


class _Columns:
    """The columns of one table, by name or by position, refused with the file's name when
    the table lacks one."""

    def __init__(self, table: pl.DataFrame, file_name: str) -> None:
        self._table = table
        self._file_name = file_name

    def holds(self, reference: ColumnName) -> bool:
        return self._name(reference) in self._table.columns

    def text(self, reference: ColumnName) -> pl.Expr:
        name = self._name(reference)
        if name not in self._table.columns:
            held = ", ".join(self._table.columns)
            raise ValueError(
                f"Expected the column {reference!r} in {self._file_name}, got the columns {held}."
            )
        return pl.col(name)

    def any_text(self, reference: ColumnName, pattern: str) -> bool:
        return bool(self._table.select(self.text(reference).str.contains(pattern).any()).item())

    @staticmethod
    def _name(reference: ColumnName) -> str:
        return f"column_{reference}" if isinstance(reference, int) else reference


def _require_the_import_zone(
    table: pl.DataFrame,
    columns: _Columns,
    profile: ImportProfile,
    time_zone: str,
    file_name: str,
) -> None:
    """Refuse times written with a zone name, as the TWS API writes its login's, whose zone
    gives other instants than the import's; another name of the same zone, such as
    `US/Eastern` for `America/New_York`, gives the same."""
    form = profile.timestamp.format
    if isinstance(form, TimestampForm) or "%z" in form:
        return
    text = _timestamp_text(columns, profile)
    zoned = table.select(
        zone=text.str.extract(_ZONE_NAME_AFTER_A_TIME, 1),
        local=text.str.replace(_ZONE_NAME_AFTER_A_TIME, "").str.to_datetime(
            form, strict=False, time_unit="ns"
        ),
    )
    for zone in zoned.get_column("zone").drop_nulls().unique().sort().to_list():
        named = zoned.filter(pl.col("zone") == known_time_zone(zone))
        moved = _from_local(pl.col("local"), zone) != _from_local(pl.col("local"), time_zone)
        if named.select(moved.any()).item():
            raise ValueError(
                f"Expected the times of {file_name} in {time_zone}, the import's time zone, got "
                f"times written in {zone}, which gives other instants: name --time-zone {zone}."
            )


def _timestamp_text(columns: _Columns, profile: ImportProfile) -> pl.Expr:
    """The timestamp's text: its column, or the date and the time joined with a space, a time
    written as a number padded with zeros to four or six digits (930 is 09:30, 0 midnight)."""
    mapping = profile.columns
    if mapping.timestamp is not None:
        return columns.text(mapping.timestamp)
    if mapping.date is None:
        raise ValueError(f"Expected a timestamp or a date column in the profile {profile.name}.")
    day = columns.text(mapping.date)
    if mapping.time is None:
        return day
    time = columns.text(mapping.time)
    padded = (
        pl.when(time.str.contains(r"^[0-9]{1,3}$"))
        .then(time.str.zfill(4))
        .when(time.str.contains(r"^[0-9]{5}$"))
        .then(time.str.zfill(6))
        .otherwise(time)
    )
    return day + " " + padded


def unix_unit_nanoseconds(form: TimestampForm | str) -> int | None:
    """The nanoseconds of one unit of a Unix timestamp form, such as 1,000,000 for `unix_ms`;
    None for a form written as text."""
    return _UNIT_NANOSECONDS.get(form) if isinstance(form, TimestampForm) else None


def _instants(text: pl.Expr, form: TimestampForm | str, time_zone: str) -> pl.Expr:
    if isinstance(form, TimestampForm) and form in _UNIT_NANOSECONDS:
        return _integer(text) * _UNIT_NANOSECONDS[form]
    if form is TimestampForm.ISO:
        return _iso_instants(text, time_zone)
    if form is TimestampForm.DATABENTO:
        digits = text.str.contains(r"^[0-9]+$")
        return pl.when(digits).then(_integer(text)).otherwise(_iso_instants(text, time_zone))
    return _pattern_instants(text, form, time_zone)


def _integer(text: pl.Expr) -> pl.Expr:
    return pl.when(text.str.contains(_INTEGER_TEXT)).then(text).cast(pl.Int64, strict=False)


def _iso_instants(text: pl.Expr, time_zone: str) -> pl.Expr:
    normalised = text.str.replace(r"Z$", "+00:00").str.replace("T", " ")
    with_offset = normalised.str.to_datetime(
        "%Y-%m-%d %H:%M:%S%.f%:z", strict=False, time_unit="ns"
    ).dt.epoch("ns")
    local = normalised.str.to_datetime("%Y-%m-%d %H:%M:%S%.f", strict=False, time_unit="ns")
    return pl.coalesce(with_offset, _from_local(local, time_zone))


def _pattern_instants(text: pl.Expr, pattern: str, time_zone: str) -> pl.Expr:
    bare = text.str.replace(_ZONE_NAME_AFTER_A_TIME, "")
    if "%z" in pattern:
        return bare.str.to_datetime(pattern, strict=False, time_unit="ns").dt.epoch("ns")
    if not any(clock in pattern for clock in ("%H", "%I")):
        return _from_local(
            bare.str.to_date(pattern, strict=False).cast(pl.Datetime("ns")), time_zone
        )
    return _from_local(bare.str.to_datetime(pattern, strict=False, time_unit="ns"), time_zone)


def _from_local(local: pl.Expr, time_zone: str) -> pl.Expr:
    zoned = local.dt.replace_time_zone(time_zone, ambiguous="null", non_existent="null")
    return zoned.dt.epoch("ns")


def _nano_units(text: pl.Expr, decimals: str = _DECIMAL_TEXT) -> pl.Expr:
    """A decimal in exact 1e-9 units, of at most nine decimals, or, read with `_AVERAGE_TEXT`,
    its first nine; null for anything else."""
    whole = text.str.extract(decimals, 1)
    part = text.str.extract(decimals, 2).fill_null("").str.pad_end(9, "0")
    return (whole + part).cast(pl.Int64, strict=False)


def _price_unit(columns: _Columns, profile: ImportProfile) -> PriceUnit:
    """The profile's unit; for Databento's, decimals when any close or price has a point."""
    if profile.price.unit is not PriceUnit.DATABENTO:
        return profile.price.unit
    mapping = profile.columns
    reference = mapping.bars.close if mapping.bars is not None else None
    if reference is None and mapping.ticks is not None:
        reference = mapping.ticks.price
    if reference is None:
        raise ValueError(f"Expected a price column in the profile {profile.name}.")
    return PriceUnit.DECIMAL if columns.any_text(reference, r"\.") else PriceUnit.NANO_INTEGER


def _price(
    text: pl.Expr, unit: PriceUnit, profile: ImportProfile, decimals: str = _DECIMAL_TEXT
) -> pl.Expr:
    units = _integer(text) if unit is PriceUnit.NANO_INTEGER else _nano_units(text, decimals)
    numerator, denominator = profile.price.scale.as_integer_ratio()
    if (numerator, denominator) == (1, 1):
        return units
    scaled = units * numerator
    return pl.when(scaled % denominator == 0).then(scaled // denominator)


def _values(
    columns: _Columns, profile: ImportProfile, unit: PriceUnit, time_zone: str
) -> dict[str, pl.Expr]:
    """A bar's prices and its volume, or a tick's price, size, side, event time, and sequence;
    a volume or size in 1e-9 units of the file's own figure, as lots are counted later."""
    bars = profile.columns.bars
    if profile.bar_timeframe() is not None and bars is not None:
        found = {
            "open": _price(columns.text(bars.open), unit, profile),
            "high": _price(columns.text(bars.high), unit, profile),
            "low": _price(columns.text(bars.low), unit, profile),
            "close": _price(columns.text(bars.close), unit, profile),
            "volume_figure": _nano_units(columns.text(bars.volume)),
        }
        if bars.trade_count is not None:
            found["trade_count"] = columns.text(bars.trade_count).cast(pl.UInt32, strict=False)
        if bars.vwap is not None:
            found["vwap"] = _price(columns.text(bars.vwap), unit, profile, _AVERAGE_TEXT)
        return found
    ticks = profile.columns.ticks
    if ticks is None:
        raise ValueError(f"Expected the bar or tick columns of the profile {profile.name}.")
    side = pl.lit("N") if ticks.side is None else columns.text(ticks.side).str.to_uppercase()
    found = {
        "price": _price(columns.text(ticks.price), unit, profile),
        "volume_figure": _nano_units(columns.text(ticks.size)),
        "side": pl.when(side.is_in(_SIDES)).then(side),
    }
    if ticks.event_time is not None:
        found["event_instant"] = _instants(
            columns.text(ticks.event_time), profile.timestamp.format, time_zone
        )
    if ticks.sequence is not None:
        found["sequence"] = columns.text(ticks.sequence).cast(pl.UInt32, strict=False)
    return found


def _identities(columns: _Columns, profile: ImportProfile) -> dict[str, pl.Expr]:
    """Each row's symbol and instrument id, where the profile maps them and the file has them,
    and its record type, where the profile maps it."""
    mapping = profile.columns
    found: dict[str, pl.Expr] = {}
    if mapping.symbol is not None and columns.holds(mapping.symbol):
        found["symbol"] = columns.text(mapping.symbol)
    if mapping.instrument_id is not None and columns.holds(mapping.instrument_id):
        found["instrument_id"] = columns.text(mapping.instrument_id).cast(pl.UInt32, strict=False)
    if mapping.record_type is not None:
        found["record_type"] = columns.text(mapping.record_type).cast(pl.UInt8, strict=False)
    return found


def _of_its_record_type(
    rows: pl.DataFrame, profile: ImportProfile
) -> tuple[pl.DataFrame, RecordProblem | None]:
    """The rows of the record type of the profile's timeframe, where it maps Databento's
    `rtype`; the others are a problem, as Databento's daily bars are."""
    if profile.columns.record_type is None:
        return rows, None
    expected = _DATABENTO_RECORD_TYPES.get(str(profile.timeframe))
    fits = pl.lit(False) if expected is None else pl.col("record_type") == expected
    reason = (
        f"a Databento record read by a profile of timeframe {profile.timeframe}, of which "
        "Databento gives no bars by session (its daily bars span UTC days): import its "
        "1-minute bars"
        if expected is None
        else f"a record whose rtype is not {expected}, Databento's type of "
        f"{profile.timeframe} records"
    )
    problem = problem_of(rows.filter(~fits), ProblemKind.OTHER_RECORD_TYPE, reason)
    return rows.filter(fits).drop("record_type"), problem


def _in_lots(
    rows: pl.DataFrame, profile: ImportProfile
) -> tuple[pl.DataFrame, RecordProblem | None]:
    """The rows with their volume, or size, in whole lots of the profile's volume unit; a
    negative one or a part of a lot is a problem and its row left out."""
    lot = profile.volume_unit.lot * _NANO
    if lot != lot.to_integral_value():
        raise ValueError(
            f"Expected a volume unit of at least 1e-9, got {profile.volume_unit.lot} in the "
            f"profile {profile.name}."
        )
    figure = pl.col("volume_figure")
    whole = (figure >= 0) & (figure % int(lot) == 0)
    part = problem_of(
        rows.filter(~whole),
        ProblemKind.PART_VOLUME,
        f"a volume or size that is no whole number of {profile.volume_unit} (the profile's "
        "volume unit), or below zero",
    )
    lots = rows.filter(whole).with_columns(volume=figure // int(lot)).drop("volume_figure")
    return lots, part
