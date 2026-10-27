//! The tick loop on hand-written tapes transcribed from the scenarios they cite, through the
//! in-memory reader; `python/tests/test_rust_engine_scenarios.py` runs every tick scenario.

use fefat_core::fidelity::Fidelity;
use fefat_core::fills::PricingRule;
use fefat_core::instants::TradeDate;
use fefat_core::instrument::{Contract, InstrumentParameters, LotStep};
use fefat_core::ledger::Position;
use fefat_core::market_data::{InMemoryMarketData, TapeDay, TbboRow, TradeRow};
use fefat_core::orders::{OcoGroupId, OrderId, OrderKind, OrderState, Side};
use fefat_core::strategy_spec::StrategySpec;
use fefat_core::units::{MONEY_UNITS, Money, PRICE_UNITS, Price, Qty};

use super::*;
use crate::book::{Bracket, BracketLeg, LegPrice};
use crate::strategy::{ScenarioOrder, ScenarioOrders};
use crate::template::{SignalRow, TemplateStrategy};

/// 2026-03-06, the trade date of the scenarios' tapes.
const TRADE_DATE: TradeDate = TradeDate(20_518);
/// 2026-03-06T14:30:00Z.
const HALF_PAST_TWO: i64 = 1_772_807_400 * 1_000_000_000;

fn at(milliseconds: i64) -> Ts {
    Ts(HALF_PAST_TWO + milliseconds * 1_000_000)
}

fn price(hundredths: i64) -> Price {
    Price(hundredths * 10_000_000)
}

fn es() -> InstrumentParameters {
    InstrumentParameters::new(
        Price(250_000_000),
        Money(50 * MONEY_UNITS),
        LotStep(PRICE_UNITS),
    )
    .unwrap()
}

fn day(tbbo: Vec<TbboRow>, trades: Vec<TradeRow>) -> InMemoryMarketData {
    let tape = TapeDay {
        trade_date: TRADE_DATE,
        tbbo,
        trades,
        bars: Default::default(),
    };
    InMemoryMarketData::new(Contract("ESH2026".to_owned()), vec![tape]).unwrap()
}

/// Trades of `(milliseconds after 14:30, price in hundredths, size)`.
fn trades(records: &[(i64, i64, i64)]) -> InMemoryMarketData {
    let rows = records
        .iter()
        .map(|&(milliseconds, hundredths, size)| TradeRow {
            ts_recv: at(milliseconds),
            price: price(hundredths),
            size: Qty(size),
        });
    day(Vec::new(), rows.collect())
}

/// TBBO records of `(milliseconds, price, size, bid, ask, bid size, ask size)`.
fn tbbo(records: &[(i64, i64, i64, i64, i64, i64, i64)]) -> InMemoryMarketData {
    let rows = records.iter().map(
        |&(milliseconds, hundredths, size, bid, ask, bid_size, ask_size)| TbboRow {
            ts_recv: at(milliseconds),
            price: price(hundredths),
            size: Qty(size),
            bid: price(bid),
            ask: price(ask),
            bid_size: Qty(bid_size),
            ask_size: Qty(ask_size),
        },
    );
    day(rows.collect(), Vec::new())
}

fn order(id: u64, side: Side, kind: OrderKind) -> ScenarioOrder {
    ScenarioOrder {
        placed_at: at(0),
        id: OrderId(id),
        side,
        lots: Qty(1),
        kind,
        oco: None,
        bracket: None,
    }
}

fn in_group(order: ScenarioOrder, group: u64) -> ScenarioOrder {
    ScenarioOrder {
        oco: Some(OcoGroupId(group)),
        ..order
    }
}

fn bracketed(order: ScenarioOrder, stop: (u64, i64), target: (u64, i64)) -> ScenarioOrder {
    let leg = |(id, hundredths): (u64, i64)| BracketLeg {
        id: Some(OrderId(id)),
        price: LegPrice::At(price(hundredths)),
    };
    ScenarioOrder {
        bracket: Some(Bracket {
            stop: leg(stop),
            target: leg(target),
        }),
        ..order
    }
}

