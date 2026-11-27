"""The trade review's models (step 5.9, D-93): a page of a saved run's chart, its bars at the
prices each contract traded at, the strategy's features beside them, and the trades the page
shows with their fills on its bars and their stop and target levels; and a trade's explanation,
an `explain` job's payload and its result, the trade replayed through the reference engine as a
timeline of its events and its fills, or the replay's refusal in its words. The API sends no
int64, an instant as ISO 8601 in UTC, a bar's open in whole seconds, and a price as decimal
text."""

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from fefat.backtest.record import Hash
from fefat.market.fidelity import FidelityText
from fefat.reference.event_log import EventKind
from fefat.reference.orders import OrderRole, PositionSide, Side
from fefat_app.services.market_bars import BarsPage


class FeatureUnit(StrEnum):
    """How a feature's values read: `price`, in the instrument's units, as the distance the
    strategy's exit rules read it as, such as an ATR; or `as_stored`, as the run's signals hold
    it, since nothing says which other features are prices (the builder's answer at the plan)."""

    PRICE = "price"
    AS_STORED = "as_stored"


class ChartFeature(BaseModel):
    """One of the strategy's features beside the page's bars: its column's name, how its values
    read, and its value at each bar's close, none where the signals hold none."""

    model_config = ConfigDict(frozen=True)

    name: str
    unit: FeatureUnit
    values: tuple[float | None, ...]


class ChartFill(BaseModel):
    """A fill of a trade, as the fills ledger holds it: its order, role, side, and lots, its
    instant, its price as decimal text, the fidelity it priced on, and `bar_time`, the open in
    whole seconds of the page's bar it lies on by F-BAR-06, none where it lies off the page."""

    model_config = ConfigDict(frozen=True)

    order: int
    role: OrderRole
    side: Side
    lots: int
    time: str
    bar_time: int | None
    price: str
    fidelity: FidelityText


class StopLevels(BaseModel):
    """A trade's stop: its first level, from its entry's price and its initial risk, and its last,
    as the orders hold it once a breakeven, a trail, or a roll moved it; none without a stop."""

    model_config = ConfigDict(frozen=True)

    first: str | None
    last: str | None


class ChartTrade(BaseModel):
    """A trade the page shows: its row, its id, its entry order, its side and lots, its net P&L
    as decimal text, every fill of it in the order they were made, its stop, and each target's
    last level."""

    model_config = ConfigDict(frozen=True)

    trade: int = Field(ge=0)
    entry_order: int
    side: PositionSide
    lots: int
    pnl: Decimal
    fills: tuple[ChartFill, ...]
    stop: StopLevels
    targets: tuple[str, ...]


class ChartPage(BarsPage):
    """A page of a saved run's chart: its bars as `GET /v1/market/bars` sends them, at the prices
    each contract traded at, with `next_from` to send as the next page's `from`; the
    instrument's tick; the strategy's features at each bar; and the trades with a fill on the
    page, or held across it."""

    tick_size: Decimal
    features: tuple[ChartFeature, ...]
    trades: tuple[ChartTrade, ...]


class NoSuchTradeError(ValueError):
    """A trade's id, its entry order, that no trade of the run has."""


class ExplainPayload(BaseModel):
    """An `explain` job's work: the trade `trade_id`, its entry order, of the saved run
    `run_key`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_key: Hash
    trade_id: int = Field(ge=0)


class ExplainedEvent(BaseModel):
    """An entry of the reference engine's log of the replay: when, what happened, of which order
    where it concerns one, under which rule of `docs/spec/fill-semantics.md`, and in words."""

    model_config = ConfigDict(frozen=True)

    time: str
    kind: EventKind
    order: int | None
    rule: str | None
    text: str


class ExplainedFill(BaseModel):
    """A fill of the replay, the reference engine's and the Rust engine's alike, as the fills
    ledger holds it: its order, role, side, and lots, its instant, its price as decimal text, the
    rule that priced it, its liquidity, its slippage in ticks, its fee as decimal text, its
    flags, the fidelity it priced on, and its contract."""

    model_config = ConfigDict(frozen=True)

    order: int
    role: OrderRole
    side: Side
    lots: int
    time: str
    price: str
    rule: str
    liquidity: str
    slippage_ticks: int
    fee: Decimal
    flags: tuple[str, ...]
    fidelity: FidelityText
    contract: str


class TradeExplained(BaseModel):
    """A trade replayed through the reference engine: its id, its heading as the notebook's
    `Run.explain` prints it, the instant its replay's first record starts at, the events of its
    log in the order they happened, and its fills."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["explained"] = "explained"
    trade_id: int
    heading: str
    started_at: str
    events: tuple[ExplainedEvent, ...]
    fills: tuple[ExplainedFill, ...]


class ExplanationRefused(BaseModel):
    """A trade the replay refused, with why, in words that name no folder of this PC: on TBBO,
    on two fidelities, of prints across a roll, entered by reversing a position, or of data or
    settings changed since the run (`fefat.backtest.explain`)."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["refused"] = "refused"
    trade_id: int
    reason: str


type TradeExplanation = Annotated[TradeExplained | ExplanationRefused, Field(discriminator="kind")]
"""An `explain` job's result, told apart by `kind`."""
