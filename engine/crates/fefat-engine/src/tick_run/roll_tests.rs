//! Rolls, dated fees, and funding in the loop (step 2.9), on hand-written tapes transcribed from
//! the scenarios they cite; `python/tests/test_rust_engine_scenarios.py` runs every scenario
//! through both engines.

use fefat_core::costs::{CostLine, CostReason, FeeRate, FeeSchedule, FeeTable, FundingRate, Rate};
use fefat_core::fidelity::Fidelity;
use fefat_core::fills::PricingRule;
use fefat_core::instants::{TradeDate, Ts};
use fefat_core::instrument::{Contract, InstrumentParameters, LotStep};
use fefat_core::ledger::{Ledger, Position};
use fefat_core::market_data::{InMemoryMarketData, TapeDay, TradeRow};
use fefat_core::orders::{OrderId, OrderKind, OrderRole, Side};
use fefat_core::rolls::{Roll, RollReason};
use fefat_core::units::{MONEY_UNITS, Money, PRICE_UNITS, Price, Qty};

use super::*;
use crate::book::{Bracket, BracketLeg, LegPrice};
use crate::event_log::EventKind;
use crate::settings::{RollHandling, RunCosts};
use crate::strategy::{ScenarioOrder, ScenarioOrders};
use crate::template::{SignalRow, TemplateStrategy};
use fefat_core::strategy_spec::StrategySpec;

const SECOND: i64 = 1_000_000_000;
const MARCH_5: TradeDate = TradeDate(20_517);
const MARCH_6: TradeDate = TradeDate(20_518);
const MARCH_7: TradeDate = TradeDate(20_519);
const MARCH_9: TradeDate = TradeDate(20_521);
/// 2026-03-05T14:30:00Z.
const MARCH_5_14_30: i64 = 1_772_721_000;
/// 2026-03-06T14:30:00Z.
const MARCH_6_14_30: i64 = 1_772_807_400;
/// 2026-03-06T20:00:00Z.
const MARCH_6_20_00: i64 = 1_772_827_200;
/// 2026-03-08T22:00:00Z, the open of 2026-03-09's session, where ESM2026 becomes the front.
const ROLL_OPEN: i64 = 1_773_007_200;
/// 2026-03-09T13:30:00Z.
const MARCH_9_13_30: i64 = 1_773_063_000;
/// 2026-03-09T14:00:00Z.
const MARCH_9_14_00: i64 = 1_773_064_800;
/// 2026-03-07T16:00:00Z.
const MARCH_7_16_00: i64 = 1_772_899_200;

fn at(seconds: i64, milliseconds: i64) -> Ts {
    Ts(seconds * SECOND + milliseconds * 1_000_000)
}

fn price(hundredths: i64) -> Price {
    Price(hundredths * 10_000_000)
}

fn cents(cents: i64) -> Money {
    Money(cents * 10_000)
}

fn es() -> InstrumentParameters {
    InstrumentParameters::new(
        Price(250_000_000),
        Money(50 * MONEY_UNITS),
        LotStep(PRICE_UNITS),
    )
    .unwrap()
}

fn esh() -> Contract {
    Contract("ESH2026".to_owned())
}

fn esm() -> Contract {
    Contract("ESM2026".to_owned())
}

/// A trade of `(instant, price in hundredths, size)`.
type Trade = (Ts, i64, i64);

/// Trades by trade date, of `contract`.
fn trades(contract: Contract, days: &[(TradeDate, &[Trade])]) -> InMemoryMarketData {
    let days = days.iter().map(|&(trade_date, records)| {
        let rows = records.iter().map(|&(ts_recv, hundredths, size)| TradeRow {
            ts_recv,
            price: price(hundredths),
            size: Qty(size),
        });
        TapeDay {
            trade_date,
            tbbo: Vec::new(),
            trades: rows.collect(),
            bars: Default::default(),
        }
    });
    InMemoryMarketData::new(contract, days.collect()).unwrap()
}

