"""Continuous futures bars for signals, forward-anchored, and the roll calendar that splices them
from a root's contracts (`02-engine-and-data.md` §1.5, D-09, D-44).

Why forward anchoring (ADR-0007, `docs/adr/0007-forward-anchored-continuous-series.md`): a
back-adjusted series shifts every earlier price at each roll, so a value a feature computed
yesterday changes today, its cache goes stale, and the leak detector, which recomputes on
truncated data and requires every value before a cut to stay the same (ADR-0010), flags honest
features. Here history never changes: the first contract keeps its raw prices, and at each roll
the new contract is shifted by the gap between the two contracts so that it joins the old
series. Orders execute on the real contract at its raw prices, so a price level read on the
series converts back through `RollCalendar.to_raw_price`; a back-adjusted view, which ends at
the newest contract's raw prices, is for charts only (`back_adjusted`).

The roll calendar decides the front contract of each session `d` at its open from the bars of
the sessions before it, all in hand by then (D-43), and refuses a bar closing after the next
session's open (`fefat.market.roll_decisions`). The default rule, `volume_rolls`: the contract
that traded most in `d-1` leads; the front never rolls back to an earlier month, so it is the
latest month that has led so far; and it is forced off a contract at the open of its last trade
date (`fefat.market.last_trade_rules`), inside whose session the contract stops trading, onto
the nearest later month that has traded. `open_interest_rolls` leads by the open interest last
received by each open, and `calendar_rolls` rolls a set number of sessions before the last trade
date. Rows run from the second session of the bars to the last opening by `received_until`, the
instant by which every bar is in hand, as `fefat.market.bars` takes it; each row's front holds
until the next session's open, and a session that no contract may serve has no row.

At a roll from A to B at the open of `d`, the gap is B's close minus A's in the latest bar both
traded in before `d`, and `adj_offset` falls by it: adjusted prices are raw prices plus
`adj_offset`, 0 for the first contract of the bars given, so the two closes of that bar read the
same adjusted. `RollCalendar.rolls` lists the rolls, at whose opens the engine transfers a
position held across them (step 2.9), and `continuous_bars` keeps the front's bars of each
session with adjusted prices, `close_raw`, `adj_offset`, and `roll_flag` on each new front's
first bar. No row or bar depends on later data: those by any instant are the same when the data
stops there (D-12).

    mes = instruments.get("MES")
    sessions = sessions_of(mes.session_calendar(), paths.cache_dir)
    bars = store.scan_contracts(request).collect()
    calendar = volume_rolls(bars, sessions, mes, bars.get_column("ts_close").max())
    signal_bars = calendar.continuous_bars(bars)
"""

from datetime import date

import polars as pl

from fefat.market.calendar import SessionTable, utc_text
from fefat.market.instruments import Instrument
from fefat.market.roll_decisions import (
    CONTRACT_BAR_COLUMNS,
    ROLL_CALENDAR_COLUMNS,
    RollReason,
    calendar_rows,
    decision_grid,
    require_bars_apart,
)
from fefat.market.schema import FrozenModel, parse_schema_name, polars_schema, require_columns

__all__ = [
    "BACK_ADJUSTED_COLUMNS",
    "CONTINUOUS_COLUMNS",
    "CONTRACT_BAR_COLUMNS",
    "ROLL_CALENDAR_COLUMNS",
    "STATISTICS_CONTRACT_COLUMNS",
    "FrontContract",
    "RollCalendar",
    "RollReason",
    "back_adjusted",
    "calendar_rolls",
    "open_interest_rolls",
    "volume_rolls",
]

STATISTICS_CONTRACT_COLUMNS = pl.Schema(
    {**polars_schema(parse_schema_name("statistics")), "contract": pl.String}
)
"""Statistics with their contract as a last column, as `Store.scan_contracts` reads them."""
CONTINUOUS_COLUMNS = pl.Schema(
    {**CONTRACT_BAR_COLUMNS, "close_raw": pl.Int64, "adj_offset": pl.Int64, "roll_flag": pl.Boolean}
)
"""Continuous bars: a bar's columns with open, high, low, close, and vwap adjusted, the front
contract, its raw close, the offset, and whether the bar is a new front's first."""
BACK_ADJUSTED_COLUMNS = pl.Schema(
    {
        ("back_adjustment" if name == "adj_offset" else name): dtype
        for name, dtype in CONTINUOUS_COLUMNS.items()
    }
)
"""The chart view of continuous bars: their columns with `back_adjustment`, what was added to
the raw prices, in place of `adj_offset`, so that nothing reading continuous bars takes it."""

