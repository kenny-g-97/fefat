"""Continuous futures bars for signals, forward-anchored, and the roll calendar that splices them
from a root's contracts (`02-engine-and-data.md` §1.5, D-09).

Why forward anchoring (ADR-0007, `docs/adr/0007-forward-anchored-continuous-series.md`): a
back-adjusted series shifts every earlier price at each roll, so a value a feature computed
yesterday changes today, its cache goes stale, and the leak detector, which recomputes on
truncated data and requires every value before a cut to stay the same (ADR-0010), flags honest
features. Here history never changes: the first contract keeps its raw prices, and at each roll
the new contract is shifted by the gap between the two contracts' closes so that it joins the
old series. Orders execute on the real contract at its raw prices, so a price level read on the
series converts back through `RollCalendar.to_raw_price`; a back-adjusted view, which ends at
the newest contract's raw prices, is for charts only (`back_adjusted`).

The roll calendar decides the front contract of each session `d` from what is known at its
open: each contract's volume and last close through the session before, `d-1`, whose prints are
all in hand by then (D-43). The default rule, `volume_rolls`: the contract that traded most in
`d-1` leads; the front never rolls back to an earlier month, so it is the latest month that has
led so far; and it is forced off a contract at the open of its last trade date
(`fefat.market.last_trade_rules`), inside whose session the contract stops trading, onto the
nearest later month with a price. `open_interest_rolls` leads by the open interest last
received by each open, and `calendar_rolls` rolls a set number of sessions before the last
trade date. The first session of the data has no decision, and a session that no contract may
serve has no row.

At a roll from A to B at the open of `d`, the gap is B's last close through `d-1` minus A's,
and `adj_offset` falls by it: adjusted prices are raw prices plus `adj_offset`, 0 for the first
contract, so B's last close before the roll, adjusted, equals A's. `RollCalendar.rolls` lists the
rolls, at whose opens the engine transfers a position held across them (step 2.9), and
`continuous_bars` keeps the front's bars of each session with adjusted prices, `close_raw`,
`adj_offset`, and `roll_flag` on the new front's first bar of a roll session. No row or bar
depends on later data: those by any instant are the same when the data stops there (D-12).

    mes = instruments.get("MES")
    sessions = sessions_of(BUILT_IN[mes.calendar_id], paths.cache_dir)
    bars = store.scan_contracts(request).collect()
    calendar = volume_rolls(bars, sessions, mes, sessions.following(request.end).open)
    signal_bars = calendar.continuous_bars(bars)
"""

from datetime import date, timedelta
from enum import StrEnum

import polars as pl

from fefat.market.bars import BAR_COLUMNS
from fefat.market.calendar import SessionTable, utc_text
from fefat.market.contracts import parse_contract_name
from fefat.market.instruments import Instrument
from fefat.market.schema import FrozenModel, parse_schema_name, polars_schema, require_columns

CONTRACT_BAR_COLUMNS = pl.Schema({**BAR_COLUMNS, "contract": pl.String})
"""Bars with their contract as a last column, as `Store.scan_contracts` reads them."""
STATISTICS_CONTRACT_COLUMNS = pl.Schema(
    {**polars_schema(parse_schema_name("statistics")), "contract": pl.String}
)
"""Statistics with their contract as a last column, as `Store.scan_contracts` reads them."""
ROLL_CALENDAR_COLUMNS = pl.Schema(
    {
        "trade_date": pl.Date,
        "session_open": pl.Int64,
        "contract": pl.String,
        "adj_offset": pl.Int64,
        "rolled_from": pl.String,
        "gap": pl.Int64,
        "reason": pl.String,
    }
)
"""A roll calendar's row per session: its trade date and open, its front contract, and the
offset added to that contract's raw prices; at a roll, the contract rolled from, the gap between
the two contracts' last closes before the session, and the `RollReason`, null on other rows."""
CONTINUOUS_COLUMNS = pl.Schema(
    {**CONTRACT_BAR_COLUMNS, "close_raw": pl.Int64, "adj_offset": pl.Int64, "roll_flag": pl.Boolean}
)
"""Continuous bars: a bar's columns with open, high, low, close, and vwap adjusted, the front
contract, its raw close, the offset, and whether the bar is the first of a new front."""

