"""NautilusTrader's side of the cross-check: load the month cut through its Databento adapter,
build the contract, and run each strategy of `fefat.json` under both bar paths on a simulated
venue with bar execution, no slippage, limits filled on touch, no fees, and no latency; write the
bars as loaded, each run's decisions, and each run's trades in the comparison's columns under
`<comparison folder>/engine/`, with `nautilus.json`."""

import json
import warnings
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import nautilus_trader
import polars as pl
from nautilus_trader.adapters.databento.loaders import DatabentoDataLoader
from nautilus_trader.backtest.config import BacktestEngineConfig
from nautilus_trader.backtest.engine import BacktestEngine
from nautilus_trader.backtest.models import FillModel, PerContractFeeModel
from nautilus_trader.config import LoggingConfig
from nautilus_trader.data.config import DataEngineConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import Bar
from nautilus_trader.model.enums import AccountType, AssetClass, OmsType, OrderType
from nautilus_trader.model.events import OrderFilled
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import FuturesContract
from nautilus_trader.model.objects import Money, Quantity
from nautilus_trader.model.orders import Order

from fefat_xcheck.classify import TRADE_COLUMNS
from fefat_xcheck.strategies import (
    ENTRY_TAG,
    FLAT_BY_TAG,
    STOP_TAG,
    TARGET_TAG,
    CrossCheckConfig,
    CrossCheckStrategy,
)
from fefat_xcheck.units import MINUTE, UNITS_PER_POINT, units_of, utc_day, whole_second

VENUE = Venue("GLBX")
BAR_ORDERS = {"ohlc": False, "adaptive": True}
"""The two bar paths, by the venue's `bar_adaptive_high_low_ordering`."""
BUILD_DELAY_MICROSECONDS = 1
"""Nautilus closes a time bar on a timer; the delay puts the timer after the 1-minute bar stamped
at the boundary, so that bar joins the 5-minute bar closing there (its data documentation)."""
BARS_COLUMNS = ["ts_open", "ts_close", "open", "high", "low", "close", "volume"]
DECISION_COLUMNS = pl.Schema({"ts_close": pl.Int64, "close": pl.Int64, "action": pl.String})
STARTING_BALANCE = Money(1_000_000, USD)


def run_nautilus_side(folder: Path) -> dict[str, Any]:
    """Run every strategy of `folder/fefat/fefat.json` on the cut named by `folder/cut.json`
    under both bar paths and write the results under `folder/engine`; `nautilus.json`, the
    facts of the runs, is returned."""
    facts = json.loads((folder / "fefat" / "fefat.json").read_text(encoding="utf-8"))
    cut = json.loads((folder / "cut.json").read_text(encoding="utf-8"))["cut"]
    instrument_id = InstrumentId.from_str(f"{cut['raw_symbol']}.{VENUE}")
    tick = Decimal(facts["instrument"]["tick"]) / UNITS_PER_POINT
    precision = -int(tick.normalize().as_tuple().exponent)
    bars = loaded_bars(folder / cut["name"], instrument_id, precision)
    contract = futures_contract(facts, instrument_id, tick, precision)
    engine_folder = folder / "engine"
    engine_folder.mkdir(exist_ok=True)
    bars_frame(bars).write_parquet(engine_folder / "bars_1m.parquet")
    point_value = Decimal(facts["instrument"]["point_value"])
    for strategy in facts["strategies"]:
        for order_name, adaptive in BAR_ORDERS.items():
            config = strategy_config(facts, strategy, instrument_id, tick, precision)
            trades, decisions = run_strategy(bars, contract, config, adaptive, point_value)
            trades.write_parquet(engine_folder / f"trades_{strategy['name']}_{order_name}.parquet")
            decisions.write_parquet(
                engine_folder / f"decisions_{strategy['name']}_{order_name}.parquet"
            )
    settings = {
        "nautilus_trader": nautilus_trader.__version__,
        "bar_type": f"{instrument_id}-5-MINUTE-LAST-INTERNAL@1-MINUTE-EXTERNAL",
        "bars": len(bars),
        "venue": {
            "name": str(VENUE),
            "oms_type": "NETTING",
            "account_type": "MARGIN",
            "fill_model": {"prob_fill_on_limit": 1.0, "prob_slippage": 0.0},
            "fee_model": "PerContractFeeModel(0 USD)",
            "latency_model": None,
            "bar_execution": True,
            "reject_stop_orders": False,
            "bar_adaptive_high_low_ordering": sorted(BAR_ORDERS),
        },
        "data_engine": {
            "time_bars_build_delay": BUILD_DELAY_MICROSECONDS,
            "time_bars_build_with_no_updates": False,
        },
    }
    (engine_folder / "nautilus.json").write_text(
        json.dumps(settings, indent=2) + "\n", encoding="utf-8"
    )
    return settings


