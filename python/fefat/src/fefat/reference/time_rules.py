"""The execution template's time rules as both engines read them (steps 2.3 and 2.8, D-53,
`docs/spec/fill-semantics.md` §26): each signal row's flat-by instant (F-TIM-01); whether it lies
from the last signal close before a stop of trading, of any kind or over a weekend, until trading
resumes (F-TIM-03); and whether an entry may be placed at its close (F-TIM-04); each worked out
once per row from the session table and the time zone's own rules (F-TIM-05). `fefat-cli run`
reads the same columns (`fefat.reference.rust_batch`); max bars and max minutes (F-TIM-02) count
from a fill, and the template applies them at its decisions.

    frame = with_time_rules(spec, signals, sessions)
    frame.select("ts_close", "flat_by", "session_end", "week_end", "in_window")
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from types import MappingProxyType

import polars as pl

from fefat.market.calendar import Session, SessionTable, utc_text
from fefat.market.calendar_definition import SessionHours
from fefat.market.schema import Timeframe
from fefat.reference.orders import OrderRole
from fefat.strategy.exits import EntryWindow, TimeRules, Weekday
from fefat.strategy.spec import StrategySpec

_ISO_WEEKDAYS = {weekday: number for number, weekday in enumerate(Weekday, start=1)}
_NO_ROWS: Mapping[date, int] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class TradingStop:
    """A stop of trading (§20): from `start` until trading resumes at `resumes`, in nanoseconds
    since the Unix epoch, UTC; over a weekend when its break holds a day of the week on which the
    calendar has no trade date."""

    start: int
    resumes: int
    weekend: bool


def with_time_rules(
    spec: StrategySpec, frame: pl.DataFrame, sessions: SessionTable | None
) -> pl.DataFrame:
    """`frame`, a signal frame in the order of its closes, with a column for each time rule of
    `spec` that reads one: `flat_by`, `session_end`, `week_end`, and `in_window`. Flat-by, no
    overnight, and no weekend need the instrument's session table."""
    rules = spec.execution.time
    if rules is None:
        return frame
    columns = [] if not rules.windows else [f_tim_04(frame, rules.windows, rules.tz)]
    if rules.flat_by is not None:
        table = _required(sessions, f"the flat-by time {rules.flat_by}")
        timeframe = Timeframe.parse(spec.timeframe)
        columns.append(f_tim_01(frame, rules.flat_by, rules.tz, table, timeframe))
    if rules.no_overnight:
        columns.append(f_tim_03(frame, _required(sessions, "no_overnight"), weekend=False))
    if rules.no_weekend:
        columns.append(f_tim_03(frame, _required(sessions, "no_weekend"), weekend=True))
    return frame.with_columns(columns)


def _required(sessions: SessionTable | None, rule: str) -> SessionTable:
    if sessions is None:
        raise ValueError(f"Expected a session calendar for {rule}, got an instrument without one.")
    return sessions


# §26 Time rules
def f_tim_01(
    frame: pl.DataFrame, flat_by: str, tz: str, sessions: SessionTable, timeframe: Timeframe
) -> pl.Series:
    """Each row's flat-by instant, its trade date's (`flat_by_instants`), from which the template
    closes the position and places no entry."""
    trade_dates = frame.get_column("trade_date").to_list()
    last_closes = _last_closes_before_the_close(frame, sessions)
    instants = flat_by_instants(trade_dates, flat_by, tz, sessions, timeframe, last_closes)
    return pl.Series("flat_by", [instants[day] for day in trade_dates], dtype=pl.Int64)


def f_tim_02(
    rules: TimeRules | None, opened_at: int | None, now: int, decisions: int
) -> OrderRole | None:
    """The time exit of a position that opened at `opened_at`, at the decision `now`, the
    `decisions`-th at or after its entry's fill: `max_bars` from the max_bars-th, `max_minutes`
    from the first at or after the fill plus the minutes; none for a position held when the
    tape starts, which no fill opened."""
    if rules is None or opened_at is None:
        return None
    if rules.max_bars is not None and decisions >= rules.max_bars:
        return OrderRole.MAX_BARS
    minutes = rules.max_minutes
    if minutes is not None and now >= opened_at + minutes * 60 * 1_000_000_000:
        return OrderRole.MAX_MINUTES
    return None


def f_tim_03(frame: pl.DataFrame, sessions: SessionTable, weekend: bool) -> pl.Series:
    """Whether each row lies from the last signal close before a stop of trading (§20) until
    trading resumes, the last row of the stop's trade date that closes before it:
    `session_end` for every stop, `week_end` for a stop over a weekend."""
    closes = frame.get_column("ts_close").to_list()
    rows_of: defaultdict[date, list[int]] = defaultdict(list)
    for index, day in enumerate(frame.get_column("trade_date").to_list()):
        rows_of[day].append(index)
    flagged = [False] * len(closes)
    for day, rows in rows_of.items():
        for stop in trading_stops(sessions, day):
            before = [closes[index] for index in rows if closes[index] < stop.start]
            if not before or (weekend and not stop.weekend):
                continue
            for index in rows:
                flagged[index] |= max(before) <= closes[index] < stop.resumes
    return pl.Series("week_end" if weekend else "session_end", flagged, dtype=pl.Boolean)