_OPEN_INTEREST_STAT_TYPE = 9
"""The `stat_type` of open interest in the statistics schema (`fefat.market.schema`)."""
_ADJUSTED_COLUMNS = ("open", "high", "low", "close", "vwap")
_CONTRACT_COLUMNS = pl.Schema(
    {"contract": pl.String, "month_index": pl.Int32, "serves_until": pl.Date}
)


class RollReason(StrEnum):
    """Why the front passed to a new contract: its rule's leader, or its last trade date."""

    VOLUME = "volume"
    OPEN_INTEREST = "open-interest"
    CALENDAR = "calendar"
    EXPIRY = "expiry"


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
        `rolled_from` to `contract`, whose last closes before it differ by `gap`, for `reason`;
        a position held across the roll is transferred there (step 2.9)."""
        return self._rows.filter(pl.col("rolled_from").is_not_null()).select(
            "trade_date", "session_open", "rolled_from", "contract", "gap", "reason"
        )

    def front(self, at: int) -> FrontContract:
        """The front contract at the instant `at`: that of the last session opening at or
        before it. An instant before the first session, or after `received_until`, when the
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
        row = self._rows.filter(pl.col("session_open") <= at).row(-1, named=True)
        return FrontContract(
            trade_date=row["trade_date"], contract=row["contract"], adj_offset=row["adj_offset"]
        )

    def to_raw_price(self, level: int, at: int) -> int:
        """A price level of the continuous series at the instant `at`, in 1e-9 units, as the raw
        price of the front contract then, on which an order executes."""
        return level - self.front(at).adj_offset

    def continuous_bars(self, bars: pl.DataFrame) -> pl.DataFrame:
        """The bars of each session's front among `bars`, which have the columns of
        `CONTRACT_BAR_COLUMNS`, sorted by `ts_open`, with the columns of `CONTINUOUS_COLUMNS`.
        Bars of other contracts, and of sessions without a row, are left out."""
        require_columns(CONTRACT_BAR_COLUMNS, bars.schema, f"the bars of {self._root} to splice")
        fronts = self._rows.select(
            "trade_date", "contract", "adj_offset", rolled=pl.col("rolled_from").is_not_null()
        )
        first_of_its_session = pl.col("ts_open") == pl.col("ts_open").min().over("trade_date")
        spliced = bars.join(fronts, on=["trade_date", "contract"]).with_columns(
            close_raw=pl.col("close"), roll_flag=pl.col("rolled") & first_of_its_session
        )
        adjusted = [pl.col(column) + pl.col("adj_offset") for column in _ADJUSTED_COLUMNS]
        return spliced.with_columns(adjusted).sort("ts_open").select(CONTINUOUS_COLUMNS.names())


def volume_rolls(
    bars: pl.DataFrame, sessions: SessionTable, instrument: Instrument, received_until: int
) -> RollCalendar:
    """The default roll calendar of `instrument`'s contracts from their `bars` of any
    timeframe, with the columns of `CONTRACT_BAR_COLUMNS`: the contract that traded most in the
    session before leads, the front never rolls back, and it is forced off a contract at the
    open of its last trade date. Rows run to the last session opening by `received_until`, the
    instant by which every bar is in hand."""
    grid = _decision_grid(bars, sessions, instrument, received_until, sessions_before_expiry=0)
    ranked = grid.with_columns(measure=pl.col("previous_volume").cast(pl.Int64))
    return _calendar(instrument.root, ranked, received_until, RollReason.VOLUME)