/// The roll of S-fill-058 to S-fill-061: ESH2026 to ESM2026 at the open of 2026-03-09's session,
/// a gap of 20.00, on volume.
fn march_roll() -> Roll {
    Roll {
        session_open: at(ROLL_OPEN, 0),
        rolled_from: esh(),
        contract: esm(),
        gap: price(2_000),
        reason: RollReason::Volume,
    }
}

fn futures_fee(per_side: i64) -> RunCosts {
    let fee = FeeRate::Futures {
        per_contract_side: cents(per_side),
    };
    RunCosts {
        fees: Some(FeeTable::always(fee)),
        funding: Vec::new(),
    }
}

/// S-fill-058's long of `lots`, bought at the market at 14:30 on 03-06 with a stop at 4990.00 and
/// a target at 5030.00.
fn bracketed_long(lots: i64) -> ScenarioOrders {
    let leg = |id: u64, hundredths: i64| BracketLeg {
        id: Some(OrderId(id)),
        price: LegPrice::At(price(hundredths)),
    };
    ScenarioOrders::new(vec![ScenarioOrder {
        placed_at: at(MARCH_6_14_30, 0),
        id: OrderId(1),
        side: Side::Buy,
        lots: Qty(lots),
        kind: OrderKind::Market,
        oco: None,
        bracket: Some(Bracket {
            stop: leg(2, 499_000),
            target: leg(3, 503_000),
        }),
    }])
}

fn capital() -> Ledger {
    Ledger::new(es(), Money(50_000 * MONEY_UNITS))
}

/// `strategy` on `reader`'s trades from `ledger`, paying `costs`, across `rolls`.
fn run_on_trades(
    reader: &InMemoryMarketData,
    ledger: Ledger,
    strategy: &mut dyn Strategy,
    costs: RunCosts,
    rolls: (Vec<Roll>, RollHandling),
) -> Result<RunOutputs, RunError> {
    let hours = TradingHours::always();
    let settings = RunSettings::defaults_for(Fidelity::Trades);
    let (fidelity, replay) = (Fidelity::Trades, Replay::Full);
    let run = TickRun::new(reader, fidelity, replay, &hours, settings, ledger, strategy)?;
    let (rolls, handling) = rolls;
    run.with_costs(costs)?.with_rolls(rolls, handling)?.run()
}

/// Each fill's order, role, price in hundredths, rule, contract, and fee.
fn fills(outputs: &RunOutputs) -> Vec<(u64, OrderRole, i64, PricingRule, Contract, Money)> {
    let booked = outputs.fills.iter();
    booked
        .map(|booked| {
            let fill = booked.fill;
            let hundredths = fill.price.0 / 10_000_000;
            let contract = booked.contract.clone();
            (
                fill.order.0,
                fill.role,
                hundredths,
                fill.rule,
                contract,
                fill.fee,
            )
        })
        .collect()
}

/// Each entry of the log of `kind`: its order and its rule.
fn logged(outputs: &RunOutputs, kind: EventKind) -> Vec<(Option<u64>, Option<&'static str>)> {
    let entries = outputs.log.iter().filter(|entry| entry.kind == kind);
    entries
        .map(|entry| (entry.order.map(|order| order.0), entry.rule))
        .collect()
}

/// S-fill-058's tape: the long's fill and a mark on 03-06, the new front's first trade at
/// 5025.00, and its fall to the moved stop on 03-09.
fn across_the_roll() -> InMemoryMarketData {
    trades(
        esh(),
        &[
            (
                MARCH_6,
                &[
                    (at(MARCH_6_14_30, 200), 500_000, 3),
                    (at(MARCH_6_20_00, 0), 500_400, 2),
                ],
            ),
            (
                MARCH_9,
                &[
                    (at(ROLL_OPEN, 500), 502_500, 4),
                    (at(MARCH_9_14_00, 0), 500_975, 2),
                ],
            ),
        ],
    )
}

