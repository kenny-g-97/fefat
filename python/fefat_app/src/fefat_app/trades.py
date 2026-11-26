"""A saved run's trades as the API shows them (step 5.8, D-124): which trades a table asks for, its
filters and its order, and the cursor where its last page ended; a row of the trades artifact as
a reader of its Parquet gives it, in the engines' units, and as the API sends it, in the
instrument's (the phase's conventions: instants as ISO 8601 in UTC, prices and money as decimal
text); a page of them; the answer to the trader's SELECT over the run's artifacts; and a file the
run exports. Frozen models, as at every boundary, kept apart from the port in `fefat_app.ports`
and from the adapter that reads the Parquet, `fefat_app.artifact_queries`."""

import base64
import binascii
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, model_validator

from fefat.market.calendar import utc_text
from fefat.market.engine_units import PRICE_DECIMALS, money_text, price_text
from fefat.market.fidelity import FidelityText
from fefat.reference.orders import OrderRole, PositionSide

_NANOSECONDS_A_MINUTE = 60_000_000_000


class TradeSort(StrEnum):
    """What the trades are ordered by: the entry's or the exit's instant, the net P&L, the R
    multiple, none without a stop, the time held, or the adverse or the favourable excursion in
    ticks; each a column of `RawTrade`."""

    ENTRY_TS = "entry_ts"
    EXIT_TS = "exit_ts"
    PNL = "pnl"
    R_MULTIPLE = "r_multiple"
    HELD = "held"
    MAE_TICKS = "mae_ticks"
    MFE_TICKS = "mfe_ticks"


class SortOrder(StrEnum):
    """Lowest first or highest first, a trade without the sort's figure last either way."""

    ASC = "asc"
    DESC = "desc"


class PnlSign(StrEnum):
    """The trades whose net P&L is above zero, below it, or zero (`02` §7: a win is above zero,
    a loss below)."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    ZERO = "zero"


class TradeFilters(BaseModel):
    """Which of a run's trades to show, each filter left out keeping every trade: a side, an exit
    reason, the trade dates of the entry from `start` to `end`, the sign of the net P&L, the
    fidelity of the entry's fill, and whether a fill of the trade's path is ambiguous (F-BAR-05)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    side: PositionSide | None = None
    exit_reason: OrderRole | None = None
    start: date | None = None
    end: date | None = None
    pnl_sign: PnlSign | None = None
    fidelity: FidelityText | None = None
    ambiguous: bool | None = None

    @model_validator(mode="after")
    def _start_on_or_before_its_end(self) -> Self:
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError(
                f"Expected the start {self.start} on or before the end, got the end {self.end}."
            )
        return self


class TradesShown(TradeFilters):
    """The trades a table shows: those its filters keep, in its order, ties by their row."""

    sort: TradeSort = TradeSort.ENTRY_TS
    order: SortOrder = SortOrder.ASC


class TradeCursorError(ValueError):
    """A cursor no page of the run's trades gave, or one of another order than the one asked."""


class RawTrade(BaseModel):
    """A row of a run's trades artifact as its Parquet holds it, in the engines' units, with its
    row from 0, which its path names, its time held in nanoseconds, its entry order's first
    fill's fidelity, as the metrics' fidelity breakdown counts it, and whether a fill of its path
    is ambiguous; each `TradeSort` one of its columns."""

    model_config = ConfigDict(frozen=True)

    trade: int = Field(ge=0)
    side: PositionSide
    lots: int
    entry_order: int
    entry_decision: int
    entry_ts: int
    entry_price: int
    entry_contract: str
    exits: int
    exit_price: float | None
    exit_ts: int
    exit_reason: OrderRole
    exit_contract: str
    rolls: int
    gross_pnl: int
    fees: int
    funding: int
    pnl: int
    initial_risk_ticks: int | None
    mae_ticks: int
    mfe_ticks: int
    mae: int
    mfe: int
    max_drawdown_ticks: int
    max_drawdown: int
    path_fidelity: FidelityText
    entry_trade_date: date
    initial_risk: int | None
    r_multiple: float | None
    mae_r: float | None
    mfe_r: float | None
    held: int
    fidelity: FidelityText
    ambiguous: bool

    def sort_value(self, sort: TradeSort) -> int | float | None:
        """The trade's figure that `sort` orders by."""
        match sort:
            case TradeSort.ENTRY_TS:
                return self.entry_ts
            case TradeSort.EXIT_TS:
                return self.exit_ts
            case TradeSort.PNL:
                return self.pnl
            case TradeSort.R_MULTIPLE:
                return self.r_multiple
            case TradeSort.HELD:
                return self.held
            case TradeSort.MAE_TICKS:
                return self.mae_ticks
            case TradeSort.MFE_TICKS:
                return self.mfe_ticks