fn stop(hundredths: i64) -> OrderKind {
    OrderKind::StopMarket {
        stop: price(hundredths),
    }
}

fn limit(hundredths: i64) -> OrderKind {
    OrderKind::Limit {
        limit: price(hundredths),
    }
}

/// A long of one lot at 5000.00 held when the tape starts.
fn long_one() -> Ledger {
    Ledger::holding(
        es(),
        Money(50_000 * MONEY_UNITS),
        Side::Buy,
        Qty(1),
        price(500_000),
    )
    .unwrap()
}

fn flat() -> Ledger {
    Ledger::new(es(), Money(50_000 * MONEY_UNITS))
}

fn run(
    reader: &InMemoryMarketData,
    level: TickFidelity,
    ledger: Ledger,
    strategy: &mut dyn Strategy,
) -> RunOutputs {
    let hours = TradingHours::always();
    let settings = RunSettings::defaults_for(level.fidelity());
    TickRun::new(reader, level, &hours, settings, ledger, strategy)
        .unwrap()
        .run()
        .unwrap()
}

fn run_orders(
    reader: &InMemoryMarketData,
    level: TickFidelity,
    ledger: Ledger,
    orders: Vec<ScenarioOrder>,
) -> RunOutputs {
    run(reader, level, ledger, &mut ScenarioOrders::new(orders))
}

/// Each fill's order, milliseconds after 14:30, price in hundredths, and rule.
fn fills(outputs: &RunOutputs) -> Vec<(u64, i64, i64, PricingRule)> {
    let booked = outputs.fills.iter().map(|booked| booked.fill);
    booked
        .map(|fill| {
            let milliseconds = (fill.ts.0 - HALF_PAST_TWO) / 1_000_000;
            (
                fill.order.0,
                milliseconds,
                fill.price.0 / 10_000_000,
                fill.rule,
            )
        })
        .collect()
}

fn state_of(outputs: &RunOutputs, id: u64) -> OrderState {
    let found = outputs
        .orders
        .iter()
        .find(|order| order.order.id == OrderId(id));
    found.unwrap().state()
}

#[test]
fn a_sell_stop_gapped_through_on_trades_fills_at_the_first_trade_past_it() {
    // S-fill-012
    let reader = trades(&[
        (200, 499_600, 2),
        (450, 499_550, 1),
        (1_250, 499_025, 6),
        (1_400, 499_075, 3),
    ]);
    let orders = vec![order(1, Side::Sell, stop(499_500))];
    let outputs = run_orders(&reader, TickFidelity::Trades, long_one(), orders);
    assert_eq!(
        fills(&outputs),
        [(1, 1_250, 499_025, PricingRule::StopOnTrades)]
    );
    assert_eq!(outputs.fills[0].fill.slippage_ticks, 19);
    assert_eq!(outputs.ledger.position(), Position::Flat);
    assert_eq!(outputs.ledger.cash(), Money(49_512_500_000));
}

#[test]
fn the_first_stop_of_an_oco_pair_to_trigger_fills_and_cancels_the_other() {
    // S-fill-025
    let reader = trades(&[(300, 500_050, 2), (2_100, 500_500, 3), (5_400, 499_450, 4)]);
    let orders = vec![
        in_group(order(1, Side::Buy, stop(500_500)), 1),
        in_group(order(2, Side::Sell, stop(499_500)), 1),
    ];
    let outputs = run_orders(&reader, TickFidelity::Trades, flat(), orders);
    assert_eq!(
        fills(&outputs),
        [(1, 2_100, 500_525, PricingRule::StopOnTrades)]
    );
    assert_eq!(state_of(&outputs, 2), OrderState::Cancelled);
}