def open_interest_rolls(
    bars: pl.DataFrame,
    statistics: pl.DataFrame,
    sessions: SessionTable,
    instrument: Instrument,
    received_until: int,
) -> RollCalendar:
    """The roll calendar of `volume_rolls` with the contracts ranked at each open by the open
    interest last received by then among their `statistics`, which have the columns of
    `STATISTICS_CONTRACT_COLUMNS`."""
    source = f"the statistics of {instrument.root}"
    require_columns(STATISTICS_CONTRACT_COLUMNS, statistics.schema, source)
    grid = _decision_grid(bars, sessions, instrument, received_until, sessions_before_expiry=0)
    open_interest = (
        statistics.filter(pl.col("stat_type") == _OPEN_INTEREST_STAT_TYPE)
        .select("contract", "ts_recv", measure="quantity")
        .sort("ts_recv")
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
    return _calendar(instrument.root, ranked, received_until, RollReason.OPEN_INTEREST)


def calendar_rolls(
    bars: pl.DataFrame,
    sessions: SessionTable,
    instrument: Instrument,
    received_until: int,
    sessions_before_expiry: int,
) -> RollCalendar:
    """The roll calendar that keeps the nearest contract with a price and rolls off it at the
    open of the session `sessions_before_expiry` sessions before its last trade date, 0 being
    the last trade date itself, whatever the contracts trade."""
    if sessions_before_expiry < 0:
        raise ValueError(
            f"Expected a number of sessions before expiry of 0 or more, got "
            f"{sessions_before_expiry}."
        )
    grid = _decision_grid(bars, sessions, instrument, received_until, sessions_before_expiry)
    unranked = grid.with_columns(measure=pl.lit(None, dtype=pl.Int64))
    return _calendar(instrument.root, unranked, received_until, RollReason.CALENDAR)


def back_adjusted(continuous: pl.DataFrame) -> pl.DataFrame:
    """For charts only (ADR-0007): `continuous`, with the columns of `CONTINUOUS_COLUMNS`,
    shifted so that its newest contract shows its raw prices and each older contract is moved
    by the gaps of the rolls after it, `adj_offset` alike. Each roll changes every earlier value
    of this view, so no signal or feature may read it."""
    require_columns(CONTINUOUS_COLUMNS, continuous.schema, "the continuous bars to back-adjust")
    if continuous.is_empty():
        return continuous
    newest = continuous.sort("ts_open").item(-1, "adj_offset")
    return continuous.with_columns(
        pl.col(column) - newest for column in (*_ADJUSTED_COLUMNS, "adj_offset")
    )


def _decision_grid(
    bars: pl.DataFrame,
    sessions: SessionTable,
    instrument: Instrument,
    received_until: int,
    sessions_before_expiry: int,
) -> pl.DataFrame:
    """A row for each session after the first of `bars` that opens by `received_until` and
    each contract: the session's open, the contract's `month_index` and `serves_until`, and its
    volume in the session before and last close through it, null where it has none."""
    require_columns(CONTRACT_BAR_COLUMNS, bars.schema, f"the bars of {instrument.root}")
    if bars.is_empty():
        raise ValueError(f"Expected bars of at least one contract of {instrument.root}, got none.")
    contracts = _contracts(bars, instrument, sessions, sessions_before_expiry)
    dates = pl.col("trade_date")
    first, last = bars.select(first=dates.min(), last=dates.max()).row(0)
    in_range = sessions.between(first, sessions.following(last).trade_date).select(
        "trade_date", session_open="open"
    )
    per_session = bars.group_by("trade_date", "contract").agg(
        volume=pl.col("volume").sum(), close=pl.col("close").sort_by("ts_open").last()
    )
    return (
        in_range.join(contracts, how="cross")
        .join(per_session, on=["trade_date", "contract"], how="left")
        .sort("contract", "trade_date")
        .with_columns(
            previous_volume=pl.col("volume").shift(1).over("contract"),
            reference_close=pl.col("close").forward_fill().shift(1).over("contract"),
        )
        .filter(dates > first, pl.col("session_open") <= received_until)
        .drop("volume", "close")
    )


def _contracts(
    bars: pl.DataFrame, instrument: Instrument, sessions: SessionTable, sessions_before_expiry: int
) -> pl.DataFrame:
    """Each contract of `bars` with the index of its month, by which no roll goes back, and the
    trade date from which it may no longer serve a session (`serves_until`): its last trade
    date, or the trade date `sessions_before_expiry` sessions before it."""
    rows: list[tuple[str, int, date]] = []
    for contract in bars.get_column("contract").unique().sort().to_list():
        root, month = parse_contract_name(contract)
        if root != instrument.root:
            raise ValueError(f"Expected contracts of {instrument.root}, got {contract}.")
        last_trade_date = instrument.last_trade_date(month, sessions)
        serves_until = _sessions_before(sessions, last_trade_date, sessions_before_expiry)
        rows.append((contract, month.year * 12 + month.month - 1, serves_until))
    return pl.DataFrame(rows, schema=_CONTRACT_COLUMNS, orient="row")


def _sessions_before(sessions: SessionTable, trade_date: date, count: int) -> date:
    """The trade date `count` sessions before `trade_date`, itself for none."""
    lead_in = timedelta(days=2 * count + 14)
    trade_dates = sessions.between(trade_date - lead_in, trade_date).get_column("trade_date")
    return trade_dates[-1 - count]


def _calendar(
    root: str, grid: pl.DataFrame, received_until: int, ranked_by: RollReason
) -> RollCalendar:
    """The roll calendar of a decision grid with the rule's `measure` beside each contract."""
    names = grid.select("contract", "month_index").unique()
    fronts = _fronts(grid).join(names, left_on="front_month", right_on="month_index")
    forced_by = RollReason.CALENDAR if ranked_by is RollReason.CALENDAR else RollReason.EXPIRY
    rows = _with_rolls(fronts.sort("trade_date"), grid, ranked_by, forced_by)
    return RollCalendar(root, rows, received_until)


def _fronts(grid: pl.DataFrame) -> pl.DataFrame:
    """Each session's front month: the latest month that has led so far, or the nearest month
    with a price that may serve the session when it is later, and never earlier than the front
    before; sessions that no month may serve are left out."""
    priced = pl.col("reference_close").is_not_null()
    may_serve = priced & (pl.col("trade_date") < pl.col("serves_until"))
    month = pl.col("month_index")
    by_rank = grid.sort(
        ["trade_date", "measure", "month_index"], descending=[False, True, False], nulls_last=True
    )
    return (
        by_rank.group_by("trade_date", maintain_order=True)
        .agg(
            pl.col("session_open").first(),
            leader=month.filter(pl.col("measure").is_not_null() & priced).first(),
            nearest=month.filter(may_serve).min(),
        )
        .with_columns(led=pl.col("leader").cum_max().forward_fill())
        .filter(pl.col("nearest").is_not_null())
        .with_columns(front_month=pl.max_horizontal("led", "nearest").cum_max())
    )


def _with_rolls(
    fronts: pl.DataFrame, grid: pl.DataFrame, ranked_by: RollReason, forced_by: RollReason
) -> pl.DataFrame:
    """The calendar's rows from the fronts, sorted by trade date: where the front changes, the
    contract rolled from, the gap between the two contracts' last closes before the session,
    and the reason, the rule's own where its leader set the new front; `adj_offset` falls by
    each gap."""
    closes = grid.select("trade_date", "contract", "reference_close")
    rolled_closes = closes.rename(
        {"contract": "rolled_from", "reference_close": "rolled_from_close"}
    )
    previous = pl.col("contract").shift(1)
    reason = (
        pl.when(pl.col("led") == pl.col("front_month"))
        .then(pl.lit(ranked_by.value))
        .otherwise(pl.lit(forced_by.value))
    )
    return (
        fronts.with_columns(rolled_from=pl.when(previous != pl.col("contract")).then(previous))
        .join(closes, on=["trade_date", "contract"], how="left")
        .join(rolled_closes, on=["trade_date", "rolled_from"], how="left")
        .sort("trade_date")
        .with_columns(
            gap=pl.col("reference_close") - pl.col("rolled_from_close"),
            reason=pl.when(pl.col("rolled_from").is_not_null()).then(reason),
        )
        .with_columns(adj_offset=-pl.col("gap").fill_null(0).cum_sum())
        .select(ROLL_CALENDAR_COLUMNS.names())
    )
