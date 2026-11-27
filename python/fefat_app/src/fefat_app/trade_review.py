"""The trade review's models (step 5.9, D-93): a page of a saved run's chart, its bars at the
prices each contract traded at, the strategy's features beside them, and the trades the page
shows with their fills on its bars and their stop and target levels; the API sends no int64,
an instant as ISO 8601 in UTC, a bar's open in whole seconds, and a price as decimal text."""

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from fefat.market.fidelity import FidelityText
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