#[test]
fn a_roll_with_an_open_long_fills_two_legs_on_two_contracts_for_its_reason() {
    // S-fill-058, step 2.9's Done means 3: the close leg sells ESH2026 at the new front's first
    // trade less the gap, the open leg buys ESM2026 there, both a tick against the trader, both
    // costed and recorded as roll_volume; the bracket moves by the gap, and its stop fills on
    // ESM2026.
    let reader = across_the_roll();
    let rolls = (vec![march_roll()], RollHandling::Transfer);
    let outputs = run_on_trades(
        &reader,
        capital(),
        &mut bracketed_long(1),
        futures_fee(250),
        rolls,
    )
    .unwrap();

    let leg = OrderRole::Roll(RollReason::Volume);
    let fee = cents(250);
    assert_eq!(
        fills(&outputs),
        vec![
            (
                1,
                OrderRole::Entry,
                500_025,
                PricingRule::MarketAtTrade,
                esh(),
                fee
            ),
            (4, leg, 500_475, PricingRule::RollLeg, esh(), fee),
            (5, leg, 502_525, PricingRule::RollLeg, esm(), fee),
            (
                2,
                OrderRole::Stop,
                500_975,
                PricingRule::StopOnTrades,
                esm(),
                fee
            ),
        ]
    );
    assert_eq!(leg.to_string(), "roll_volume");
    assert_eq!(
        logged(&outputs, EventKind::Rolled),
        vec![(None, Some("F-ROL-01"))]
    );
    assert_eq!(
        logged(&outputs, EventKind::Moved),
        vec![(Some(2), Some("F-ROL-03")), (Some(3), Some("F-ROL-03"))]
    );
    let stop = outputs
        .orders
        .iter()
        .find(|order| order.order.id == OrderId(2));
    assert_eq!(stop.and_then(WorkingOrder::level), Some(price(501_000)));
    assert_eq!(outputs.ledger.cash(), Money(49_440 * MONEY_UNITS));
    assert_eq!(outputs.cost_lines.len(), 4);
}

#[test]
fn a_flattening_roll_closes_the_long_by_its_close_leg_alone_and_cancels_its_bracket() {
    // S-fill-060: with roll_handling flatten the bracket is cancelled at the roll and the close
    // leg alone sells the 2 lots, flagged against the trade's 1.
    let reader = trades(
        esh(),
        &[
            (MARCH_6, &[(at(MARCH_6_14_30, 200), 500_000, 3)]),
            (
                MARCH_9,
                &[
                    (at(ROLL_OPEN, 500), 502_500, 1),
                    (at(MARCH_9_14_00, 0), 500_975, 2),
                ],
            ),
        ],
    );
    let rolls = (vec![march_roll()], RollHandling::Flatten);
    let costs = RunCosts::default();
    let outputs = run_on_trades(&reader, capital(), &mut bracketed_long(2), costs, rolls).unwrap();

    let leg = OrderRole::Roll(RollReason::Volume);
    assert_eq!(
        fills(&outputs),
        vec![
            (
                1,
                OrderRole::Entry,
                500_025,
                PricingRule::MarketAtTrade,
                esh(),
                Money(0)
            ),
            (4, leg, 500_475, PricingRule::RollLeg, esh(), Money(0)),
        ]
    );
    assert!(outputs.fills[1].fill.flags.size_exceeded);
    assert_eq!(
        logged(&outputs, EventKind::Cancelled),
        vec![(Some(2), Some("F-ROL-04")), (Some(3), Some("F-ROL-04"))]
    );
    assert_eq!(outputs.ledger.position(), Position::Flat);
    assert!(outputs.cost_lines.is_empty());
}