RAW_TRADE_COLUMNS = tuple(name for name in RawTrade.model_fields if name != "ambiguous")
"""The columns a reader selects of a run's trades, every column of `RawTrade` but the flag it may
work out apart, for a page's trades alone."""


class TradeCursor(BaseModel):
    """Where a page of a run's trades ended: the order it was read in, and its last trade's
    figure of the sort, None where the trade has none, and its row; written as URL-safe base64 of
    its JSON (`text`, `read`)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sort: TradeSort
    order: SortOrder
    value: int | float | None
    trade: int = Field(ge=0)

    @classmethod
    def after(cls, last: RawTrade, shown: TradesShown) -> Self:
        """The cursor of the page that ends on `last`, read as `shown` orders the trades."""
        return cls(
            sort=shown.sort, order=shown.order, value=last.sort_value(shown.sort), trade=last.trade
        )

    @classmethod
    def read(cls, text: str, shown: TradesShown) -> Self:
        """The cursor `text` gives, which must be of the order `shown` asks; `TradeCursorError`
        for one no page gave, or one of another order."""
        try:
            cursor = cls.model_validate_json(base64.urlsafe_b64decode(text.encode()))
        except (binascii.Error, ValidationError, UnicodeEncodeError):
            raise TradeCursorError(
                f"Expected a cursor that a page of the run's trades gave, got {text!r}."
            ) from None
        if (cursor.sort, cursor.order) != (shown.sort, shown.order):
            raise TradeCursorError(
                f"Expected a cursor of the trades by {shown.sort} {shown.order}, got one by "
                f"{cursor.sort} {cursor.order}: ask for the first page again."
            )
        return cursor

    def text(self) -> str:
        return base64.urlsafe_b64encode(self.model_dump_json().encode()).decode()


class TradesAsked(BaseModel):
    """What a reader of a run's trades is asked for: the trades `shown` keeps, in its order,
    after the trade `after` ends on, at most `limit` of them, or all where `limit` is None, as an
    export reads them."""

    model_config = ConfigDict(frozen=True)

    shown: TradesShown
    after: TradeCursor | None
    limit: int | None = Field(ge=1)


class RawTrades(BaseModel):
    """The trades a reader found for `TradesAsked`, whether more follow them, and how many trades
    the filters keep in all."""

    model_config = ConfigDict(frozen=True)

    rows: tuple[RawTrade, ...]
    more: bool
    total: int = Field(ge=0)


def _money(units: int) -> Decimal:
    return Decimal(money_text(units))


def _averaged_price(units: float) -> Decimal:
    """A price in 1e-9 units that an average of exits made a float, as the decimal of its
    shortest digits, such as 5000.083333333333."""
    scaled = Decimal(repr(units)).scaleb(-PRICE_DECIMALS).normalize()
    return Decimal(format(scaled, "f"))


class TradeRow(BaseModel):
    """A trade of a run as the table and its export show it (step 5.8): its row in the trades
    artifact, which its path names, and its entry order, the trade's id for `Run.explain` (step
    5.9); every column of the artifact but the strategy's features, its instants as ISO 8601 in
    UTC, its prices as decimal text in the instrument's units and its money in the run's
    currency, its time held in minutes, and its R figures None without a stop; its entry order's
    first fill's fidelity; and whether a fill of its path is ambiguous."""

    model_config = ConfigDict(frozen=True)

    trade: int
    entry_order: int
    side: PositionSide
    lots: int
    entry_trade_date: date
    entry_decision: str
    entry_ts: str
    entry_price: Decimal
    entry_contract: str
    exit_ts: str
    exit_price: Decimal | None
    exit_reason: OrderRole
    exit_contract: str
    exits: int
    rolls: int
    held_minutes: float
    pnl: Decimal
    gross_pnl: Decimal
    fees: Decimal
    funding: Decimal
    initial_risk_ticks: int | None
    initial_risk: Decimal | None
    r_multiple: float | None
    mae_ticks: int
    mfe_ticks: int
    mae: Decimal
    mfe: Decimal
    mae_r: float | None
    mfe_r: float | None
    max_drawdown_ticks: int
    max_drawdown: Decimal
    fidelity: FidelityText
    path_fidelity: FidelityText
    ambiguous: bool

    @classmethod
    def of(cls, raw: RawTrade) -> Self:
        """The trade `raw` in the instrument's units, each conversion the SDK's own."""
        return cls(
            trade=raw.trade,
            entry_order=raw.entry_order,
            side=raw.side,
            lots=raw.lots,
            entry_trade_date=raw.entry_trade_date,
            entry_decision=utc_text(raw.entry_decision),
            entry_ts=utc_text(raw.entry_ts),
            entry_price=Decimal(price_text(raw.entry_price)),
            entry_contract=raw.entry_contract,
            exit_ts=utc_text(raw.exit_ts),
            exit_price=None if raw.exit_price is None else _averaged_price(raw.exit_price),
            exit_reason=raw.exit_reason,
            exit_contract=raw.exit_contract,
            exits=raw.exits,
            rolls=raw.rolls,
            held_minutes=raw.held / _NANOSECONDS_A_MINUTE,
            pnl=_money(raw.pnl),
            gross_pnl=_money(raw.gross_pnl),
            fees=_money(raw.fees),
            funding=_money(raw.funding),
            initial_risk_ticks=raw.initial_risk_ticks,
            initial_risk=None if raw.initial_risk is None else _money(raw.initial_risk),
            r_multiple=raw.r_multiple,
            mae_ticks=raw.mae_ticks,
            mfe_ticks=raw.mfe_ticks,
            mae=_money(raw.mae),
            mfe=_money(raw.mfe),
            mae_r=raw.mae_r,
            mfe_r=raw.mfe_r,
            max_drawdown_ticks=raw.max_drawdown_ticks,
            max_drawdown=_money(raw.max_drawdown),
            fidelity=raw.fidelity,
            path_fidelity=raw.path_fidelity,
            ambiguous=raw.ambiguous,
        )


