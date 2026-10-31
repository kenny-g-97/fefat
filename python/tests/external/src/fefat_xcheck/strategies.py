"""The cross-check's strategies as NautilusTrader runs them: one `Strategy` that decides on a
composite 5-minute bar type built from the external 1-minute bars, long when the close is above
the previous close, short when below, enters at the market or with a limit or a stop ticks from
the close (cancelled at the next decision if unfilled), with a stop and a target at fixed levels
from the signal close as one OCO group, inside an entry window and flat by a local time, as
`scripts/xcheck.py`'s `signal_strategy` writes the same for FEFAT.

The entry and its two legs are one order list built as `OrderFactory.bracket` builds one (the
entry OTO to its legs, the legs OCO to each other), since the factory takes no stop-market
entry."""

from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from nautilus_trader.config import StrategyConfig
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.data import Bar, BarType
from nautilus_trader.model.enums import ContingencyType, OrderSide, OrderType, TriggerType
from nautilus_trader.model.identifiers import ClientOrderId, InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.model.orders import LimitOrder, MarketOrder, Order, OrderList, StopMarketOrder
from nautilus_trader.trading.strategy import Strategy

ENTRY_TAG, STOP_TAG, TARGET_TAG, FLAT_BY_TAG = "entry", "stop", "target", "flat_by"
NANOSECONDS_PER_SECOND = 1_000_000_000
ENTRY_ORDER_TYPES = {
    "market": OrderType.MARKET,
    "limit": OrderType.LIMIT,
    "stop": OrderType.STOP_MARKET,
}
ONE_LOT = Quantity.from_int(1)


class CrossCheckConfig(StrategyConfig, frozen=True):
    """The strategy's parameters, from `fefat.json`'s strategy and instrument."""

    instrument_id: str
    bar_type: str
    entry: str
    offset_ticks: int
    stop_ticks: int
    target_ticks: int
    window_start: str
    window_end: str
    flat_by: str
    time_zone: str
    first_trade_date: str
    last_trade_date: str
    tick: str
    price_precision: int