#[test]
fn a_dated_fee_table_prices_each_fill_by_its_trade_date_and_warns_once() {
    // S-fill-062: 2.00 from 03-06 and 2.50 from 03-07; the buy on 03-05 takes the first schedule
    // with a warning, and the sell on 03-09 the second.
    let reader = trades(
        esh(),
        &[
            (MARCH_5, &[(at(MARCH_5_14_30, 200), 500_000, 3)]),
            (MARCH_9, &[(at(MARCH_9_13_30, 150), 501_000, 3)]),
        ],
    );
    let schedule = |trade_date: TradeDate, per_side: i64| FeeSchedule {
        effective_from: trade_date,
        fee: FeeRate::Futures {
            per_contract_side: cents(per_side),
        },
    };
    let table = FeeTable::new(vec![schedule(MARCH_6, 200), schedule(MARCH_7, 250)]).unwrap();
    let costs = RunCosts {
        fees: Some(table),
        funding: Vec::new(),
    };
    let order = |id: u64, placed: Ts, side: Side| ScenarioOrder {
        placed_at: placed,
        id: OrderId(id),
        side,
        lots: Qty(2),
        kind: OrderKind::Market,
        oco: None,
        bracket: None,
    };
    let mut strategy = ScenarioOrders::new(vec![
        order(1, at(MARCH_5_14_30, 0), Side::Buy),
        order(2, at(MARCH_9_13_30, 0), Side::Sell),
    ]);
    let rolls = (Vec::new(), RollHandling::Transfer);
    let outputs = run_on_trades(&reader, capital(), &mut strategy, costs, rolls).unwrap();

    let fees: Vec<Money> = outputs.fills.iter().map(|booked| booked.fill.fee).collect();
    assert_eq!(fees, vec![cents(400), cents(500)]);
    assert_eq!(
        logged(&outputs, EventKind::Warning),
        vec![(Some(1), Some("F-FEE-01"))]
    );
    let kinds: Vec<EventKind> = outputs.log.iter().map(|entry| entry.kind).collect();
    let warned = kinds.iter().position(|kind| *kind == EventKind::Warning);
    assert_eq!(
        warned.map(|at| kinds.get(at + 1)),
        Some(Some(&EventKind::Filled))
    );
    let paid: Vec<CostLine> = outputs.cost_lines.clone();
    assert_eq!(
        paid.iter()
            .map(|line| (line.reason, line.amount))
            .collect::<Vec<_>>(),
        vec![
            (CostReason::Fee { order: OrderId(1) }, cents(400)),
            (CostReason::Fee { order: OrderId(2) }, cents(500)),
        ]
    );
}

fn btc() -> InstrumentParameters {
    InstrumentParameters::new(Price(100_000_000), Money(1_000), LotStep(1_000_000)).unwrap()
}

#[test]
fn a_short_pays_a_negative_funding_rate_at_the_mark_before_the_trade_of_its_instant() {
    // S-fill-065: the short of 0.020 BTC is marked at 65123.7 when the funding of 16:00 comes,
    // before the trade received then, and pays 0.2604948, rounded against it to 0.260495.
    let reader = trades(
        Contract("BTCUSDT-PERP".to_owned()),
        &[(
            MARCH_7,
            &[
                (at(MARCH_7_16_00 - 1, 500), 6_512_370, 7),
                (at(MARCH_7_16_00, 0), 6_513_000, 3),
                (at(MARCH_7_16_00 + 1_800, 200), 6_515_000, 30),
            ],
        )],
    );
    let ledger = Ledger::holding(
        btc(),
        Money(50_000 * MONEY_UNITS),
        Side::Sell,
        Qty(20),
        price(6_500_000),
    )
    .unwrap();
    let rate = Rate(-200_000);
    let costs = RunCosts {
        fees: None,
        funding: vec![FundingRate {
            ts: at(MARCH_7_16_00, 0),
            rate,
        }],
    };
    let mut strategy = ScenarioOrders::new(vec![ScenarioOrder {
        placed_at: at(MARCH_7_16_00 + 1_800, 0),
        id: OrderId(1),
        side: Side::Buy,
        lots: Qty(20),
        kind: OrderKind::Market,
        oco: None,
        bracket: None,
    }]);
    let rolls = (Vec::new(), RollHandling::Transfer);
    let outputs = run_on_trades(&reader, ledger, &mut strategy, costs, rolls).unwrap();

    let funding = CostLine {
        ts: at(MARCH_7_16_00, 0),
        amount: Money(260_495),
        reason: CostReason::Funding { rate },
    };
    assert_eq!(outputs.cost_lines, vec![funding]);
    assert_eq!(
        logged(&outputs, EventKind::Funding),
        vec![(None, Some("F-FND-01"))]
    );
}

