"""From the rows of a trader's export, read with an import profile
(`fefat.market.importers.profile_values`), to the store's records (step 1.10,
`02-engine-and-data.md` §1.8).

`mapped_records` names each record's contract (`fefat.market.importers.profile_contracts`),
on the instrument FEFAT knows or the new one the profile specifies. Each record's instrument id
is the file's where it has one, else the contract's year and month (202603 for ESH2026), or 1
for a contract that never expires, such as a continuous series or a perpetual.

It then places each record in the sessions of its instrument's calendar: a tick takes the trade
date of its session, an intraday bar the bucket of its session that its timestamp opens or
closes, as the bar builder cuts buckets (`fefat.market.bars.in_buckets`), so an hourly bar
stamped at a 12:15 early close is the bucket from 12:00 to 12:15, and a daily bar the session of
the date it names. A price off the instrument's tick, a record before the product's first trade
date, two bars of a contract in one bucket, a bar off the buckets of its session, and bars no
two of which lie one timeframe apart are problems (`RecordProblem`), their rows left out.
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from fefat.market.bars import in_buckets
from fefat.market.calendar import SessionTable, sessions_of
from fefat.market.calendar_definition import Calendar, CalendarId
from fefat.market.contracts import parse_contract_name
from fefat.market.importers.profile_contracts import ImportFacts, with_contracts
from fefat.market.importers.profile_values import (
    ProblemKind,
    RecordProblem,
    problem_of,
    read_rows,
)
from fefat.market.importers.profiles import BarStamp, ImportProfile, NewInstrument
from fefat.market.instruments import Instrument, InstrumentTable
from fefat.market.schema import SchemaName, Timeframe, TimeUnit, parse_schema_name, polars_schema

NEW_INSTRUMENT_SOURCE = "entered by the trader in an import profile"
_NANO = 1_000_000_000
_UNDATED_INSTRUMENT_ID = 1
_SPACING_PAIRS = 10
"""Pairs of neighbouring bars a file needs before their spacing is checked."""


@dataclass(frozen=True)
class MappedRecords:
    """A file's records as the store holds them, each with its `root` and `contract`, beside
    what was found on the way: their instrument (new when the profile specifies it), its
    sessions, their schema, how many rows the file has, the problems, and how many bars without
    volume and rows of spread symbols were left out."""

    instrument: Instrument
    new_instrument: bool
    sessions: SessionTable
    schema_name: SchemaName
    records: pl.DataFrame
    rows_read: int
    problems: tuple[RecordProblem, ...]
    bars_without_volume: int
    spread_rows: int


def mapped_records(
    table: pl.DataFrame,
    profile: ImportProfile,
    facts: ImportFacts,
    instruments: InstrumentTable,
    cache_folder: Path,
) -> MappedRecords:
    """The records of `table` read with `profile` (module docstring), in the sessions of their
    instrument's calendar, whose table is kept in `cache_folder`."""
    time_zone = _time_zone(profile, facts)
    read = read_rows(table, profile, time_zone, facts.file_name)
    named, root, spread_rows = with_contracts(read.values, profile, facts)
    instrument, new = _instrument(profile, root, instruments)
    identified = _with_instrument_ids(named, facts.file_name)
    priced, off_tick = _on_the_tick(identified, instrument)
    sessions = sessions_of(instrument.session_calendar(), cache_folder)
    timeframe = profile.bar_timeframe()
    if timeframe is None:
        placed, placing = _dated_ticks(priced, sessions), []
    else:
        placed, placing = _placed_bars(priced, timeframe, profile, sessions, time_zone)
    kept, early = _from_the_first_trade_date(
        placed, instrument.valid_from if new else instruments.first_trade_date(root)
    )
    schema_name = parse_schema_name("trades" if timeframe is None else f"ohlcv-{timeframe}")
    found = [
        problem for problem in (*read.problems, off_tick, *placing, early) if problem is not None
    ]
    return MappedRecords(
        instrument=instrument,
        new_instrument=new,
        sessions=sessions,
        schema_name=schema_name,
        records=_canonical(kept, schema_name),
        rows_read=table.height,
        problems=tuple(sorted(found, key=lambda problem: problem.first_row)),
        bars_without_volume=read.bars_without_volume,
        spread_rows=spread_rows,
    )


def _time_zone(profile: ImportProfile, facts: ImportFacts) -> str:
    if facts.time_zone is not None:
        return facts.time_zone
    if profile.timestamp.time_zone is not None:
        return profile.timestamp.time_zone
    raise ValueError(
        f"Expected the time zone of the file's times: the profile {profile.name} leaves it to "
        "each import, since the zone is yours (such as the TWS login's), so name it, such as "
        "--time-zone America/New_York."
    )