def loaded_bars(cut: Path, instrument_id: InstrumentId, precision: int) -> list[Bar]:
    """The cut's bars of the instrument through the Databento adapter, stamped at their close,
    sorted; a bar of another symbol in the cut is left out rather than relabelled."""
    loader = DatabentoDataLoader()
    loaded = loader.from_dbn_file(cut, price_precision=precision, bars_timestamp_on_close=True)
    bars = [
        bar
        for bar in loaded
        if isinstance(bar, Bar) and bar.bar_type.instrument_id == instrument_id
    ]
    if not bars:
        raise ValueError(f"Expected bars of {instrument_id} in {cut.name}, got none.")
    return sorted(bars, key=lambda bar: bar.ts_event)


def futures_contract(
    facts: dict[str, Any], instrument_id: InstrumentId, tick: Decimal, precision: int
) -> FuturesContract:
    """The contract from FEFAT's instrument table: the tick and the money a point makes; active
    through the window."""
    first = date.fromisoformat(facts["window"]["first"])
    last = date.fromisoformat(facts["window"]["last"])
    return FuturesContract(
        instrument_id=instrument_id,
        raw_symbol=Symbol(instrument_id.symbol.value),
        asset_class=AssetClass.INDEX,
        currency=USD,
        price_precision=precision,
        price_increment=_price(tick, precision),
        multiplier=Quantity.from_str(facts["instrument"]["point_value"]),
        lot_size=Quantity.from_int(1),
        underlying=facts["instrument"]["root"],
        activation_ns=utc_day(first) - 400 * 24 * 60 * MINUTE,
        expiration_ns=utc_day(last) + 90 * 24 * 60 * MINUTE,
        ts_event=0,
        ts_init=0,
    )


def strategy_config(
    facts: dict[str, Any],
    strategy: dict[str, Any],
    instrument_id: InstrumentId,
    tick: Decimal,
    precision: int,
) -> CrossCheckConfig:
    return CrossCheckConfig(
        instrument_id=str(instrument_id),
        bar_type=f"{instrument_id}-5-MINUTE-LAST-INTERNAL@1-MINUTE-EXTERNAL",
        entry=strategy["entry"],
        offset_ticks=strategy["offset_ticks"],
        stop_ticks=strategy["stop_ticks"],
        target_ticks=strategy["target_ticks"],
        window_start=strategy["window"][0],
        window_end=strategy["window"][1],
        flat_by=strategy["flat_by"],
        time_zone=strategy["tz"],
        first_trade_date=facts["window"]["first"],
        last_trade_date=facts["window"]["last"],
        tick=str(tick),
        price_precision=precision,
    )