#[test]
fn funding_with_a_position_and_no_mark_is_refused() {
    // F-FND-01 pays at the mark: a position held when the tape starts has none before its first
    // tradeable record.
    let reader = trades(esh(), &[(MARCH_6, &[(at(MARCH_6_14_30, 200), 500_000, 3)])]);
    let ledger = Ledger::holding(es(), Money(0), Side::Buy, Qty(1), price(500_000)).unwrap();
    let costs = RunCosts {
        fees: None,
        funding: vec![FundingRate {
            ts: at(MARCH_6_14_30, 0),
            rate: Rate(100_000),
        }],
    };
    let rolls = (Vec::new(), RollHandling::Transfer);
    let outcome = run_on_trades(
        &reader,
        ledger,
        &mut ScenarioOrders::new(Vec::new()),
        costs,
        rolls,
    );

    assert_eq!(
        outcome,
        Err(RunError::FundingWithoutMark {
            at: at(MARCH_6_14_30, 0)
        })
    );
}

#[test]
fn rolls_that_do_not_chain_from_the_front_are_refused() {
    // F-ROL-01: the first roll rolls from the run's first front, the reader's contract.
    let reader = across_the_roll();
    let from_another = Roll {
        rolled_from: Contract("ESZ2025".to_owned()),
        ..march_roll()
    };
    let rolls = (vec![from_another], RollHandling::Transfer);
    let outcome = run_on_trades(
        &reader,
        capital(),
        &mut bracketed_long(1),
        RunCosts::default(),
        rolls,
    );

    assert_eq!(
        outcome,
        Err(RunError::RollFromAnotherFront {
            at: at(ROLL_OPEN, 0),
            front: esh(),
            rolled_from: Contract("ESZ2025".to_owned()),
            contract: esm(),
        })
    );
}

#[test]
fn a_roll_before_the_legs_of_the_roll_before_it_have_filled_is_refused() {
    // F-ROL-01: two rolls with no tradeable record between them leave the first one's legs on
    // their way.
    let reader = across_the_roll();
    let second = Roll {
        session_open: at(ROLL_OPEN, 100),
        rolled_from: esm(),
        contract: Contract("ESU2026".to_owned()),
        gap: price(2_000),
        reason: RollReason::Expiry,
    };
    let rolls = (vec![march_roll(), second], RollHandling::Transfer);
    let outcome = run_on_trades(
        &reader,
        capital(),
        &mut bracketed_long(1),
        RunCosts::default(),
        rolls,
    );

    assert_eq!(
        outcome,
        Err(RunError::RollBeforeItsLegs {
            at: at(ROLL_OPEN, 100)
        })
    );
}

#[test]
fn a_run_that_ends_before_the_legs_fill_values_the_long_at_its_own_contracts_price() {
    // F-ROL-03, your choice of 2026-10-29: the tape ends before the new front trades, so the
    // long is still on ESH2026 at the end, valued at its last trade, 5004.00, not at the mark
    // moved by the gap, 5024.00, which the run judges stops by.
    let reader = trades(
        esh(),
        &[(
            MARCH_6,
            &[
                (at(MARCH_6_14_30, 200), 500_000, 3),
                (at(MARCH_6_20_00, 0), 500_400, 2),
            ],
        )],
    );
    let rolls = (vec![march_roll()], RollHandling::Transfer);
    let outputs = run_on_trades(
        &reader,
        capital(),
        &mut bracketed_long(1),
        RunCosts::default(),
        rolls,
    )
    .unwrap();

    let placed = logged(&outputs, EventKind::Placed);
    let legs = placed.iter().filter(|(_, rule)| *rule == Some("F-ROL-02"));

    assert_eq!(outputs.ledger.mark(), Some(price(500_400)));
    assert_eq!(legs.count(), 2);
    assert_eq!(fills(&outputs).len(), 1);
}

