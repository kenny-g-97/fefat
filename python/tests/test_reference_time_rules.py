"""Step 2.8's stops of trading (`docs/spec/fill-semantics.md` §20, F-TIM-03), from the session
table: a holiday's halt and the close are stops, a daily halt is none, and a stop whose break holds
a day of the week without trade dates is a weekend; and step 3.4's last close of the signal bars'
grid before a stop, from the session table and the timeframe, so that a frame cut inside a session
keeps the flags of its rows (D-71). S-template-035 to S-template-045 hold the time rules on tapes."""

from datetime import date

import polars as pl
import pytest

from fefat.market import instruments
from fefat.market.calendar import SessionTable, sessions_of
from fefat.market.schema import Timeframe
from fefat.market.trading_stops import TradingStop, trading_stops
from fefat.reference.time_rules import flat_by_instants, last_grid_close_before, with_time_rules
from fefat.reference.units import instant_nanoseconds
from fefat.strategy import TimeRules
from test_reference_template import spec_of


@pytest.fixture(scope="module")
def es_sessions(tmp_path_factory: pytest.TempPathFactory) -> SessionTable:
    calendar = instruments.get("ES").session_calendar()
    return sessions_of(calendar, tmp_path_factory.mktemp("cache"))


def stop(start: str, resumes: str, weekend: bool) -> TradingStop:
    return TradingStop(instant_nanoseconds(start), instant_nanoseconds(resumes), weekend)


@pytest.mark.parametrize(
    ("trade_date", "stops"),
    [
        # A Thursday: the close, an hour before the next session opens.
        (date(2026, 3, 5), [stop("2026-03-05T22:00:00Z", "2026-03-05T23:00:00Z", False)]),
        # A Friday: the close, until Sunday's open, over a Saturday.
        (date(2026, 3, 6), [stop("2026-03-06T22:00:00Z", "2026-03-08T22:00:00Z", True)]),
        # Presidents' Day's halt, from noon Monday to the regular open, then Tuesday's close.
        (
            date(2026, 2, 17),
            [
                stop("2026-02-16T18:00:00Z", "2026-02-16T23:00:00Z", False),
                stop("2026-02-17T22:00:00Z", "2026-02-17T23:00:00Z", False),
            ],
        ),
        # The daily pause from 15:15 to 15:30 before 2021-06-28 is no stop.
        (date(2021, 3, 4), [stop("2021-03-04T22:00:00Z", "2021-03-04T23:00:00Z", False)]),
        # Thursday before the Good Friday full close, until Sunday's open.
        (date(2025, 4, 17), [stop("2025-04-17T21:00:00Z", "2025-04-20T22:00:00Z", True)]),
        # The halt from noon on Friday 2026-07-03 to Sunday's open, inside Monday's session.
        (
            date(2026, 7, 6),
            [
                stop("2026-07-03T17:00:00Z", "2026-07-05T22:00:00Z", True),
                stop("2026-07-06T21:00:00Z", "2026-07-06T22:00:00Z", False),
            ],
        ),
    ],
)
def test_a_sessions_stops_of_trading_are_its_holiday_halts_and_its_close(
    es_sessions: SessionTable, trade_date: date, stops: list[TradingStop]
) -> None:
    assert list(trading_stops(es_sessions, trade_date)) == stops


def rows_of(trade_date: str, *closes: str) -> pl.DataFrame:
    """Signal rows of `trade_date` closing at `closes`, UTC clocks."""
    day = date.fromisoformat(trade_date)
    return pl.DataFrame(
        {
            "ts_close": [instant_nanoseconds(close) for close in closes],
            "trade_date": [day] * len(closes),
        }
    )


