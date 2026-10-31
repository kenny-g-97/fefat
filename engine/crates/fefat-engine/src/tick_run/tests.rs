//! The loop on hand-written tapes transcribed from the scenarios they cite, ticks and bars,
//! through the in-memory reader; `python/tests/test_rust_engine_scenarios.py` runs every
//! scenario.

use std::collections::BTreeMap;

use fefat_core::fidelity::{Fidelity, Timeframe};
use fefat_core::fills::PricingRule;
use fefat_core::instants::TradeDate;
use fefat_core::instrument::{Contract, InstrumentParameters, LotStep};
use fefat_core::ledger::Position;
use fefat_core::market_data::{BarRow, InMemoryMarketData, TapeDay, TbboRow, TradeRow};
use fefat_core::orders::{OcoGroupId, OrderId, OrderKind, OrderState, Side};
use fefat_core::strategy_spec::StrategySpec;
use fefat_core::units::{MONEY_UNITS, Money, PRICE_UNITS, Price, Qty};

use super::*;
use crate::book::{Bracket, BracketLeg, LegPrice};
use crate::hours::Session;
use crate::strategy::{ScenarioOrder, ScenarioOrders};
use crate::template::{SignalRow, TemplateStrategy};

/// 2026-03-06, the trade date of the scenarios' tapes.
pub(super) const TRADE_DATE: TradeDate = TradeDate(20_518);
/// 2026-03-06T14:30:00Z.
pub(super) const HALF_PAST_TWO: i64 = 1_772_807_400 * 1_000_000_000;

pub(super) fn at(milliseconds: i64) -> Ts {
    Ts(HALF_PAST_TWO + milliseconds * 1_000_000)
}

pub(super) fn price(hundredths: i64) -> Price {
    Price(hundredths * 10_000_000)
}