#[test]
fn funding_times_or_rolls_out_of_order_or_repeated_are_refused() {
    // The loop takes its timers in order, each once, as the reference does (F-FND-01, F-ROL-01).
    let reader = across_the_roll();
    let rate = |seconds: i64| FundingRate {
        ts: at(seconds, 0),
        rate: Rate(100_000),
    };
    let backwards = RunCosts {
        fees: None,
        funding: vec![rate(MARCH_7_16_00), rate(MARCH_6_20_00)],
    };
    let no_rolls = (Vec::new(), RollHandling::Transfer);
    let to_esu = Roll {
        rolled_from: esm(),
        contract: Contract("ESU2026".to_owned()),
        ..march_roll()
    };
    let at_one_open = (vec![march_roll(), to_esu], RollHandling::Transfer);
    let mut nothing = ScenarioOrders::new(Vec::new());

    assert_eq!(
        run_on_trades(&reader, capital(), &mut nothing, backwards, no_rolls),
        Err(RunError::TimersOutOfOrder {
            what: "funding times",
            previous: at(MARCH_7_16_00, 0),
            next: at(MARCH_6_20_00, 0),
        })
    );
    assert_eq!(
        run_on_trades(
            &reader,
            capital(),
            &mut nothing,
            RunCosts::default(),
            at_one_open
        ),
        Err(RunError::TimersOutOfOrder {
            what: "rolls",
            previous: at(ROLL_OPEN, 0),
            next: at(ROLL_OPEN, 0),
        })
    );
}

#[test]
fn a_trade_across_a_roll_counts_its_legs_money_and_the_gap_in_its_excursions() {
    // Step 2.10 (BACKLOG's trades across a roll, §20): S-fill-058's long is one trade from its
    // entry on ESH2026 to its stop on ESM2026, through the roll's two legs; its profit and loss
    // is what all four fills moved the cash by less their fees, the ledger's 560.00 loss. Its
    // marks reach, the reference of 5000.25 moved by the gap of 20.00 to 5020.25, 19 ticks for it
    // at the new front's 5025.00, which is 5005.00 of the old contract, and its stop's fill at
    // 5009.75, which closes it, 42 against it.
    let reader = across_the_roll();
    let rolls = (vec![march_roll()], RollHandling::Transfer);
    let outputs = run_on_trades(
        &reader,
        capital(),
        &mut bracketed_long(1),
        futures_fee(250),
        rolls,
    )
    .unwrap();

    let [trade] = outputs.trades.as_slice() else {
        panic!("Expected one trade, got {:?}", outputs.trades);
    };
    assert_eq!((trade.exits, trade.rolls), (1, 1));
    assert_eq!(
        (trade.entry_contract.clone(), trade.exit_contract.clone()),
        (esh(), esm())
    );
    assert_eq!(trade.exit_reason, OrderRole::Stop);
    assert_eq!(trade.exit_price, Some(price(500_975).0 as f64));
    assert_eq!(trade.fees, cents(1_000));
    assert_eq!(trade.gross_pnl, Money(-550 * MONEY_UNITS));
    assert_eq!(trade.pnl, Money(-560 * MONEY_UNITS));
    assert_eq!(
        outputs.ledger.cash(),
        Money(50_000 * MONEY_UNITS).checked_add(trade.pnl).unwrap()
    );
    assert_eq!((trade.mae_ticks, trade.mfe_ticks), (42, 19));
    assert_eq!(trade.initial_risk_ticks, Some(41));
    let dates: Vec<TradeDate> = outputs
        .fills
        .iter()
        .map(|booked| booked.trade_date)
        .collect();
    assert_eq!(dates, [MARCH_6, MARCH_9, MARCH_9, MARCH_9]);
}