@pytest.mark.parametrize(
    ("rules", "column", "trade_date"),
    [
        (TimeRules(tz="America/Chicago", no_overnight=True), "session_end", "2026-03-05"),
        (TimeRules(tz="America/Chicago", no_weekend=True), "week_end", "2026-03-06"),
    ],
)
def test_a_frame_cut_inside_a_session_flags_its_rows_as_the_whole_session_does(
    es_sessions: SessionTable, rules: TimeRules, column: str, trade_date: str
) -> None:
    # The amendment (D-71): the last close before a stop comes from the session table and the
    # timeframe, so a frame that ends inside a session, as one the leak detector cuts does, flags
    # no row that the whole session leaves unflagged, and a frame that ends at the close keeps
    # its flags: 21:55 and 22:00, the close.
    spec = spec_of(time=rules)
    minutes = ("30", "35", "40", "45", "50", "55")
    closes = [*(f"{trade_date}T21:{minute}:00Z" for minute in minutes), f"{trade_date}T22:00:00Z"]

    whole = with_time_rules(spec, rows_of(trade_date, *closes), es_sessions)
    cut = with_time_rules(spec, rows_of(trade_date, *closes[:3]), es_sessions)

    assert whole.get_column(column).to_list() == [False] * 5 + [True, True]
    assert cut.get_column(column).to_list() == [False] * 3


def test_flat_by_on_an_early_close_acts_at_the_grids_last_close_before_it_whatever_the_frame(
    es_sessions: SessionTable,
) -> None:
    # F-TIM-01 on 2026-11-27, the day after Thanksgiving, which closes at 12:15 Chicago, 18:15 UTC:
    # the last close of the 5-minute grid before it is 18:10, in a frame cut before it and with
    # no frame at all (S-template-038 holds the rows to the close).
    spec = spec_of(time=TimeRules(tz="America/Chicago", flat_by="15:05"))
    cut = rows_of("2026-11-27", "2026-11-27T17:55:00Z", "2026-11-27T18:05:00Z")
    last_before_the_close = instant_nanoseconds("2026-11-27T18:10:00Z")

    timed = with_time_rules(spec, cut, es_sessions)
    instants = flat_by_instants(
        [date(2026, 11, 27)], "15:05", "America/Chicago", es_sessions, Timeframe.parse("5m")
    )

    assert timed.get_column("flat_by").to_list() == [last_before_the_close] * 2
    assert instants == {date(2026, 11, 27): last_before_the_close}


@pytest.mark.parametrize(
    ("trade_date", "timeframe", "before", "last"),
    [
        # A Thursday's close, on 5-minute and hourly bars; a daily bar closes at the close alone.
        (date(2026, 3, 5), "5m", "2026-03-05T22:00:00Z", "2026-03-05T21:55:00Z"),
        (date(2026, 3, 5), "1h", "2026-03-05T22:00:00Z", "2026-03-05T21:00:00Z"),
        (date(2026, 3, 5), "1d", "2026-03-05T22:00:00Z", None),
        (date(2026, 3, 5), "1d", "2026-03-05T23:00:00Z", "2026-03-05T22:00:00Z"),
        # No bucket closes before the first one, five minutes after the open.
        (date(2026, 3, 5), "5m", "2026-03-04T23:05:00Z", None),
        # Presidents' Day's halt: the bar before it, and from inside it the bar closing at its
        # start, since the grid leaves out the buckets lying wholly inside it.
        (date(2026, 2, 17), "5m", "2026-02-16T18:00:00Z", "2026-02-16T17:55:00Z"),
        (date(2026, 2, 17), "5m", "2026-02-16T20:00:00Z", "2026-02-16T18:00:00Z"),
        # The daily pause from 15:15 to 15:30 Chicago before 2021-06-28.
        (date(2021, 3, 4), "5m", "2021-03-04T21:30:00Z", "2021-03-04T21:15:00Z"),
        # The early close at 12:15 Chicago cuts the hourly bucket from 12:00 in two.
        (date(2026, 11, 27), "1h", "2026-11-27T18:15:00Z", "2026-11-27T18:00:00Z"),
        (date(2026, 11, 27), "1h", "2026-11-27T18:16:00Z", "2026-11-27T18:15:00Z"),
    ],
)
def test_the_last_close_of_the_grid_before_an_instant_comes_from_the_session_and_the_timeframe(
    es_sessions: SessionTable, trade_date: date, timeframe: str, before: str, last: str | None
) -> None:
    session = es_sessions.session(trade_date)

    found = last_grid_close_before(session, Timeframe.parse(timeframe), instant_nanoseconds(before))

    assert found == (None if last is None else instant_nanoseconds(last))
