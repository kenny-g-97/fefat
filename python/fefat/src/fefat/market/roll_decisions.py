"""How a roll calendar decides (`fefat.market.continuous`, D-44): the inputs of each session's
decision, all in hand at its open, the front month a rule gives each session, and the gap of
each roll.

A decision grid holds a row for each session from the second of the bars to the last opening by
`received_until`, and for each contract: the session's open and the next one's, the contract's
month, the trade date from which it may no longer serve a session, its volume in the session
before, and whether it has traded before. The calendar's rows follow from the grid and the rule's
`measure` beside each contract; the gap of a roll is taken from the bars themselves, in the
latest bar both contracts traded in before the roll's session.
"""

from datetime import date, timedelta
from enum import StrEnum

import polars as pl

from fefat.market.bars import BAR_COLUMNS
from fefat.market.calendar import SessionTable, utc_text
from fefat.market.contracts import parse_contract_name
from fefat.market.instruments import Instrument
from fefat.market.layout import YearMonth
from fefat.market.schema import require_columns

CONTRACT_BAR_COLUMNS = pl.Schema({**BAR_COLUMNS, "contract": pl.String})
"""Bars with their contract as a last column, as `Store.scan_contracts` reads them."""
ROLL_CALENDAR_COLUMNS = pl.Schema(
    {
        "trade_date": pl.Date,
        "session_open": pl.Int64,
        "next_open": pl.Int64,
        "contract": pl.String,
        "adj_offset": pl.Int64,
        "rolled_from": pl.String,
        "gap": pl.Int64,
        "reason": pl.String,
    }
)
"""A roll calendar's row per session: its trade date, its open and the next session's, until
which its front contract holds, and the offset added to that contract's raw prices; at a roll,
the contract rolled from, the gap, and the `RollReason`, null on other rows."""

_CONTRACT_COLUMNS = pl.Schema(
    {"contract": pl.String, "month_index": pl.Int32, "serves_until": pl.Date}
)


class RollReason(StrEnum):
    """Why the front passed to a new contract: its rule's leader, or its last trade date."""

    VOLUME = "volume"
    OPEN_INTEREST = "open-interest"
    CALENDAR = "calendar"
    EXPIRY = "expiry"


def decision_grid(
    bars: pl.DataFrame,
    sessions: SessionTable,
    instrument: Instrument,
    received_until: int,
    sessions_before_expiry: int,
) -> pl.DataFrame:
    """A row for each session from the second of `bars` to the last opening by
    `received_until` and each contract: the session's open and the next one's, the contract's
    `month_index` and `serves_until`, its volume in the session before (null without bars),
    and whether it traded in a session before (`has_traded`). A bar closing after the open of
    the session after its trade date, where a decision reads it (D-43), is refused."""
    require_columns(CONTRACT_BAR_COLUMNS, bars.schema, f"the bars of {instrument.root}")
    if bars.is_empty():
        raise ValueError(f"Expected bars of at least one contract of {instrument.root}, got none.")
    first: date = bars.select(pl.col("trade_date").min()).item()
    last = _last_session_by(sessions, received_until)
    in_range = sessions.between(first, last).select(
        "trade_date",
        session_open="open",
        next_open=pl.col("open").shift(-1).fill_null(sessions.following(last).open),
    )
    _require_bars_closing_by_the_next_open(bars, in_range)
    contracts = _contracts(bars, instrument, sessions, sessions_before_expiry, last)
    volumes = bars.group_by("trade_date", "contract").agg(pl.col("volume").sum())
    traded = pl.col("volume").is_not_null().cum_max()
    return (
        in_range.join(contracts, how="cross")
        .join(volumes, on=["trade_date", "contract"], how="left")
        .sort("contract", "trade_date")
        .with_columns(
            previous_volume=pl.col("volume").shift(1).over("contract"),
            has_traded=traded.shift(1, fill_value=False).over("contract"),
        )
        .filter(pl.col("trade_date") > first)
        .drop("volume")
    )


def calendar_rows(grid: pl.DataFrame, bars: pl.DataFrame, ranked_by: RollReason) -> pl.DataFrame:
    """The roll calendar's rows, with the columns of `ROLL_CALENDAR_COLUMNS`, from a decision
    grid with the rule's `measure` beside each contract, null where it ranks none: a roll's
    reason is `ranked_by` where the rule's leader set the new front, else the last trade date's
    (`CALENDAR` for the calendar rule, which ranks nothing)."""
    names = grid.select("contract", "month_index").unique()
    fronts = _fronts(grid).join(names, left_on="front_month", right_on="month_index")
    forced_by = RollReason.CALENDAR if ranked_by is RollReason.CALENDAR else RollReason.EXPIRY
    return _with_rolls(fronts.sort("trade_date"), bars, ranked_by, forced_by)


def _last_session_by(sessions: SessionTable, instant: int) -> date:
    """The trade date of the last session opening at or before `instant`."""
    at = pl.DataFrame({"instant": [instant]}, schema={"instant": pl.Int64})
    return sessions.assign_trade_dates_or_previous(at, "instant").item(0, "trade_date")


def _require_bars_closing_by_the_next_open(bars: pl.DataFrame, in_range: pl.DataFrame) -> None:
    """Refuse a bar closing after the open of the session after its trade date, as a coarse bar
    straddling a break would."""
    next_opens = in_range.select("trade_date", "next_open")
    late = bars.join(next_opens, on="trade_date").filter(pl.col("ts_close") > pl.col("next_open"))
    if late.is_empty():
        return
    first = late.sort("ts_open").select("contract", "trade_date", "ts_close", "next_open").row(0)
    contract, trade_date, ts_close, next_open = first
    raise ValueError(
        f"Expected every bar to close by the open of the session after its trade date, where a "
        f"roll decision reads it, got {late.height} closing later, the first of {contract} "
        f"dated {trade_date} closing at {utc_text(ts_close)}, after {utc_text(next_open)}."
    )