class CrossCheckStrategy(Strategy):
    """Decides at each 5-minute close as the FEFAT template does at each signal row
    (F-ENT-01): the flat-by first, then the cancel of an entry still resting, then the entry."""

    def __init__(self, config: CrossCheckConfig) -> None:
        super().__init__(config)
        self.instrument_id = InstrumentId.from_str(config.instrument_id)
        self.bar_type = BarType.from_str(config.bar_type)
        self.entry_type = ENTRY_ORDER_TYPES[config.entry]
        self.tick = Decimal(config.tick)
        self.zone = ZoneInfo(config.time_zone)
        self.window = (
            time.fromisoformat(config.window_start),
            time.fromisoformat(config.window_end),
        )
        self.flat_by = time.fromisoformat(config.flat_by)
        self.trade_dates = (
            date.fromisoformat(config.first_trade_date),
            date.fromisoformat(config.last_trade_date),
        )
        self.previous_close: Decimal | None = None
        self.decisions: list[tuple[int, int, str]] = []
        """Each decision: the bar's close instant, its close in 1e-9 units, and the action."""

    def on_start(self) -> None:
        self.subscribe_bars(self.bar_type)

    def on_bar(self, bar: Bar) -> None:
        instant = bar.ts_init // NANOSECONDS_PER_SECOND * NANOSECONDS_PER_SECOND
        close = bar.close.as_decimal()
        local = datetime.fromtimestamp(instant / NANOSECONDS_PER_SECOND, tz=self.zone)
        action = self._decide(local, close)
        self.decisions.append((instant, int(close * NANOSECONDS_PER_SECOND), action))
        self.previous_close = close

    def _decide(self, local: datetime, close: Decimal) -> str:
        if local.time() >= self.flat_by:
            return self._flat_by()
        self._cancel_resting_entries()
        if not self.portfolio.is_flat(self.instrument_id) or self._working_legs():
            return "none"
        if not self._may_enter(local):
            return "none"
        if self.previous_close is None or close == self.previous_close:
            return "none"
        side = OrderSide.BUY if close > self.previous_close else OrderSide.SELL
        self.submit_order_list(self._bracket(side, close))
        return "long" if side == OrderSide.BUY else "short"

    def _flat_by(self) -> str:
        if self.cache.orders_open(instrument_id=self.instrument_id):
            self.cancel_all_orders(self.instrument_id)
        if self.portfolio.is_flat(self.instrument_id):
            return "none"
        self.close_all_positions(self.instrument_id, tags=[FLAT_BY_TAG])
        return "flat_by"

    def _cancel_resting_entries(self) -> None:
        """An entry still resting at the next decision is cancelled (F-ENT-03, one bar to live)."""
        for order in self.cache.orders_open(instrument_id=self.instrument_id):
            if order.parent_order_id is None and order.order_type != OrderType.MARKET:
                self.cancel_order(order)

    def _working_legs(self) -> bool:
        return any(
            order.parent_order_id is not None
            for order in self.cache.orders_open(instrument_id=self.instrument_id)
        )

    def _may_enter(self, local: datetime) -> bool:
        first, last = self.trade_dates
        start, end = self.window
        return first <= local.date() <= last and start <= local.time() < end

    def _bracket(self, side: OrderSide, close: Decimal) -> OrderList:
        """The entry with its stop and target, levels from the signal close."""
        sign = 1 if side == OrderSide.BUY else -1
        exit_side = OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY
        factory = self.order_factory
        entry_id, stop_id, target_id = (factory.generate_client_order_id() for _ in range(3))
        list_id = factory.generate_order_list_id()
        shared = {
            "trader_id": self.trader_id,
            "strategy_id": self.id,
            "instrument_id": self.instrument_id,
            "quantity": ONE_LOT,
            "ts_init": self.clock.timestamp_ns(),
            "order_list_id": list_id,
        }
        entry = self._entry_order(entry_id, side, close, [stop_id, target_id], shared)
        stop = StopMarketOrder(
            client_order_id=stop_id,
            order_side=exit_side,
            trigger_price=self._price(close - sign * self.config.stop_ticks * self.tick),
            trigger_type=TriggerType.DEFAULT,
            init_id=UUID4(),
            reduce_only=True,
            contingency_type=ContingencyType.OCO,
            linked_order_ids=[target_id],
            parent_order_id=entry_id,
            tags=[STOP_TAG],
            **shared,
        )
        target = LimitOrder(
            client_order_id=target_id,
            order_side=exit_side,
            price=self._price(close + sign * self.config.target_ticks * self.tick),
            init_id=UUID4(),
            reduce_only=True,
            contingency_type=ContingencyType.OCO,
            linked_order_ids=[stop_id],
            parent_order_id=entry_id,
            tags=[TARGET_TAG],
            **shared,
        )
        return OrderList(list_id, [entry, stop, target])

    def _entry_order(
        self,
        entry_id: ClientOrderId,
        side: OrderSide,
        close: Decimal,
        legs: list[ClientOrderId],
        shared: dict[str, object],
    ) -> Order:
        sign = 1 if side == OrderSide.BUY else -1
        offset = self.config.offset_ticks * self.tick
        contingent = {
            "contingency_type": ContingencyType.OTO,
            "linked_order_ids": legs,
            "tags": [ENTRY_TAG],
        }
        if self.entry_type == OrderType.MARKET:
            return MarketOrder(
                client_order_id=entry_id, order_side=side, init_id=UUID4(), **contingent, **shared
            )
        if self.entry_type == OrderType.LIMIT:
            return LimitOrder(
                client_order_id=entry_id,
                order_side=side,
                price=self._price(close - sign * offset),
                init_id=UUID4(),
                **contingent,
                **shared,
            )
        return StopMarketOrder(
            client_order_id=entry_id,
            order_side=side,
            trigger_price=self._price(close + sign * offset),
            trigger_type=TriggerType.DEFAULT,
            init_id=UUID4(),
            **contingent,
            **shared,
        )

    def _price(self, value: Decimal) -> Price:
        return Price(value, self.config.price_precision)