#[test]
fn a_bracket_stop_at_the_market_fills_on_the_next_trade_not_on_its_entrys_own() {
    // S-fill-035
    let reader = trades(&[(200, 500_000, 3), (600, 500_050, 2)]);
    let entry = order(1, Side::Buy, OrderKind::Market);
    let orders = vec![bracketed(entry, (2, 500_000), (3, 501_000))];
    let outputs = run_orders(&reader, TickFidelity::Trades, flat(), orders);
    assert_eq!(
        fills(&outputs),
        [
            (1, 200, 500_025, PricingRule::MarketAtTrade),
            (2, 600, 500_025, PricingRule::StopThroughMarket),
        ]
    );
    assert_eq!(state_of(&outputs, 3), OrderState::Cancelled);
}

#[test]
fn when_one_tbbo_record_would_fill_a_triggered_stop_and_its_target_the_stop_fills() {
    // S-fill-036
    let reader = tbbo(&[
        (200, 499_500, 2, 499_500, 499_525, 6, 4),
        (300, 500_525, 1, 500_500, 500_525, 3, 5),
    ]);
    let orders = vec![
        in_group(order(1, Side::Sell, stop(499_500)), 1),
        in_group(order(2, Side::Sell, limit(500_500)), 1),
    ];
    let outputs = run_orders(&reader, TickFidelity::Tbbo, long_one(), orders);
    assert_eq!(
        fills(&outputs),
        [(1, 300, 499_500, PricingRule::StopAtNextQuote)]
    );
}

#[test]
fn on_tbbo_a_bracket_stop_at_its_entry_records_trade_is_through_the_market() {
    // S-fill-041
    let reader = tbbo(&[
        (200, 499_975, 2, 499_975, 500_000, 6, 5),
        (450, 500_000, 1, 499_975, 500_000, 4, 3),
    ]);
    let entry = order(1, Side::Buy, OrderKind::Market);
    let orders = vec![bracketed(entry, (2, 499_975), (3, 501_000))];
    let outputs = run_orders(&reader, TickFidelity::Tbbo, flat(), orders);
    assert_eq!(
        fills(&outputs),
        [
            (1, 200, 500_000, PricingRule::MarketAtQuote),
            (2, 450, 499_975, PricingRule::StopThroughMarket),
        ]
    );
}

#[test]
fn a_tbbo_record_that_triggers_a_stop_and_trades_through_a_limit_of_its_group_fills_the_limit() {
    // S-fill-043
    let reader = tbbo(&[
        (200, 500_300, 2, 500_275, 500_300, 6, 4),
        (300, 500_500, 1, 500_475, 500_500, 3, 5),
        (400, 500_525, 2, 500_500, 500_525, 4, 6),
    ]);
    let orders = vec![
        in_group(order(1, Side::Buy, stop(500_500)), 1),
        in_group(order(2, Side::Sell, limit(500_400)), 1),
    ];
    let outputs = run_orders(&reader, TickFidelity::Tbbo, flat(), orders);
    assert_eq!(
        fills(&outputs),
        [(2, 300, 500_400, PricingRule::LimitAtItsPrice)]
    );
    assert_eq!(state_of(&outputs, 1), OrderState::Cancelled);
}

#[test]
fn in_a_tbbo_sweep_a_stop_fills_at_the_print_below_the_bid_it_carries() {
    // S-fill-044
    let reader = tbbo(&[
        (200, 499_600, 2, 499_575, 499_600, 6, 4),
        (300, 499_575, 6, 499_575, 499_600, 6, 4),
        (300, 499_525, 5, 499_575, 499_600, 6, 4),
        (300, 499_400, 5, 499_575, 499_600, 6, 4),
        (400, 499_375, 1, 499_350, 499_375, 3, 2),
    ]);
    let orders = vec![order(1, Side::Sell, stop(499_550))];
    let outputs = run_orders(&reader, TickFidelity::Tbbo, long_one(), orders);
    assert_eq!(
        fills(&outputs),
        [(1, 300, 499_400, PricingRule::StopAtNextQuote)]
    );
    assert_eq!(outputs.fills[0].fill.slippage_ticks, 6);
}