_OPEN_INTEREST_STAT_TYPE = 9
"""The `stat_type` of open interest in the statistics schema (`fefat.market.schema`)."""
_ADJUSTED_COLUMNS = ("open", "high", "low", "close", "vwap")


class FrontContract(FrozenModel):
    """The front contract of a session in a roll calendar, with the offset of its prices."""

    trade_date: date
    contract: str
    adj_offset: int


class RollCalendar:
    """A root's front contract session by session, decided from the data in hand by
    `received_until`, with the columns of `ROLL_CALENDAR_COLUMNS`, sorted by trade date."""

    def __init__(self, root: str, rows: pl.DataFrame, received_until: int) -> None:
        require_columns(ROLL_CALENDAR_COLUMNS, rows.schema, f"the roll calendar of {root}")
        self._root = root
        self._rows = rows
        self._received_until = received_until

    def __repr__(self) -> str:
        if self._rows.is_empty():
            return f"RollCalendar({self._root!r}, no sessions)"
        first, last = self._rows.item(0, "trade_date"), self._rows.item(-1, "trade_date")
        rolls = self.rolls().height
        counted = f"{rolls} roll" if rolls == 1 else f"{rolls} rolls"
        sessions = f"{self._rows.height} sessions, {first} to {last}"
        return f"RollCalendar({self._root!r}, {sessions}, {counted})"

    @property
    def root(self) -> str:
        """The root whose contracts the calendar splices."""
        return self._root

    @property
    def rows(self) -> pl.DataFrame:
        """The row of each session, with the columns of `ROLL_CALENDAR_COLUMNS`."""
        return self._rows

    def rolls(self) -> pl.DataFrame:
        """The rolls, sorted by trade date: at `session_open` the front passes from
        `rolled_from` to `contract`, whose closes in the latest bar both traded in before it
        differ by `gap`, for `reason`; a position held across the roll is transferred there,
        its price levels moving by the gap (step 2.9)."""
        return self._rows.filter(pl.col("rolled_from").is_not_null()).select(
            "trade_date", "session_open", "rolled_from", "contract", "gap", "reason"
        )

    def front(self, at: int) -> FrontContract:
        """The front contract at the instant `at`: that of the last session opening at or
        before it, which holds until the next session's open. An instant before the first
        session, in a session that no contract may serve, or after `received_until`, when the
        next session's front may still change, is refused."""
        if self._rows.is_empty():
            raise ValueError(f"Expected a session in the roll calendar of {self._root}, got none.")
        first_open = self._rows.item(0, "session_open")
        if at < first_open:
            raise ValueError(
                f"Expected an instant from {utc_text(first_open)}, the first open of the roll "
                f"calendar of {self._root}, got {utc_text(at)}."
            )
        if at > self._received_until:
            raise ValueError(
                f"Expected an instant by {utc_text(self._received_until)}, the end of the data "
                f"of the roll calendar of {self._root}, got {utc_text(at)}."
            )
        index = self._rows.get_column("session_open").search_sorted(at, side="right") - 1
        row = self._rows.row(index, named=True)
        if at >= row["next_open"]:
            raise ValueError(
                f"Expected an instant in a session with a front contract of {self._root}, got "
                f"{utc_text(at)}, in the sessions from {utc_text(row['next_open'])} that no "
                "contract may serve."
            )
        return FrontContract(
            trade_date=row["trade_date"], contract=row["contract"], adj_offset=row["adj_offset"]
        )

    def to_raw_price(self, level: int, at: int) -> int:
        """A price level of the continuous series, in 1e-9 units, as a raw price of the
        contract that is front at the instant `at` when the order executes: a level decided at
        a bar's close and filled at the next session's open converts at that open."""
        return level - self.front(at).adj_offset

    def continuous_bars(self, bars: pl.DataFrame) -> pl.DataFrame:
        """The bars of each session's front among `bars`, which have the columns of
        `CONTRACT_BAR_COLUMNS`, sorted by `ts_open`, with the columns of `CONTINUOUS_COLUMNS`;
        `roll_flag` marks a bar whose contract is not that of the bar before it, a new front's
        first, which the first bar given never is. Bars of other contracts, and of sessions
        without a row, are left out."""
        source = f"the bars of {self._root} to splice"
        require_columns(CONTRACT_BAR_COLUMNS, bars.schema, source)
        require_bars_apart(bars, source)
        fronts = self._rows.select("trade_date", "contract", "adj_offset")
        spliced = bars.join(fronts, on=["trade_date", "contract"]).sort("ts_open")
        new_front = pl.col("contract") != pl.col("contract").shift(1)
        adjusted = [pl.col(column) + pl.col("adj_offset") for column in _ADJUSTED_COLUMNS]
        return (
            spliced.with_columns(close_raw=pl.col("close"), roll_flag=new_front.fill_null(False))
            .with_columns(adjusted)
            .select(CONTINUOUS_COLUMNS.names())
        )