def _contracts(
    bars: pl.DataFrame,
    instrument: Instrument,
    sessions: SessionTable,
    sessions_before_expiry: int,
    last: date,
) -> pl.DataFrame:
    """Each contract of `bars` with the index of its month, by which no roll goes back, and the
    trade date from which it may no longer serve a session (`serves_until`): its last trade
    date, or the trade date `sessions_before_expiry` sessions before it; null for a contract
    whose month begins too late for that date to fall by `last`."""
    rows: list[tuple[str, int, date | None]] = []
    for contract in bars.get_column("contract").unique().sort().to_list():
        root, month = parse_contract_name(contract)
        if root != instrument.root:
            raise ValueError(f"Expected contracts of {instrument.root}, got {contract}.")
        serves_until = None
        if _may_stop_serving_by(month, last, sessions_before_expiry):
            last_trade_date = instrument.last_trade_date(month, sessions)
            serves_until = _sessions_before(sessions, last_trade_date, sessions_before_expiry)
        rows.append((contract, month.year * 12 + month.month - 1, serves_until))
    return pl.DataFrame(rows, schema=_CONTRACT_COLUMNS, orient="row")


def _may_stop_serving_by(month: YearMonth, last: date, sessions_before_expiry: int) -> bool:
    """Whether a contract of `month` can stop serving by `last`: every last-trade rule falls on
    or after the first day of the month before, and `sessions_before_expiry` sessions span at
    most 2·count + 14 days."""
    margin = timedelta(days=31 + 2 * sessions_before_expiry + 14)
    return date(month.year, month.month, 1) - margin <= last


def _sessions_before(sessions: SessionTable, trade_date: date, count: int) -> date:
    """The trade date `count` sessions before the trade date `trade_date`, itself for none: a
    window of 2·count + 14 days holds more than `count` trade dates, five in seven days less a
    few holidays."""
    lead_in = timedelta(days=2 * count + 14)
    trade_dates = sessions.between(trade_date - lead_in, trade_date).get_column("trade_date")
    return trade_dates[-1 - count]


def _fronts(grid: pl.DataFrame) -> pl.DataFrame:
    """Each session's front month: the latest month that has led so far, or the nearest month
    that has traded and may serve the session when it is later, and never earlier than the
    front before; sessions that no month may serve are left out."""
    serves = pl.col("serves_until").is_null() | (pl.col("trade_date") < pl.col("serves_until"))
    may_serve = pl.col("has_traded") & serves
    month = pl.col("month_index")
    by_rank = grid.sort(
        ["trade_date", "measure", "month_index"], descending=[False, True, False], nulls_last=True
    )
    return (
        by_rank.group_by("trade_date", maintain_order=True)
        .agg(
            pl.col("session_open").first(),
            pl.col("next_open").first(),
            leader=month.filter(pl.col("measure").is_not_null() & pl.col("has_traded")).first(),
            nearest=month.filter(may_serve).min(),
        )
        .with_columns(led=pl.col("leader").cum_max().forward_fill())
        .filter(pl.col("nearest").is_not_null())
        .with_columns(front_month=pl.max_horizontal("led", "nearest").cum_max())
    )


def _with_rolls(
    fronts: pl.DataFrame, bars: pl.DataFrame, ranked_by: RollReason, forced_by: RollReason
) -> pl.DataFrame:
    """The calendar's rows from the fronts, sorted by trade date: where the front changes, the
    contract rolled from, the gap, and the reason; `adj_offset` falls by each gap."""
    previous = pl.col("contract").shift(1)
    named = fronts.with_columns(rolled_from=pl.when(previous != pl.col("contract")).then(previous))
    gaps = _gaps(named.filter(pl.col("rolled_from").is_not_null()), bars)
    reason = (
        pl.when(pl.col("led") == pl.col("front_month"))
        .then(pl.lit(ranked_by.value))
        .otherwise(pl.lit(forced_by.value))
    )
    return (
        named.join(gaps, on="trade_date", how="left")
        .sort("trade_date")
        .with_columns(reason=pl.when(pl.col("rolled_from").is_not_null()).then(reason))
        .with_columns(adj_offset=-pl.col("gap").fill_null(0).cum_sum())
        .select(ROLL_CALENDAR_COLUMNS.names())
    )


def _gaps(rolls: pl.DataFrame, bars: pl.DataFrame) -> pl.DataFrame:
    """Each roll's `gap`, by its trade date: the new contract's close minus the old one's in the
    latest bar, by `ts_open`, that both traded in before the roll's session. A roll without one
    is refused, since closes of different times would put the market's move into the gap."""
    keys = rolls.select("trade_date", "rolled_from", "contract")
    closes = bars.select("contract", "ts_open", "close", bar_date="trade_date")
    before_the_roll = pl.col("bar_date") < pl.col("trade_date")
    old = keys.join(closes, left_on="rolled_from", right_on="contract").filter(before_the_roll)
    new = keys.join(closes, on="contract").filter(before_the_roll)
    both = old.join(
        new.select("trade_date", "ts_open", new_close="close"), on=["trade_date", "ts_open"]
    )
    gap = (pl.col("new_close") - pl.col("close")).sort_by("ts_open").last()
    gaps = both.group_by("trade_date").agg(gap=gap)
    missing = keys.join(gaps, on="trade_date", how="anti").sort("trade_date")
    if not missing.is_empty():
        trade_date, rolled_from, contract = missing.row(0)
        raise ValueError(
            f"Expected a bar in which both {rolled_from} and {contract} traded before the "
            f"session of {trade_date}, to measure the gap of the roll between them, got none."
        )
    return gaps