#[test]
fn funding_paid_while_a_trade_is_open_counts_in_its_profit_and_loss() {
    // F-FND-01 and §20: the long pays 0.0001 of 5000.00 × 50 at 15:30, 25.00, and its target's
    // fill at 5030.00 makes 1,487.50 before it.
    let reader = trades(
        esh(),
        &[(
            MARCH_6,
            &[
                (at(MARCH_6_14_30, 200), 500_000, 3),
                (at(MARCH_6_20_00, 0), 503_100, 2),
            ],
        )],
    );
    let funding = vec![FundingRate {
        ts: at(MARCH_6_14_30 + 3_600, 0),
        rate: Rate(100_000),
    }];
    let costs = RunCosts {
        fees: None,
        funding,
    };
    let rolls = (Vec::new(), RollHandling::Transfer);

    let outputs = run_on_trades(&reader, capital(), &mut bracketed_long(1), costs, rolls).unwrap();

    let [trade] = outputs.trades.as_slice() else {
        panic!("Expected one trade, got {:?}", outputs.trades);
    };
    assert_eq!(trade.exit_reason.to_string(), "target_1");
    assert_eq!(trade.funding, Money(-25 * MONEY_UNITS));
    assert_eq!(trade.gross_pnl, Money(1_487_500_000));
    assert_eq!(trade.pnl, Money(1_462_500_000));
}

#[test]
fn equity_at_a_decision_before_a_rolls_legs_values_the_position_at_its_own_contract() {
    // F-ROL-03: a decision after the roll and before the new front's first trade finds the
    // legs on their way, so the long is valued at the mark less the gap, 5004.00 of ESH2026, not
    // at the moved mark of 5024.00.
    let spec: StrategySpec = serde_json::from_value(serde_json::json!({
        "spec_version": 1,
        "instrument": "ES",
        "timeframe": "5m",
        "execution": {"entry": {"kind": "market"}, "sizing": {"kind": "fixed", "units": 1}}
    }))
    .unwrap();
    let rows = vec![
        SignalRow {
            long_entry: true,
            ..SignalRow::at(at(MARCH_6_14_30, 0))
        },
        SignalRow::at(at(ROLL_OPEN, 200)),
    ];
    let mut template = TemplateStrategy::new(&spec, rows, &es()).unwrap();
    let rolls = (vec![march_roll()], RollHandling::Transfer);

    let outputs = run_on_trades(
        &across_the_roll(),
        capital(),
        &mut template,
        RunCosts::default(),
        rolls,
    )
    .unwrap();

    let at_the_roll = outputs.equity.get(1).unwrap();
    assert_eq!(at_the_roll.ts, at(ROLL_OPEN, 200));
    assert_eq!(at_the_roll.mark, Some(price(500_400)));
    // 50,000 − 5000.25 × 50 + 5004.00 × 50 = 50,187.50.
    assert_eq!(at_the_roll.equity, Some(Money(50_187_500_000)));
}

#[test]
fn a_long_held_when_the_tape_starts_is_no_trade_though_a_roll_reopens_it() {
    // §20: no fill opened the long, so the roll's open leg, which buys it again on ESM2026 after
    // the close leg sold it on ESH2026, opens no trade, and the sell that closes it closes none.
    let reader = across_the_roll();
    let held = Ledger::holding(
        es(),
        Money(50_000 * MONEY_UNITS),
        Side::Buy,
        Qty(1),
        price(500_000),
    )
    .unwrap();
    let exit = ScenarioOrder {
        placed_at: at(MARCH_9_14_00 - 60, 0),
        id: OrderId(10),
        side: Side::Sell,
        lots: Qty(1),
        kind: OrderKind::Market,
        oco: None,
        bracket: None,
    };
    let rolls = (vec![march_roll()], RollHandling::Transfer);

    let outputs = run_on_trades(
        &reader,
        held,
        &mut ScenarioOrders::new(vec![exit]),
        futures_fee(250),
        rolls,
    )
    .unwrap();

    let roles: Vec<OrderRole> = fills(&outputs).into_iter().map(|fill| fill.1).collect();
    assert_eq!(
        roles,
        [
            OrderRole::Roll(RollReason::Volume),
            OrderRole::Roll(RollReason::Volume),
            OrderRole::Entry
        ]
    );
    assert!(outputs.trades.is_empty(), "{:?}", outputs.trades);
}
