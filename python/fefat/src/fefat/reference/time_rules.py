"""The execution template's time rules as the reference engine applies them (step 2.3, D-53): the
instant of each trade date's flat-by time. Step 2.8 adds entry windows and the other time exits.

    flat_by_instants([date(2026, 3, 6)], "15:05", "America/Chicago", sessions, Timeframe.parse("5m"))
    # {date(2026, 3, 6): <21:05 UTC, in nanoseconds>}
"""

from collections.abc import Iterable
from datetime import date, time

import polars as pl

from fefat.market.calendar import Session, SessionTable, utc_text
from fefat.market.schema import Timeframe


def flat_by_instants(
    trade_dates: Iterable[date],
    flat_by: str,
    tz: str,
    sessions: SessionTable,
    timeframe: Timeframe,
) -> dict[date, int]:
    """The flat-by instant of each of `trade_dates`: the local time `flat_by`, `HH:MM` in `tz`,
    on the trade date's own day, in nanoseconds since the Unix epoch, UTC, converted per date so
    that a clock change moves it. An instant outside its trade date's session, inside one of the
    session's halts, or off the grid of the signal bars of `timeframe` from the session's open is
    refused, so that a signal bar closes at the instant itself and the exit it places can fill
    before the market closes (D-53): the session's open and a halt's end, at which no bar closes,
    and its close and a halt's start, after which an exit waits for the market to reopen, are
    refused too."""
    days = sorted(set(trade_dates))
    local = _local_instants(days, time.fromisoformat(flat_by), tz)
    named = f"{flat_by} in {tz}"
    return {day: _on_the_grid(local[day], sessions.session(day), timeframe, named) for day in days}


def _local_instants(days: list[date], local: time, tz: str) -> dict[date, int]:
    """The instant of the local time `local` in `tz` on each of `days`; Polars refuses a time
    that a clock change skips or repeats."""
    frame = pl.DataFrame({"trade_date": days}, schema={"trade_date": pl.Date})
    instants = frame.select(
        "trade_date",
        instant=pl.col("trade_date")
        .dt.combine(local, time_unit="ns")
        .dt.replace_time_zone(tz)
        .dt.epoch("ns"),
    )
    return dict(instants.iter_rows())


def _on_the_grid(instant: int, session: Session, timeframe: Timeframe, named: str) -> int:
    """`instant`, the flat-by time `named` on `session`'s trade date, once it falls inside the
    session, outside its halts, and on a close of its signal bars."""
    day, opens, closes = session.trade_date, utc_text(session.open), utc_text(session.close)
    if not session.open < instant < session.close:
        raise ValueError(
            f"Expected the flat-by time {named} inside the session of {day}, after its open at "
            f"{opens} and before its close at {closes}, got {utc_text(instant)}: a flat-by time "
            "at or outside the session's bounds waits for step 2.8."
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