def _instrument(
    profile: ImportProfile, root: str, instruments: InstrumentTable
) -> tuple[Instrument, bool]:
    """The records' instrument: the new one the profile specifies, or the table's."""
    if not isinstance(profile.instrument, NewInstrument):
        return instruments.get(root), False
    specification = profile.instrument
    calendar = specification.calendar
    if not isinstance(calendar, CalendarId):
        calendar = Calendar(name=f"{specification.root}-sessions", hours=calendar, holidays=())
    instrument = Instrument(
        root=specification.root,
        kind=specification.kind,
        tick_size=specification.tick_size,
        point_value=specification.point_value,
        lot_step=specification.lot_step,
        currency=specification.currency,
        calendar=calendar,
        last_trade_rule=specification.last_trade_rule,
        valid_from=specification.first_trade_date,
        valid_to=None,
        sources=(NEW_INSTRUMENT_SOURCE,),
    )
    return instrument, True


def _with_instrument_ids(rows: pl.DataFrame, file_name: str) -> pl.DataFrame:
    """The rows with the file's instrument ids, each naming one contract, or with ids from
    their contracts."""
    if "instrument_id" in rows.columns:
        named = rows.select("instrument_id", "contract").unique()
        reused = named.filter(pl.col("instrument_id").is_duplicated())
        if not reused.is_empty():
            raise ValueError(
                f"Expected each instrument_id of {file_name} to name one contract, got "
                f"{reused.item(0, 'instrument_id')} naming several."
            )
        return rows
    ids = {
        contract: _instrument_id(contract)
        for contract in rows.get_column("contract").unique().to_list()
    }
    return rows.with_columns(
        instrument_id=pl.col("contract").replace_strict(ids, return_dtype=pl.UInt32)
    )


def _instrument_id(contract: str) -> int:
    try:
        _, month = parse_contract_name(contract)
    except ValueError:
        return _UNDATED_INSTRUMENT_ID
    return month.year * 100 + month.month


def _on_the_tick(
    rows: pl.DataFrame, instrument: Instrument
) -> tuple[pl.DataFrame, RecordProblem | None]:
    """The rows whose prices lie on the instrument's tick; the others are a problem."""
    tick = instrument.tick_size * _NANO
    prices = [name for name in ("open", "high", "low", "close", "price") if name in rows.columns]
    on_the_tick = pl.all_horizontal(pl.col(name) % int(tick) == 0 for name in prices)
    problem = problem_of(
        rows.filter(~on_the_tick),
        ProblemKind.OFF_THE_TICK,
        f"a price off {instrument.root}'s tick of {instrument.tick_size}: check the profile's "
        "price unit and scale",
    )
    return rows.filter(on_the_tick), problem


def _dated_ticks(rows: pl.DataFrame, sessions: SessionTable) -> pl.DataFrame:
    """Ticks received at their timestamp, each with the trade date of its session (or of the
    session before it, in a break), in the file's order where instants are equal."""
    received = rows.with_columns(
        ts_recv=pl.col("instant"),
        ts_event=pl.col("event_instant") if "event_instant" in rows.columns else pl.col("instant"),
        sequence=pl.col("sequence") if "sequence" in rows.columns else pl.col("row") - 1,
        size=pl.col("volume"),
    )
    return sessions.assign_trade_dates_or_previous(received, "ts_recv").drop("in_session")


def _placed_bars(
    rows: pl.DataFrame,
    timeframe: Timeframe,
    profile: ImportProfile,
    sessions: SessionTable,
    time_zone: str,
) -> tuple[pl.DataFrame, list[RecordProblem]]:
    """Bars in the buckets of their sessions, with the problems of those that fit none, that
    share one, or whose spacing shows another timeframe."""
    if timeframe.unit is TimeUnit.DAY:
        placed, off = _daily_bars(rows, sessions, time_zone)
        return placed, [problem for problem in (off,) if problem is not None]
    placed, off = _intraday_bars(rows, timeframe, profile.timestamp.stamp, sessions)
    twice = pl.struct("contract", "ts_open").is_duplicated()
    doubled = problem_of(
        placed.filter(twice),
        ProblemKind.DUPLICATE_BAR,
        "two bars of a contract in one bucket of its session",
    )
    unique = placed.filter(~twice)
    spaced = _spacing_problem(unique, timeframe)
    return unique, [problem for problem in (off, doubled, spaced) if problem is not None]