def run_strategy(
    bars: list[Bar],
    contract: FuturesContract,
    config: CrossCheckConfig,
    adaptive: bool,
    point_value: Decimal,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """One backtest: the trades in the comparison's columns and the decisions."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        engine = BacktestEngine(
            BacktestEngineConfig(
                logging=LoggingConfig(bypass_logging=True),
                data_engine=DataEngineConfig(
                    time_bars_build_delay=BUILD_DELAY_MICROSECONDS,
                    time_bars_build_with_no_updates=False,
                ),
            )
        )
        engine.add_venue(
            venue=VENUE,
            oms_type=OmsType.NETTING,
            account_type=AccountType.MARGIN,
            starting_balances=[STARTING_BALANCE],
            base_currency=USD,
            fill_model=FillModel(prob_fill_on_limit=1.0, prob_slippage=0.0),
            fee_model=PerContractFeeModel(Money(0, USD)),
            bar_execution=True,
            bar_adaptive_high_low_ordering=adaptive,
            reject_stop_orders=False,
        )
        engine.add_instrument(contract)
        engine.add_data(bars)
        strategy = CrossCheckStrategy(config)
        engine.add_strategy(strategy)
        engine.run()
        trades = trades_of(engine.cache.orders(instrument_id=contract.id), point_value)
        decisions = pl.DataFrame(strategy.decisions, schema=DECISION_COLUMNS, orient="row")
        engine.dispose()
    return trades, decisions


def trades_of(orders: list[Order], point_value: Decimal) -> pl.DataFrame:
    """The flat-to-flat trades from the filled orders: an entry's fill opens one, the next fill
    of its leg or of a flat-by closes it; one lot, one position at a time. A leg released on the
    tick that fills its entry carries the entry's fill instant, so the entry sorts first by its
    role, and the cache's order of orders, which Nautilus leaves undefined, decides nothing."""
    filled = sorted(
        (order for order in orders if order.filled_qty > 0),
        key=lambda order: (
            _fill_of(order).ts_event,
            _role(order) != ENTRY_TAG,
            str(order.client_order_id),
        ),
    )
    by_id = {order.client_order_id: order for order in orders}
    rows: list[dict[str, object]] = []
    open_entry: Order | None = None
    for order in filled:
        role = _role(order)
        if role == ENTRY_TAG:
            if open_entry is not None:
                raise ValueError(
                    f"Expected a flat position before the entry {order.client_order_id}."
                )
            open_entry = order
            continue
        if open_entry is None:
            raise ValueError(f"Expected an open position before the exit {order.client_order_id}.")
        rows.append(_trade_row(open_entry, order, by_id, point_value))
        open_entry = None
    return pl.DataFrame(rows, schema=TRADE_COLUMNS)


def _trade_row(
    entry: Order, exit: Order, by_id: dict[Any, Order], point_value: Decimal
) -> dict[str, object]:
    entry_fill, exit_fill = _fill_of(entry), _fill_of(exit)
    legs = [order for order in by_id.values() if order.parent_order_id == entry.client_order_id]
    stop = next(order for order in legs if STOP_TAG in (order.tags or ()))
    target = next(order for order in legs if TARGET_TAG in (order.tags or ()))
    long = entry.side.name == "BUY"
    entry_price, exit_price = entry_fill.last_px.as_decimal(), exit_fill.last_px.as_decimal()
    sign = 1 if long else -1
    return {
        "entry_decision": whole_second(entry.ts_init),
        "side": "long" if long else "short",
        "entry_kind": {
            OrderType.MARKET: "market",
            OrderType.LIMIT: "limit",
            OrderType.STOP_MARKET: "stop",
        }[entry.order_type],
        "entry_ts": whole_second(entry_fill.ts_event),
        "entry_price": units_of(entry_price),
        "exit_ts": whole_second(exit_fill.ts_event),
        "exit_price": units_of(exit_price),
        "exit_reason": _role(exit),
        "stop_price": units_of(stop.trigger_price.as_decimal()),
        "target_price": units_of(target.price.as_decimal()),
        "gross_pnl": float((exit_price - entry_price) * sign * point_value),
    }


def _role(order: Order) -> str:
    tags = set(order.tags or ())
    roles = tags & {ENTRY_TAG, STOP_TAG, TARGET_TAG, FLAT_BY_TAG}
    if len(roles) != 1:
        raise ValueError(f"Expected one role tag on {order.client_order_id}, got {sorted(tags)}.")
    return roles.pop()


def _fill_of(order: Order) -> OrderFilled:
    fills = [event for event in order.events if isinstance(event, OrderFilled)]
    if len(fills) != 1:
        raise ValueError(f"Expected one fill of {order.client_order_id}, got {len(fills)}.")
    return fills[0]


def bars_frame(bars: list[Bar]) -> pl.DataFrame:
    """The bars as loaded, in the store's units: instants in nanoseconds and prices in 1e-9."""
    return pl.DataFrame(
        {
            "ts_open": [bar.ts_event - MINUTE for bar in bars],
            "ts_close": [bar.ts_event for bar in bars],
            "open": [units_of(bar.open.as_decimal()) for bar in bars],
            "high": [units_of(bar.high.as_decimal()) for bar in bars],
            "low": [units_of(bar.low.as_decimal()) for bar in bars],
            "close": [units_of(bar.close.as_decimal()) for bar in bars],
            "volume": [int(bar.volume.as_decimal()) for bar in bars],
        },
        schema={name: pl.Int64 for name in BARS_COLUMNS},
    )


def _price(value: Decimal, precision: int) -> Any:
    from nautilus_trader.model.objects import Price

    return Price(value, precision)