class TradePage(BaseModel):
    """A page of a run's trades (step 5.8): its trades, the cursor of the next page, None on the
    last, and how many trades the filters keep in all."""

    model_config = ConfigDict(frozen=True)

    trades: tuple[TradeRow, ...]
    next_cursor: str | None
    total: int


class QueryRefusedError(Exception):
    """A query over a run's artifacts that FEAT does not run, or that DuckDB refused, in words
    that say what to change: not one SELECT, a SELECT DuckDB refuses, or an answer past its rows,
    its bytes, or its time."""


class QueryColumn(BaseModel):
    """A column of a query's answer, named and typed as DuckDB gives it, such as `DECIMAL(29,9)`."""

    model_config = ConfigDict(frozen=True)

    name: str
    type: str


class QueryAnswer(BaseModel):
    """What one SELECT over a run's artifacts answered (step 5.8): its columns, and its rows,
    each a value a column, an instant as ISO 8601 text in UTC, a decimal as its text, and a whole
    number past 2^53, or a float that is no number, as text, so that none changes in a browser."""

    model_config = ConfigDict(frozen=True)

    columns: tuple[QueryColumn, ...]
    rows: tuple[tuple[JsonValue, ...], ...]


@dataclass(frozen=True)
class ExportedFile:
    """A file a run exports (step 5.8, D-119): its name, named by the strategy, the run key's
    first twelve digits, and what it holds, and its text, a CSV."""

    name: str
    text: str