def _intraday_bars(
    rows: pl.DataFrame, timeframe: Timeframe, stamp: BarStamp, sessions: SessionTable
) -> tuple[pl.DataFrame, RecordProblem | None]:
    """Each bar in the bucket its timestamp opens, or closes: dated and bucketed by its open, or
    by the instant before its close, as the bar builder dates a print."""
    inside = pl.col("instant") if stamp is BarStamp.OPEN else pl.col("instant") - 1
    marked = rows.with_columns(ts_open=inside, ts_close=inside + 1)
    dated = sessions.assign_trade_dates_or_previous(marked, "ts_open").drop("in_session")
    bucketed = in_buckets(dated, timeframe, sessions)
    edge = "bucket_open" if stamp is BarStamp.OPEN else "bucket_close"
    fits = pl.col("instant") == pl.col(edge)
    problem = problem_of(
        bucketed.filter(~fits),
        ProblemKind.OFF_THE_BUCKETS,
        f"a bar whose timestamp is no {stamp} of a {timeframe.in_words()} bucket of its "
        "session: check the profile's timeframe and stamping",
    )
    placed = bucketed.filter(fits).with_columns(
        ts_open=pl.col("bucket_open"), ts_close=pl.col("bucket_close")
    )
    return placed.drop(
        "bucket_open", "bucket_close", "session_open", "session_close", "next_open"
    ), problem


def _daily_bars(
    rows: pl.DataFrame, sessions: SessionTable, time_zone: str
) -> tuple[pl.DataFrame, RecordProblem | None]:
    """Each daily bar as the session of the date it names, in the file's time zone."""
    local_date = (
        pl.from_epoch(pl.col("instant"), time_unit="ns")
        .dt.replace_time_zone("UTC")
        .dt.convert_time_zone(time_zone)
        .dt.date()
    )
    dated = rows.with_columns(trade_date=local_date)
    first, last = dated.select(pl.col("trade_date").min(), pl.col("trade_date").max()).row(0)
    held = sessions.between(first, last).select("trade_date", ts_open="open", ts_close="close")
    joined = dated.join(held, on="trade_date", how="left")
    problem = problem_of(
        joined.filter(pl.col("ts_open").is_null()),
        ProblemKind.OFF_THE_BUCKETS,
        "a daily bar dated a day without a session of the instrument's calendar",
    )
    return joined.filter(pl.col("ts_open").is_not_null()), problem


def _spacing_problem(bars: pl.DataFrame, timeframe: Timeframe) -> RecordProblem | None:
    """A problem when no two neighbouring bars of a contract's session lie one timeframe
    apart, of at least `_SPACING_PAIRS` pairs, as coarser bars read as finer ones give."""
    width = timeframe.nominal_nanoseconds()
    gaps = (
        bars.sort("contract", "ts_open")
        .with_columns(gap=pl.col("ts_open").diff().over("contract", "trade_date"))
        .drop_nulls("gap")
    )
    if gaps.height < _SPACING_PAIRS or (gaps.get_column("gap") == width).any():
        return None
    closest: int = gaps.select(pl.col("gap").min()).item()
    return problem_of(
        bars,
        ProblemKind.OTHER_TIMEFRAME,
        f"no two bars {timeframe.in_words()} apart, the closest {closest // _NANO} seconds "
        "apart: set the profile's timeframe to the file's",
    )


def _from_the_first_trade_date(
    rows: pl.DataFrame, first_trade_date: date
) -> tuple[pl.DataFrame, RecordProblem | None]:
    """The records dated on or after the product's first trade date; earlier ones are a
    problem."""
    early = pl.col("trade_date") < first_trade_date
    problem = problem_of(
        rows.filter(early),
        ProblemKind.BEFORE_FIRST_TRADE_DATE,
        f"a record dated before the product's first trade date, {first_trade_date}",
    )
    return rows.filter(~early), problem


def _canonical(rows: pl.DataFrame, schema_name: SchemaName) -> pl.DataFrame:
    """The records in the store's columns of `schema_name`, with their root and contract, and
    a tick's trade date, which a bar holds already; a bar's trade count and vwap are null where
    the file has none. Sorted by contract and clock."""
    schema = polars_schema(schema_name)
    filled = rows.with_columns(
        pl.lit(None, dtype=schema[name]).alias(name)
        for name in ("trade_count", "vwap")
        if name in schema and name not in rows.columns
    )
    clock = "ts_open" if "ts_open" in schema else "ts_recv"
    columns = [pl.col(name).cast(dtype) for name, dtype in schema.items()]
    beside = ["root", "contract", *(["trade_date"] if "trade_date" not in schema else [])]
    return filled.select(*columns, *beside).sort("contract", clock, maintain_order=True)