#[test]
fn a_tbbo_stop_triggered_on_one_record_fills_before_a_market_order_of_its_group() {
    // S-fill-047
    let reader = tbbo(&[
        (150, 500_100, 2, 500_075, 500_100, 5, 5),
        (300, 500_125, 2, 500_100, 500_125, 5, 5),
    ]);
    let market = ScenarioOrder {
        placed_at: at(200),
        lots: Qty(2),
        ..in_group(order(2, Side::Buy, OrderKind::Market), 1)
    };
    let orders = vec![in_group(order(1, Side::Buy, stop(500_100)), 1), market];
    let outputs = run_orders(&reader, TickFidelity::Tbbo, flat(), orders);
    assert_eq!(
        fills(&outputs),
        [(1, 300, 500_125, PricingRule::StopAtNextQuote)]
    );
    assert_eq!(state_of(&outputs, 2), OrderState::Cancelled);
    assert_eq!(outputs.ledger.position().signed_lots(), Qty(1));
}

#[test]
fn a_templates_short_takes_its_size_from_size_mult_and_its_bracket_from_the_columns() {
    // S-template-002
    let spec: StrategySpec = serde_json::from_value(serde_json::json!({
        "spec_version": 1,
        "instrument": "ES",
        "timeframe": "5m",
        "execution": {
            "entry": {"kind": "market"},
            "stop": {"kind": "column"},
            "targets": [{"price": {"kind": "column"}}],
            "sizing": {"kind": "fixed", "units": 1}
        }
    }))
    .unwrap();
    let row = SignalRow {
        ts_close: at(300_000),
        long_entry: false,
        short_entry: true,
        long_exit: false,
        short_exit: false,
        stop_price: Some(price(500_300)),
        target_price: Some(price(499_000)),
        size_mult: Some(2.0),
        wake: true,
    };
    let mut template = TemplateStrategy::new(&spec, vec![row], &es()).unwrap();
    let reader = trades(&[
        (300_200, 500_000, 3),
        (301_000, 500_150, 1),
        (302_000, 500_300, 4),
        (302_500, 500_350, 2),
    ]);
    let outputs = run(&reader, TickFidelity::Trades, flat(), &mut template);
    assert_eq!(
        fills(&outputs),
        [
            (1, 300_200, 499_975, PricingRule::MarketAtTrade),
            (2, 302_000, 500_325, PricingRule::StopOnTrades),
        ]
    );
    assert_eq!(outputs.fills[0].fill.lots, Qty(2));
    assert_eq!(state_of(&outputs, 3), OrderState::Cancelled);
}

#[test]
fn records_that_go_back_in_time_across_trade_dates_are_refused() {
    let day = |trade_date: i32, milliseconds: i64| TapeDay {
        trade_date: TradeDate(trade_date),
        tbbo: Vec::new(),
        trades: vec![TradeRow {
            ts_recv: at(milliseconds),
            price: price(500_000),
            size: Qty(1),
        }],
        bars: Default::default(),
    };
    let days = vec![day(20_518, 500), day(20_519, 100)];
    let reader = InMemoryMarketData::new(Contract("ESH2026".to_owned()), days).unwrap();
    let (hours, mut strategy) = (TradingHours::always(), ScenarioOrders::new(Vec::new()));
    let (level, settings) = (
        TickFidelity::Trades,
        RunSettings::defaults_for(Fidelity::Trades),
    );
    let run = TickRun::new(&reader, level, &hours, settings, flat(), &mut strategy).unwrap();
    assert!(matches!(run.run(), Err(RunError::RecordsOutOfOrder { .. })));
}

#[test]
fn a_bar_fidelity_is_refused_until_step_2_7() {
    let fidelity = Fidelity::Bars(fefat_core::fidelity::Timeframe::ONE_MINUTE);
    let refused = TickFidelity::try_from(fidelity);
    assert_eq!(refused, Err(RunError::BarFidelity { fidelity }));
    assert_eq!(
        TickFidelity::try_from(Fidelity::Tbbo),
        Ok(TickFidelity::Tbbo)
    );
}