pub(super) fn es() -> InstrumentParameters {
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
pub(super) fn trades(records: &[(i64, i64, i64)]) -> InMemoryMarketData {
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

pub(super) fn order(id: u64, side: Side, kind: OrderKind) -> ScenarioOrder {
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

pub(super) fn stop(hundredths: i64) -> OrderKind {
    OrderKind::StopMarket {
        stop: price(hundredths),
    }
}

pub(super) fn limit(hundredths: i64) -> OrderKind {
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

pub(super) fn flat() -> Ledger {
    Ledger::new(es(), Money(50_000 * MONEY_UNITS))
}

/// Bars of `timeframe` of `(seconds after 14:30 it opens, its length in seconds, its open, high,
/// low, and close in hundredths, its volume)`.
fn bars(timeframe: Timeframe, rows: &[(i64, i64, [i64; 4], i64)]) -> InMemoryMarketData {
    let rows = rows.iter().map(
        |&(opens, seconds, [open, high, low, close], volume)| BarRow {
            ts_open: at(opens * 1_000),
            ts_close: at((opens + seconds) * 1_000),
            open: price(open),
            high: price(high),
            low: price(low),
            close: price(close),
            volume: Qty(volume),
        },
    );
    let tape = TapeDay {
        trade_date: TRADE_DATE,
        tbbo: Vec::new(),
        trades: Vec::new(),
        bars: BTreeMap::from([(timeframe, rows.collect())]),
    };
    InMemoryMarketData::new(Contract("ESH2026".to_owned()), vec![tape]).unwrap()
}

/// 1-minute bars of `(minutes after 14:30 it opens, its open, high, low, and close in
/// hundredths, its volume)`.
pub(super) fn minutes(rows: &[(i64, [i64; 4], i64)]) -> InMemoryMarketData {
    let rows: Vec<(i64, i64, [i64; 4], i64)> = rows
        .iter()
        .map(|&(minute, prices, volume)| (minute * 60, 60, prices, volume))
        .collect();
    bars(Timeframe::ONE_MINUTE, &rows)
}

fn run(
    reader: &InMemoryMarketData,
    fidelity: Fidelity,
    ledger: Ledger,
    strategy: &mut dyn Strategy,
) -> RunOutputs {
    let hours = TradingHours::always();
    let settings = RunSettings::defaults_for(fidelity);
    TickRun::new(
        reader,
        fidelity,
        Replay::Full,
        &hours,
        settings,
        ledger,
        strategy,
    )
    .unwrap()
    .run()
    .unwrap()
}

pub(super) fn run_orders(
    reader: &InMemoryMarketData,
    fidelity: Fidelity,
    ledger: Ledger,
    orders: Vec<ScenarioOrder>,
) -> RunOutputs {
    run(reader, fidelity, ledger, &mut ScenarioOrders::new(orders))
}

/// Each fill's order and whether it is flagged ambiguous (F-BAR-05).
fn ambiguity(outputs: &RunOutputs) -> Vec<(u64, bool)> {
    let booked = outputs.fills.iter().map(|booked| booked.fill);
    booked
        .map(|fill| (fill.order.0, fill.flags.ambiguous))
        .collect()
}

fn logged_ambiguous(outputs: &RunOutputs) -> usize {
    let entries = outputs.log.iter();
    entries
        .filter(|entry| entry.kind == crate::event_log::EventKind::Ambiguous)
        .count()
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
    let outputs = run_orders(&reader, Fidelity::Trades, long_one(), orders);
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
    let outputs = run_orders(&reader, Fidelity::Trades, flat(), orders);
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
    let outputs = run_orders(&reader, Fidelity::Trades, flat(), orders);
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
    let outputs = run_orders(&reader, Fidelity::Tbbo, long_one(), orders);
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
    let outputs = run_orders(&reader, Fidelity::Tbbo, flat(), orders);
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
    let outputs = run_orders(&reader, Fidelity::Tbbo, flat(), orders);
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
    let outputs = run_orders(&reader, Fidelity::Tbbo, long_one(), orders);
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
    let outputs = run_orders(&reader, Fidelity::Tbbo, flat(), orders);
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
        short_entry: true,
        stop_price: Some(price(500_300)),
        target_price: Some(price(499_000)),
        size_mult: Some(2.0),
        ..SignalRow::at(at(300_000))
    };
    let mut template = TemplateStrategy::new(&spec, vec![row], &es()).unwrap();
    let reader = trades(&[
        (300_200, 500_000, 3),
        (301_000, 500_150, 1),
        (302_000, 500_300, 4),
        (302_500, 500_350, 2),
    ]);
    let outputs = run(&reader, Fidelity::Trades, flat(), &mut template);
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
    let settings = RunSettings::defaults_for(Fidelity::Trades);
    let (fidelity, replay) = (Fidelity::Trades, Replay::Full);
    let run = TickRun::new(
        &reader,
        fidelity,
        replay,
        &hours,
        settings,
        flat(),
        &mut strategy,
    )
    .unwrap();
    assert!(matches!(run.run(), Err(RunError::RecordsOutOfOrder { .. })));
}

#[test]
fn a_stop_triggered_on_tbbo_is_refused_on_a_trade_or_a_bar_of_the_next_date() {
    // F-STP-02 fills a stop triggered on TBBO at the next record's quote, which trades and bars
    // lack.
    let quoted = |milliseconds: i64, hundredths: i64| TbboRow {
        ts_recv: at(milliseconds),
        price: price(hundredths),
        size: Qty(1),
        bid: price(hundredths - 25),
        ask: price(hundredths),
        bid_size: Qty(1),
        ask_size: Qty(1),
    };
    let next_date = TradeDate(TRADE_DATE.0 + 1);
    let trade = TradeRow {
        ts_recv: at(86_400_000),
        price: price(499_000),
        size: Qty(2),
    };
    let minute = BarRow {
        ts_open: at(86_400_000),
        ts_close: at(86_460_000),
        open: price(499_000),
        high: price(499_000),
        low: price(499_000),
        close: price(499_000),
        volume: Qty(2),
    };
    let next_days = [
        (
            TapeDay {
                trade_date: next_date,
                tbbo: Vec::new(),
                trades: vec![trade],
                bars: Default::default(),
            },
            Fidelity::Trades,
        ),
        (
            TapeDay {
                trade_date: next_date,
                tbbo: Vec::new(),
                trades: Vec::new(),
                bars: BTreeMap::from([(Timeframe::ONE_MINUTE, vec![minute])]),
            },
            Fidelity::Bars(Timeframe::ONE_MINUTE),
        ),
    ];
    for (next_day, level) in next_days {
        let triggering = TapeDay {
            trade_date: TRADE_DATE,
            tbbo: vec![quoted(200, 500_000), quoted(400, 499_475)],
            trades: Vec::new(),
            bars: Default::default(),
        };
        let days = vec![triggering, next_day];
        let reader = InMemoryMarketData::new(Contract("ESH2026".to_owned()), days).unwrap();
        let mut strategy = ScenarioOrders::new(vec![order(1, Side::Sell, stop(499_500))]);
        let hours = TradingHours::always();
        let settings = RunSettings::defaults_for(Fidelity::Tbbo);
        let (fidelity, replay) = (Fidelity::Tbbo, Replay::Full);
        let run = TickRun::new(
            &reader,
            fidelity,
            replay,
            &hours,
            settings,
            long_one(),
            &mut strategy,
        )
        .unwrap();

        let refused = run.run().unwrap_err();

        assert!(
            matches!(
                refused,
                RunError::TriggeredWithoutQuotes { order: 1, fidelity, .. } if fidelity == level
            ),
            "{refused}"
        );
    }
}

#[test]
fn a_stop_triggered_on_tbbo_fills_at_the_next_tradeable_quote_past_a_closed_date_of_trades() {
    // F-STP-02 with F-SES-02: the trades of 2026-03-07 fall in no session, so the next tradeable
    // record is 2026-03-08's TBBO record: fill = lower of (4995.00 - 0, bid 4987.75) = 4987.75.
    const DAY: i64 = 86_400_000;
    const MIDNIGHT: i64 = -52_200_000;
    let quoted = |milliseconds: i64, hundredths: i64| TbboRow {
        ts_recv: at(milliseconds),
        price: price(hundredths),
        size: Qty(1),
        bid: price(hundredths - 25),
        ask: price(hundredths),
        bid_size: Qty(1),
        ask_size: Qty(1),
    };
    let closed = TradeRow {
        ts_recv: at(DAY),
        price: price(499_000),
        size: Qty(2),
    };
    let days = vec![
        TapeDay {
            trade_date: TRADE_DATE,
            tbbo: vec![quoted(200, 500_000), quoted(400, 499_475)],
            trades: Vec::new(),
            bars: Default::default(),
        },
        TapeDay {
            trade_date: TradeDate(TRADE_DATE.0 + 1),
            tbbo: Vec::new(),
            trades: vec![closed],
            bars: Default::default(),
        },
        TapeDay {
            trade_date: TradeDate(TRADE_DATE.0 + 2),
            tbbo: vec![quoted(2 * DAY, 498_800)],
            trades: Vec::new(),
            bars: Default::default(),
        },
    ];
    let reader = InMemoryMarketData::new(Contract("ESH2026".to_owned()), days).unwrap();
    let session = |day: i64| Session {
        open: at(day * DAY + MIDNIGHT),
        close: at(day * DAY + MIDNIGHT + 21 * 3_600_000),
        halts: Vec::new(),
    };
    let hours = TradingHours::of_sessions(vec![session(0), session(2)]);
    let mut strategy = ScenarioOrders::new(vec![order(1, Side::Sell, stop(499_500))]);
    let settings = RunSettings::defaults_for(Fidelity::Tbbo);
    let (fidelity, replay) = (Fidelity::Tbbo, Replay::Full);
    let run = TickRun::new(
        &reader,
        fidelity,
        replay,
        &hours,
        settings,
        long_one(),
        &mut strategy,
    )
    .unwrap();

    let outputs = run.run().unwrap();

    assert_eq!(
        fills(&outputs),
        [(1, 2 * DAY, 498_775, PricingRule::StopAtNextQuote)]
    );
}

#[test]
fn a_trade_date_without_a_level_at_or_coarser_than_the_runs_fidelity_is_refused() {
    let reader = trades(&[(200, 500_000, 1)]);
    let (hours, mut strategy) = (TradingHours::always(), ScenarioOrders::new(Vec::new()));
    let fidelity = Fidelity::Bars(Timeframe::ONE_MINUTE);
    let settings = RunSettings::defaults_for(fidelity);
    let run = TickRun::new(
        &reader,
        fidelity,
        Replay::Full,
        &hours,
        settings,
        flat(),
        &mut strategy,
    )
    .unwrap();
    let refused = run.run().unwrap_err();
    assert_eq!(
        refused.to_string(),
        "Expected a level at or coarser than 1m on 2026-03-06, which holds trades"
    );
}

#[test]
fn a_day_holding_tbbo_and_trades_fills_on_tbbo_and_counts_in_a_tbbo_era() {
    // Step 2.12, Done means 3 (`02` §1.6, D-58): TBBO over trades, so the market buy fills at
    // the ask, 5000.25, with no slippage tick (F-MKT-01), where trades would fill it at the
    // print and one tick, 5000.00 (F-MKT-02), as a run capped at trades does.
    let both = day(
        vec![TbboRow {
            ts_recv: at(200),
            price: price(499_975),
            size: Qty(2),
            bid: price(499_975),
            ask: price(500_025),
            bid_size: Qty(6),
            ask_size: Qty(5),
        }],
        vec![TradeRow {
            ts_recv: at(200),
            price: price(499_975),
            size: Qty(2),
        }],
    );
    let buy = || vec![order(1, Side::Buy, OrderKind::Market)];

    let on_tbbo = run_orders(&both, Fidelity::Tbbo, flat(), buy());
    let capped_at_trades = run_orders(&both, Fidelity::Trades, flat(), buy());

    assert_eq!(
        fills(&on_tbbo),
        [(1, 200, 500_025, PricingRule::MarketAtQuote)]
    );
    assert_eq!(on_tbbo.fills[0].fill.fidelity, Fidelity::Tbbo);
    assert_eq!(
        on_tbbo.eras,
        [FidelityEra {
            first: TRADE_DATE,
            last: TRADE_DATE,
            trade_dates: 1,
            fidelity: Fidelity::Tbbo,
        }]
    );
    assert_eq!(
        fills(&capped_at_trades),
        [(1, 200, 500_000, PricingRule::MarketAtTrade)]
    );
    assert_eq!(capped_at_trades.eras[0].fidelity, Fidelity::Trades);
}

#[test]
fn a_run_counts_each_stretch_of_trade_dates_on_one_level_as_an_era() {
    // Step 2.12 (`02` §1.6): each date on its finest level at or coarser than the cap (D-58), so
    // a cap of trades falls to the bars of a date of TBBO and bars (BACKLOG.md).
    const DAY: i64 = 86_400_000;
    let dated = |offset: i32| TradeDate(TRADE_DATE.0 + offset);
    let quote = |offset: i64| TbboRow {
        ts_recv: at(offset * DAY + 200),
        price: price(500_000),
        size: Qty(1),
        bid: price(499_975),
        ask: price(500_000),
        bid_size: Qty(1),
        ask_size: Qty(1),
    };
    let print = |offset: i64| TradeRow {
        ts_recv: at(offset * DAY + 200),
        price: price(500_000),
        size: Qty(1),
    };
    let minute = |offset: i64| {
        let bar = BarRow {
            ts_open: at(offset * DAY),
            ts_close: at(offset * DAY + 60_000),
            open: price(500_000),
            high: price(500_000),
            low: price(500_000),
            close: price(500_000),
            volume: Qty(1),
        };
        BTreeMap::from([(Timeframe::ONE_MINUTE, vec![bar])])
    };
    let tape = |offset: i32, tbbo: bool, trades: bool| {
        let at_offset = i64::from(offset);
        TapeDay {
            trade_date: dated(offset),
            tbbo: if tbbo {
                vec![quote(at_offset)]
            } else {
                Vec::new()
            },
            trades: if trades {
                vec![print(at_offset)]
            } else {
                Vec::new()
            },
            bars: minute(at_offset),
        }
    };
    let days = vec![
        tape(0, true, true),
        tape(1, true, false),
        tape(2, false, true),
        tape(3, false, false),
    ];
    let reader = InMemoryMarketData::new(Contract("ESH2026".to_owned()), days).unwrap();
    let era = |first: i32, last: i32, fidelity: Fidelity| FidelityEra {
        first: dated(first),
        last: dated(last),
        trade_dates: usize::try_from(last - first + 1).unwrap(),
        fidelity,
    };
    let (minutes, trades) = (Fidelity::Bars(Timeframe::ONE_MINUTE), Fidelity::Trades);

    let eras = |cap: Fidelity| run_orders(&reader, cap, flat(), Vec::new()).eras;

    assert_eq!(
        eras(Fidelity::Tbbo),
        [
            era(0, 1, Fidelity::Tbbo),
            era(2, 2, trades),
            era(3, 3, minutes)
        ]
    );
    assert_eq!(
        eras(trades),
        [
            era(0, 0, trades),
            era(1, 1, minutes),
            era(2, 2, trades),
            era(3, 3, minutes)
        ]
    );
    assert_eq!(eras(minutes), [era(0, 3, minutes)]);
}

#[test]
fn a_longs_stop_and_target_inside_one_bar_resolve_to_the_stop_flagged_ambiguous() {
    // S-fill-022
    let reader = minutes(&[
        (0, [500_025, 500_300, 499_850, 500_175], 210),
        (1, [500_150, 501_125, 499_375, 500_600], 640),
    ]);
    let orders = vec![
        in_group(order(1, Side::Sell, stop(499_500)), 1),
        in_group(order(2, Side::Sell, limit(501_000)), 1),
    ];
    let outputs = run_orders(&reader, minute(), long_one(), orders);
    assert_eq!(
        fills(&outputs),
        [(1, 120_000, 499_475, PricingRule::StopOnBars)]
    );
    assert_eq!(ambiguity(&outputs), [(1, true)]);
    assert_eq!(outputs.fills[0].fill.fidelity, minute());
    assert_eq!(
        (outputs.ambiguous_fills(), logged_ambiguous(&outputs)),
        (1, 1)
    );
    assert_eq!(state_of(&outputs, 2), OrderState::Cancelled);
}

#[test]
fn a_stop_entry_and_its_bracket_stop_both_fill_in_one_bar_flagged_ambiguous() {
    // S-fill-024
    let reader = minutes(&[
        (0, [500_300, 500_450, 500_225, 500_400], 190),
        (1, [500_400, 501_300, 500_050, 500_825], 720),
    ]);
    let entry = order(1, Side::Buy, stop(500_500));
    let orders = vec![bracketed(entry, (2, 500_100), (3, 501_200))];
    let outputs = run_orders(&reader, minute(), flat(), orders);
    assert_eq!(
        fills(&outputs),
        [
            (1, 120_000, 500_525, PricingRule::StopOnBars),
            (2, 120_000, 500_075, PricingRule::StopOnBars),
        ]
    );
    assert_eq!(ambiguity(&outputs), [(1, true), (2, true)]);
    assert_eq!(outputs.ledger.position(), Position::Flat);
}

#[test]
fn of_an_oco_pair_of_entry_stops_inside_one_bar_the_lower_id_fills() {
    // S-fill-033
    let reader = minutes(&[(0, [500_000, 500_600, 499_400, 500_100], 400)]);
    let orders = vec![
        in_group(order(1, Side::Buy, stop(500_500)), 1),
        in_group(order(2, Side::Sell, stop(499_500)), 1),
    ];
    let outputs = run_orders(&reader, minute(), flat(), orders);
    assert_eq!(
        fills(&outputs),
        [(1, 60_000, 500_525, PricingRule::StopOnBars)]
    );
    assert_eq!(ambiguity(&outputs), [(1, true)]);
}

#[test]
fn a_bracket_stop_through_the_market_at_its_entrys_bar_open_fills_there() {
    // S-fill-040
    let reader = minutes(&[
        (0, [499_950, 500_025, 499_925, 500_000], 120),
        (1, [499_000, 499_200, 498_850, 499_100], 600),
    ]);
    let entry = ScenarioOrder {
        placed_at: at(60_000),
        ..order(1, Side::Buy, OrderKind::Market)
    };
    let orders = vec![bracketed(entry, (2, 499_500), (3, 501_000))];
    let outputs = run_orders(&reader, minute(), flat(), orders);
    assert_eq!(
        fills(&outputs),
        [
            (1, 120_000, 499_025, PricingRule::MarketAtBarOpen),
            (2, 120_000, 498_975, PricingRule::StopThroughMarket),
        ]
    );
    assert_eq!(ambiguity(&outputs), [(1, false), (2, false)]);
    assert_eq!(state_of(&outputs, 3), OrderState::Cancelled);
}

#[test]
fn a_stop_that_reverses_a_long_inside_a_bar_turns_the_path_adverse_for_the_short() {
    // S-fill-042
    let reader = minutes(&[(0, [500_000, 500_600, 499_400, 500_000], 500)]);
    let reversal = ScenarioOrder {
        lots: Qty(2),
        ..order(1, Side::Sell, stop(499_500))
    };
    let orders = vec![
        reversal,
        in_group(order(2, Side::Buy, stop(500_500)), 1),
        in_group(order(3, Side::Buy, limit(499_475)), 1),
    ];
    let outputs = run_orders(&reader, minute(), long_one(), orders);
    assert_eq!(
        fills(&outputs),
        [
            (1, 60_000, 499_475, PricingRule::StopOnBars),
            (2, 60_000, 500_525, PricingRule::StopOnBars),
        ]
    );
    assert_eq!(ambiguity(&outputs), [(1, false), (2, false)]);
}

#[test]
fn a_template_closes_at_its_flat_by_time_and_enters_nothing_after_it_that_day() {
    // S-template-003: 15:05 in Chicago on 2026-03-06 is 21:05 UTC, 23,700 s after 14:30.
    let spec: StrategySpec = serde_json::from_value(serde_json::json!({
        "spec_version": 1,
        "instrument": "ES",
        "timeframe": "5m",
        "execution": {
            "entry": {"kind": "market"},
            "stop": {"kind": "ticks", "ticks": 12},
            "targets": [{"price": {"kind": "ticks", "ticks": 24}}],
            "time": {"tz": "America/Chicago", "flat_by": "15:05"},
            "sizing": {"kind": "fixed", "units": 1}
        }
    }))
    .unwrap();
    let row = |seconds: i64, long_entry: bool| SignalRow {
        long_entry,
        flat_by: Some(at(23_700_000)),
        ..SignalRow::at(at(seconds * 1_000))
    };
    let rows = vec![
        row(22_800, true),
        row(23_400, false),
        row(23_700, false),
        row(24_000, true),
    ];
    let mut template = TemplateStrategy::new(&spec, rows, &es()).unwrap();
    let reader = bars(
        Timeframe::ONE_MINUTE,
        &[
            (22_800, 60, [500_000, 500_100, 499_950, 500_050], 80),
            (23_700, 60, [500_200, 500_250, 500_150, 500_225], 60),
            (24_000, 60, [500_300, 500_350, 500_275, 500_325], 40),
        ],
    );
    let outputs = run(&reader, minute(), flat(), &mut template);
    assert_eq!(
        fills(&outputs),
        [
            (1, 22_860_000, 500_025, PricingRule::MarketAtBarOpen),
            (4, 23_760_000, 500_175, PricingRule::MarketAtBarOpen),
        ]
    );
    assert_eq!(outputs.ledger.position(), Position::Flat);
}

#[test]
fn skipping_passes_over_records_no_order_can_act_on_and_ends_as_a_full_replay() {
    // S-template-006's trades, with the 1-second and 1-minute bars they make.
    let ticks = [
        (200, 500_000, 2),
        (30_000, 500_050, 1),
        (60_000, 499_900, 3),
        (80_000, 499_950, 1),
    ];
    let trades: Vec<TradeRow> = ticks
        .iter()
        .map(|&(milliseconds, hundredths, size)| TradeRow {
            ts_recv: at(milliseconds),
            price: price(hundredths),
            size: Qty(size),
        })
        .collect();
    let bar = |opens: i64, seconds: i64, held: &[TradeRow]| BarRow {
        ts_open: at(opens * 1_000),
        ts_close: at((opens + seconds) * 1_000),
        open: held[0].price,
        high: held.iter().map(|trade| trade.price).max().unwrap(),
        low: held.iter().map(|trade| trade.price).min().unwrap(),
        close: held[held.len() - 1].price,
        volume: Qty(held.iter().map(|trade| trade.size.0).sum()),
    };
    let second_bars = vec![
        bar(0, 1, &trades[0..1]),
        bar(30, 1, &trades[1..2]),
        bar(60, 1, &trades[2..3]),
        bar(80, 1, &trades[3..4]),
    ];
    let minute_bars = vec![bar(0, 60, &trades[0..2]), bar(60, 60, &trades[2..4])];
    let tape = TapeDay {
        trade_date: TRADE_DATE,
        tbbo: Vec::new(),
        trades,
        bars: BTreeMap::from([
            (Timeframe::ONE_SECOND, second_bars),
            (Timeframe::ONE_MINUTE, minute_bars),
        ]),
    };
    let reader = InMemoryMarketData::new(Contract("ESH2026".to_owned()), vec![tape]).unwrap();
    let far = vec![order(1, Side::Sell, stop(490_000))];
    let (hours, settings) = (
        TradingHours::always(),
        RunSettings::defaults_for(Fidelity::Trades),
    );
    let replayed = |replay: Replay| {
        let mut strategy = ScenarioOrders::new(far.clone());
        let mut run = TickRun::new(
            &reader,
            Fidelity::Trades,
            replay,
            &hours,
            settings,
            long_one(),
            &mut strategy,
        )
        .unwrap();
        let mut skipped = 0;
        while let Some(stepped) = run.step().unwrap() {
            if let Stepped::Skipped { units } = stepped {
                skipped += units;
            }
        }
        (run.run().unwrap(), skipped)
    };
    let (full, none_skipped) = replayed(Replay::Full);
    let (skipping, skipped) = replayed(Replay::Skipping);
    assert_eq!((none_skipped, skipped), (0, 3));
    assert_eq!(skipping, full);
    assert_eq!(skipping.ledger.mark(), Some(price(499_950)));
}

fn minute() -> Fidelity {
    Fidelity::Bars(Timeframe::ONE_MINUTE)
}

#[test]
fn a_trade_closed_in_parts_is_one_trade_at_its_exits_average_and_its_last_reason() {
    // Step 2.10 (BACKLOG's trades closed in parts, §20): a long of 2 lots whose first target
    // closes 1 and whose stop closes the other is one trade; its exit price is the two exits'
    // average and its exit reason the stop's. The marks after the entry reach 1 tick against it
    // and 5 for it, and the stop's fill at 4999.00, which closes it, 5 against it.
    let spec: StrategySpec = serde_json::from_value(serde_json::json!({
        "spec_version": 1,
        "instrument": "ES",
        "timeframe": "5m",
        "execution": {
            "entry": {"kind": "market"},
            "stop": {"kind": "ticks", "ticks": 4},
            "targets": [{"price": {"kind": "ticks", "ticks": 4}, "fraction": 0.5}],
            "sizing": {"kind": "fixed", "units": 2}
        }
    }))
    .unwrap();
    let rows = vec![
        SignalRow {
            long_entry: true,
            ..SignalRow::at(at(300_000))
        },
        SignalRow::at(at(301_500)),
    ];
    let mut template = TemplateStrategy::new(&spec, rows, &es()).unwrap();
    let reader = trades(&[
        (300_200, 500_000, 5),
        (301_000, 500_150, 1),
        (302_000, 499_900, 4),
    ]);

    let outputs = run(&reader, Fidelity::Trades, flat(), &mut template);

    assert_eq!(
        fills(&outputs),
        [
            (1, 300_200, 500_025, PricingRule::MarketAtTrade),
            (3, 301_000, 500_125, PricingRule::LimitAtItsPrice),
            (2, 302_000, 499_900, PricingRule::StopOnTrades),
        ]
    );
    let [trade] = outputs.trades.as_slice() else {
        panic!("Expected one trade, got {:?}", outputs.trades);
    };
    assert_eq!(
        (trade.side, trade.lots, trade.exits),
        (Side::Buy, Qty(2), 2)
    );
    assert_eq!(
        (trade.entry_decision, trade.entry_ts, trade.exit_ts),
        (at(300_000), at(300_200), at(302_000))
    );
    // (5001.25 + 4999.00) / 2 = 5000.125, in 1e-9 units.
    assert_eq!(trade.exit_price, Some(5_000_125_000_000.0));
    assert_eq!(trade.exit_reason.to_string(), "stop");
    assert_eq!((trade.initial_risk_ticks, trade.rolls), (Some(4), 0));
    assert_eq!((trade.mae_ticks, trade.mfe_ticks), (5, 5));
    assert_eq!(
        (trade.mae, trade.mfe),
        (Money(125 * MONEY_UNITS), Money(125 * MONEY_UNITS))
    );
    // 50 a point × (5001.25 + 4999.00 − 2 × 5000.25) = −12.50.
    assert_eq!(trade.gross_pnl, Money(-12_500_000));
    assert_eq!(
        (trade.fees, trade.funding, trade.pnl),
        (Money(0), Money(0), Money(-12_500_000))
    );
    assert_eq!(trade.entry_contract.0, "ESH2026");
    // The account at each decision: flat at the first, then 1 lot after the target's fill, its
    // value at the mark of 5001.50 on top of the cash: 50,112.50 of equity.
    let accounts: Vec<(Ts, i64, Option<Money>)> = outputs
        .equity
        .iter()
        .map(|point| (point.ts, point.position.0, point.equity))
        .collect();
    assert_eq!(
        accounts,
        [
            (at(300_000), 0, Some(Money(50_000 * MONEY_UNITS))),
            (at(301_500), 1, Some(Money(50_112_500_000))),
        ]
    );
    assert!(
        outputs
            .fills
            .iter()
            .all(|booked| booked.trade_date == TRADE_DATE)
    );
}

#[test]
fn a_fill_that_reverses_a_long_closes_its_trade_and_opens_a_short_with_the_rest() {
    // S-fill-042, §20: a sell of 2 lots against a long of 1 crosses flat, closing the long's
    // trade with one lot and opening a short with the other, the sell's 2 × 5000.75 × 50 =
    // 500,075.00 shared 250,037.50 each. The long's marks reach 5000.00, 1 tick against it, and
    // its exit's 5000.75, 2 for it; the short's 5001.00 after its entry, 1 against it, and its
    // exit's 4999.25, 6 for it.
    let reader = trades(&[(200, 500_000, 5), (1_200, 500_100, 5), (2_200, 499_900, 5)]);
    let orders = vec![
        order(1, Side::Buy, OrderKind::Market),
        ScenarioOrder {
            placed_at: at(1_000),
            lots: Qty(2),
            ..order(2, Side::Sell, OrderKind::Market)
        },
        ScenarioOrder {
            placed_at: at(2_000),
            ..order(3, Side::Buy, OrderKind::Market)
        },
    ];

    let outputs = run_orders(&reader, Fidelity::Trades, flat(), orders);

    assert_eq!(
        fills(&outputs),
        [
            (1, 200, 500_025, PricingRule::MarketAtTrade),
            (2, 1_200, 500_075, PricingRule::MarketAtTrade),
            (3, 2_200, 499_925, PricingRule::MarketAtTrade),
        ]
    );
    let [long, short] = outputs.trades.as_slice() else {
        panic!("Expected two trades, got {:?}", outputs.trades);
    };
    let exit_at = |hundredths: i64| Some(price(hundredths).0 as f64);
    assert_eq!(
        (long.side, long.lots, long.entry_price, long.exit_price),
        (Side::Buy, Qty(1), price(500_025), exit_at(500_075))
    );
    assert_eq!(
        (short.side, short.lots, short.entry_price, short.exit_price),
        (Side::Sell, Qty(1), price(500_075), exit_at(499_925))
    );
    assert_eq!(
        (short.entry_order, short.entry_decision, short.entry_ts),
        (OrderId(2), at(1_000), at(1_200))
    );
    // 50 a point: the long makes 0.50 points, 25.00, and the short 1.50, 75.00.
    assert_eq!(
        (long.gross_pnl, short.gross_pnl),
        (Money(25 * MONEY_UNITS), Money(75 * MONEY_UNITS))
    );
    assert_eq!((long.mae_ticks, long.mfe_ticks), (1, 2));
    assert_eq!((short.mae_ticks, short.mfe_ticks), (1, 6));
    assert_eq!(outputs.ledger.cash(), Money(50_100 * MONEY_UNITS));
}

#[test]
fn a_trades_initial_risk_is_its_plans_though_a_trailing_stop_raises_the_stop_at_the_fill() {
    // F-RND-02, F-PLN-04: the plan's risk is the 8 ticks from the fill at 5000.25 to its stop's
    // first level, 4998.25, though the trailing stop of 4 ticks raises the stop at once to
    // 4999.00, 4 below the market at the fill, 5000.00. It trails to 4999.50 at 5000.50 and fills
    // at 4999.00, 5 ticks against the trade.
    let spec: StrategySpec = serde_json::from_value(serde_json::json!({
        "spec_version": 1,
        "instrument": "ES",
        "timeframe": "5m",
        "execution": {
            "entry": {"kind": "market"},
            "stop": {"kind": "ticks", "ticks": 8},
            "trailing": {"by": {"kind": "ticks", "ticks": 4}},
            "sizing": {"kind": "fixed", "units": 1}
        }
    }))
    .unwrap();
    let rows = vec![
        SignalRow {
            long_entry: true,
            ..SignalRow::at(at(300_000))
        },
        SignalRow::at(at(301_500)),
    ];
    let mut template = TemplateStrategy::new(&spec, rows, &es()).unwrap();
    let reader = trades(&[
        (300_200, 500_000, 5),
        (301_000, 500_050, 1),
        (302_000, 499_900, 4),
    ]);

    let outputs = run(&reader, Fidelity::Trades, flat(), &mut template);

    assert_eq!(
        fills(&outputs),
        [
            (1, 300_200, 500_025, PricingRule::MarketAtTrade),
            (2, 302_000, 499_900, PricingRule::StopOnTrades),
        ]
    );
    let [trade] = outputs.trades.as_slice() else {
        panic!("Expected one trade, got {:?}", outputs.trades);
    };
    assert_eq!(trade.initial_risk_ticks, Some(8));
    assert_eq!((trade.mae_ticks, trade.mfe_ticks), (5, 1));
}