def volume_rolls(
    bars: pl.DataFrame, sessions: SessionTable, instrument: Instrument, received_until: int
) -> RollCalendar:
    """The default roll calendar of `instrument`'s contracts from their `bars` of any
    timeframe, with the columns of `CONTRACT_BAR_COLUMNS`: the contract that traded most in the
    session before leads, the front never rolls back, and it is forced off a contract at the
    open of its last trade date. Rows run from the second session of the bars to the last
    opening by `received_until`, the instant by which every bar is in hand."""
    grid = decision_grid(bars, sessions, instrument, received_until, sessions_before_expiry=0)
    ranked = grid.with_columns(measure=pl.col("previous_volume").cast(pl.Int64))
    rows = calendar_rows(ranked, bars, RollReason.VOLUME)
    return RollCalendar(instrument.root, rows, received_until)


def open_interest_rolls(
    bars: pl.DataFrame,
    statistics: pl.DataFrame,
    sessions: SessionTable,
    instrument: Instrument,
    received_until: int,
) -> RollCalendar:
    """The roll calendar of `volume_rolls` with the contracts ranked at each open by the open
    interest last received at or before it among their `statistics`, which have the columns of
    `STATISTICS_CONTRACT_COLUMNS`; of figures received at one instant, the last in sequence."""
    source = f"the statistics of {instrument.root}"
    require_columns(STATISTICS_CONTRACT_COLUMNS, statistics.schema, source)
    grid = decision_grid(bars, sessions, instrument, received_until, sessions_before_expiry=0)
    open_interest = (
        statistics.filter(pl.col("stat_type") == _OPEN_INTEREST_STAT_TYPE)
        .sort("ts_recv", "sequence")
        .select("contract", "ts_recv", measure="quantity")
    )
    ranked = (
        grid.sort("session_open")
        .join_asof(
            open_interest,
            left_on="session_open",
            right_on="ts_recv",
            by="contract",
            check_sortedness=False,
        )
        .drop("ts_recv")
    )
    rows = calendar_rows(ranked, bars, RollReason.OPEN_INTEREST)
    return RollCalendar(instrument.root, rows, received_until)


def calendar_rolls(
    bars: pl.DataFrame,
    sessions: SessionTable,
    instrument: Instrument,
    received_until: int,
    sessions_before_expiry: int,
) -> RollCalendar:
    """The roll calendar that keeps the nearest contract that has traded and rolls off it at
    the open of the session `sessions_before_expiry` sessions before its last trade date, 0
    being the last trade date itself, whatever the contracts trade."""
    if sessions_before_expiry < 0:
        raise ValueError(
            f"Expected a number of sessions before expiry of 0 or more, got "
            f"{sessions_before_expiry}."
        )
    grid = decision_grid(bars, sessions, instrument, received_until, sessions_before_expiry)
    unranked = grid.with_columns(measure=pl.lit(None, dtype=pl.Int64))
    rows = calendar_rows(unranked, bars, RollReason.CALENDAR)
    return RollCalendar(instrument.root, rows, received_until)


def back_adjusted(continuous: pl.DataFrame) -> pl.DataFrame:
    """For charts only (ADR-0007): `continuous`, with the columns of `CONTINUOUS_COLUMNS`,
    shifted so that its newest contract shows its raw prices and each older contract is moved
    by the gaps of the rolls after it, with the columns of `BACK_ADJUSTED_COLUMNS`. Each roll
    changes every earlier value of this view, so no signal or feature may read it."""
    require_columns(CONTINUOUS_COLUMNS, continuous.schema, "the continuous bars to back-adjust")
    shifted = continuous
    if not continuous.is_empty():
        newest = continuous.sort("ts_open").item(-1, "adj_offset")
        moved = (*_ADJUSTED_COLUMNS, "adj_offset")
        shifted = continuous.with_columns(pl.col(column) - newest for column in moved)
    return shifted.rename({"adj_offset": "back_adjustment"})