def f_tim_04(frame: pl.DataFrame, windows: Sequence[EntryWindow], tz: str) -> pl.Series:
    """Whether an entry may be placed at each row's close: its local time in `tz` lies in one of
    `windows`, from its start to just before its end, past midnight when its end comes first,
    and on one of its weekdays, those of the row's local date."""
    local = pl.col("ts_close").cast(pl.Datetime("ns", "UTC")).dt.convert_time_zone(tz)
    clock, weekday = local.dt.time(), local.dt.weekday()
    allowed = pl.lit(False)
    for window in windows:
        start, end = time.fromisoformat(window.start), time.fromisoformat(window.end)
        within = (
            (clock >= start) & (clock < end) if start <= end else (clock >= start) | (clock < end)
        )
        if window.weekdays is not None:
            within &= weekday.is_in([_ISO_WEEKDAYS[day] for day in window.weekdays])
        allowed |= within
    return frame.select(allowed.alias("in_window")).to_series()


def f_tim_05(days: list[date], local: time, tz: str) -> dict[date, int]:
    """The instant of the local time `local` in `tz` on each of `days`, by the time zone's own
    rules, never a fixed offset; Polars refuses a time that a clock change skips or repeats."""
    frame = pl.DataFrame({"trade_date": days}, schema={"trade_date": pl.Date})
    instants = frame.select(
        "trade_date",
        instant=pl.col("trade_date")
        .dt.combine(local, time_unit="ns")
        .dt.replace_time_zone(tz)
        .dt.epoch("ns"),
    )
    return dict(instants.iter_rows())


def flat_by_instants(
    trade_dates: Iterable[date],
    flat_by: str,
    tz: str,
    sessions: SessionTable,
    timeframe: Timeframe,
    last_closes: Mapping[date, int] = _NO_ROWS,
) -> dict[date, int]:
    """The flat-by instant of each of `trade_dates` (F-TIM-01): the local time `flat_by`, `HH:MM`
    in `tz`, on the trade date's own day, in nanoseconds since the Unix epoch, UTC, converted per
    date so that a clock change moves it (F-TIM-05). An instant after the session's open must lie
    outside its halts and on the grid of the signal bars of `timeframe` from the open, so that a
    signal bar closes at the instant itself and the exit it places can fill before the market
    closes (D-53); one at or before the open is refused. On a trade date whose session closes at
    or before the instant, as an early close does, it is the last signal close before the close,
    from `last_closes`, or the close itself without one."""
    days = sorted(set(trade_dates))
    local = f_tim_05(days, time.fromisoformat(flat_by), tz)
    named = f"{flat_by} in {tz}"
    instants = {}
    for day in days:
        session = sessions.session(day)
        if local[day] >= session.close:
            instants[day] = last_closes.get(day, session.close)
            continue
        instants[day] = _on_the_grid(local[day], session, timeframe, named)
    return instants


def trading_stops(sessions: SessionTable, trade_date: date) -> tuple[TradingStop, ...]:
    """The stops of trading of `trade_date`'s session, in order: each holiday halt, from which
    trading resumes at the calendar's regular open (D-41), and the close, from which it resumes
    at the next session's open; a daily halt, which every session of its era holds, is none."""
    session, hours = sessions.session(trade_date), sessions.hours()
    breaks = [
        (halt.start, halt.end)
        for halt in session.halts
        if _local(halt.end, hours.time_zone).time() == hours.opens_at
    ]
    breaks.append((session.close, sessions.following(trade_date).open))
    return tuple(
        TradingStop(start, resumes, _holds_a_day_off(start, resumes, hours))
        for start, resumes in breaks
    )


def _holds_a_day_off(start: int, resumes: int, hours: SessionHours) -> bool:
    """Whether a break from `start` to `resumes` holds a whole local day on which the calendar
    has no trade date, such as a Saturday for CME: a weekend."""
    first, last = (_local(instant, hours.time_zone).date() for instant in (start, resumes))
    held = (first + timedelta(days=offset) for offset in range(1, (last - first).days))
    trading = {int(weekday) for weekday in hours.weekdays}
    return any(day.isoweekday() not in trading for day in held)


def _local(instant: int, tz: str) -> datetime:
    """`instant` as the wall clock of `tz` shows it."""
    utc = pl.Series([instant], dtype=pl.Int64).cast(pl.Datetime("ns", "UTC"))
    return utc.dt.convert_time_zone(tz).dt.replace_time_zone(None).item()


def _last_closes_before_the_close(frame: pl.DataFrame, sessions: SessionTable) -> dict[date, int]:
    """The last signal close before its session's close on each trade date of `frame`."""
    closes: dict[date, int] = {}
    sessions_of = {day: sessions.session(day) for day in frame.get_column("trade_date").unique()}
    for ts_close, day in frame.select("ts_close", "trade_date").iter_rows():
        if ts_close < sessions_of[day].close:
            closes[day] = max(closes.get(day, ts_close), ts_close)
    return closes


def _on_the_grid(instant: int, session: Session, timeframe: Timeframe, named: str) -> int:
    """`instant`, the flat-by time `named` on `session`'s trade date, once it falls after the
    session's open, outside its halts, and on a close of its signal bars."""
    day, opens = session.trade_date, utc_text(session.open)
    if instant <= session.open:
        raise ValueError(
            f"Expected the flat-by time {named} inside the session of {day}, after its open at "
            f"{opens}, got {utc_text(instant)}."
        )
    for halt in session.halts:
        if halt.start <= instant <= halt.end:
            raise ValueError(
                f"Expected the flat-by time {named} outside the halts of the session of {day}, "
                f"got {utc_text(instant)}, at or inside the halt from {utc_text(halt.start)} to "
                f"{utc_text(halt.end)}."
            )
    if (instant - session.open) % timeframe.nominal_nanoseconds():
        raise ValueError(
            f"Expected the flat-by time {named} on a close of the {timeframe} signal bars of {day}, "
            f"which close every {timeframe} from {opens}, got {utc_text(instant)}."
        )
    return instant
