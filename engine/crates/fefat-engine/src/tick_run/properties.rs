//! Done means 2 of step 2.6 as properties of the tick loop over random tapes: no fill before its
//! order's activation, nor on a record received while the market is closed; every fill on the
//! costly side of the trades its order saw, a buy never below the lowest and a sell never above the
//! highest, which TBBO's quotes, read no better than their trades, cannot break (F-SLP-01); and,
//! after every record, equity equal to cash plus the position's value at
//! the mark, with the cash and the position tracked apart from the ledger, from the fills alone.

use fefat_core::instants::{TradeDate, Ts};
use fefat_core::instrument::{Contract, InstrumentParameters, LotStep};
use fefat_core::ledger::Ledger;
use fefat_core::market_data::{InMemoryMarketData, TapeDay, TbboRow, TradeRow};
use fefat_core::orders::{OcoGroupId, OrderId, OrderKind, Side};
use fefat_core::units::{MONEY_UNITS, Money, PRICE_UNITS, Price, Qty};
use proptest::prelude::*;

use super::{Stepped, TickFidelity, TickRun};
use crate::book::{Bracket, BracketLeg, LegPrice};
use crate::hours::{Session, TradingHours};
use crate::settings::{LimitFill, RunSettings, SlippageTicks};
use crate::strategy::{ScenarioOrder, ScenarioOrders};

const TICK: i64 = 250_000_000;
const MONEY_PER_POINT: i64 = 50 * MONEY_UNITS;
const CAPITAL: i64 = 50_000 * MONEY_UNITS;
/// 2026-03-06T14:30:00Z.
const FIRST: i64 = 1_772_807_400 * 1_000_000_000;
const DAY: i64 = 86_400 * 1_000_000_000;
const MILLISECOND: i64 = 1_000_000;
const OPENING_PRICE: i64 = 5_000 * PRICE_UNITS;

#[derive(Debug, Clone)]
struct DrawnRecord {
    gap_milliseconds: i64,
    ticks_moved: i64,
    size: i64,
    bid_ticks: i64,
    spread_ticks: i64,
    bid_size: i64,
    ask_size: i64,
}

#[derive(Debug, Clone)]
struct DrawnBracket {
    in_ticks: bool,
    stop_ticks: i64,
    target_ticks: i64,
}

#[derive(Debug, Clone)]
struct DrawnOrder {
    decision: usize,
    buys: bool,
    class: u8,
    away_ticks: i64,
    lots: i64,
    bracket: Option<DrawnBracket>,
    grouped_with_next: bool,
}

#[derive(Debug, Clone)]
struct DrawnCase {
    tbbo: bool,
    records: Vec<DrawnRecord>,
    decisions: Vec<(usize, i64)>,
    orders: Vec<DrawnOrder>,
    opening: Option<(bool, i64)>,
    latency_milliseconds: u32,
    ticks: (u32, u32),
    touch: bool,
    closed: Option<(usize, usize)>,
}

fn drawn_record() -> impl Strategy<Value = DrawnRecord> {
    let gap = prop_oneof![3 => Just(0_i64), 7 => 1_i64..900];
    let moved = prop_oneof![8 => -2_i64..=2, 1 => -60_i64..=60];
    let quote = (-3_i64..=2, 1_i64..=3, 1_i64..=20, 1_i64..=20);
    (gap, moved, 1_i64..=20, quote).prop_map(
        |(gap_milliseconds, ticks_moved, size, (bid_ticks, spread_ticks, bid_size, ask_size))| {
            DrawnRecord {
                gap_milliseconds,
                ticks_moved,
                size,
                bid_ticks,
                spread_ticks,
                bid_size,
                ask_size,
            }
        },
    )
}

fn drawn_order() -> impl Strategy<Value = DrawnOrder> {
    let bracket =
        (any::<bool>(), 1_i64..=12, 1_i64..=12).prop_map(|(in_ticks, stop_ticks, target_ticks)| {
            DrawnBracket {
                in_ticks,
                stop_ticks,
                target_ticks,
            }
        });
    (
        0_usize..3,
        any::<bool>(),
        0_u8..3,
        -30_i64..=30,
        1_i64..=3,
        proptest::option::of(bracket),
        any::<bool>(),
    )
        .prop_map(
            |(decision, buys, class, away_ticks, lots, bracket, grouped_with_next)| DrawnOrder {
                decision,
                buys,
                class,
                away_ticks,
                lots,
                bracket,
                grouped_with_next,
            },
        )
}

fn drawn_case() -> impl Strategy<Value = DrawnCase> {
    let records = proptest::collection::vec(drawn_record(), 1..40);
    let decisions = proptest::collection::vec((0_usize..40, -300_i64..300), 3);
    let orders = proptest::collection::vec(drawn_order(), 1..5);
    let opening = proptest::option::of((any::<bool>(), 1_i64..=3));
    let settings = (
        prop_oneof![Just(0_u32), Just(100), Just(1_000)],
        (0_u32..=2, 0_u32..=2),
        any::<bool>(),
    );
    let closed = proptest::option::of((0_usize..40, 0_usize..40));
    (
        any::<bool>(),
        records,
        decisions,
        orders,
        opening,
        settings,
        closed,
    )
        .prop_map(
            |(tbbo, records, decisions, orders, opening, settings, closed)| DrawnCase {
                tbbo,
                records,
                decisions,
                orders,
                opening,
                latency_milliseconds: settings.0,
                ticks: settings.1,
                touch: settings.2,
                closed,
            },
        )
}

fn side(buys: bool) -> Side {
    if buys { Side::Buy } else { Side::Sell }
}

fn rows(case: &DrawnCase) -> (Vec<TradeRow>, Vec<TbboRow>) {
    let (mut ts, mut price) = (FIRST, OPENING_PRICE);
    let mut trades = Vec::new();
    let mut tbbo = Vec::new();
    for record in &case.records {
        ts += record.gap_milliseconds * MILLISECOND;
        price += record.ticks_moved * TICK;
        let bid = price + record.bid_ticks * TICK;
        let trade = TradeRow {
            ts_recv: Ts(ts),
            price: Price(price),
            size: Qty(record.size),
        };
        tbbo.push(TbboRow {
            ts_recv: trade.ts_recv,
            price: trade.price,
            size: trade.size,
            bid: Price(bid),
            ask: Price(bid + record.spread_ticks * TICK),
            bid_size: Qty(record.bid_size),
            ask_size: Qty(record.ask_size),
        });
        trades.push(trade);
    }
    (trades, tbbo)
}

fn order_of(drawn: &DrawnOrder, id: u64, group: Option<u64>, placed_at: Ts) -> ScenarioOrder {
    let side = side(drawn.buys);
    let level = Price(OPENING_PRICE + drawn.away_ticks * TICK);
    let kind = match drawn.class {
        0 => OrderKind::Market,
        1 => OrderKind::StopMarket { stop: level },
        _ => OrderKind::Limit { limit: level },
    };
    let bracket = drawn.bracket.as_ref().map(|bracket| {
        let leg = |leg_id: u64, ticks: i64, against: bool| {
            let away = if against == (side == Side::Buy) {
                -ticks
            } else {
                ticks
            };
            let price = if bracket.in_ticks {
                LegPrice::TicksFromFill(u32::try_from(ticks).unwrap())
            } else {
                LegPrice::At(Price(OPENING_PRICE + away * TICK))
            };
            BracketLeg {
                id: Some(OrderId(leg_id)),
                price,
            }
        };
        Bracket {
            stop: leg(id + 100, bracket.stop_ticks, true),
            target: leg(id + 200, bracket.target_ticks, false),
        }
    });
    ScenarioOrder {
        placed_at,
        id: OrderId(id),
        side,
        lots: Qty(drawn.lots),
        kind,
        oco: group.map(OcoGroupId),
        bracket,
    }
}

fn orders(case: &DrawnCase, trades: &[TradeRow]) -> Vec<ScenarioOrder> {
    let instants: Vec<Ts> = case
        .decisions
        .iter()
        .map(|&(record, offset)| {
            let near = trades[record.min(trades.len() - 1)].ts_recv.0;
            Ts(near + offset * MILLISECOND)
        })
        .collect();
    let mut placed = Vec::new();
    let mut group = None;
    for (index, drawn) in case.orders.iter().enumerate() {
        let id = u64::try_from(index).unwrap() + 1;
        let in_group = group.or(drawn.grouped_with_next.then_some(id));
        placed.push(order_of(drawn, id, in_group, instants[drawn.decision]));
        group = if group.is_none() && drawn.grouped_with_next {
            Some(id)
        } else {
            None
        };
    }
    placed
}

fn hours(case: &DrawnCase, trades: &[TradeRow]) -> TradingHours {
    let Some((first, second)) = case.closed else {
        return TradingHours::always();
    };
    let last = trades.len() - 1;
    let (from, to) = (first.min(second).min(last), first.max(second).min(last));
    TradingHours::of_sessions(vec![
        Session {
            open: Ts(FIRST - DAY),
            close: trades[from].ts_recv,
            halts: Vec::new(),
        },
        Session {
            open: Ts(trades[to].ts_recv.0 + 1),
            close: Ts(FIRST + DAY),
            halts: Vec::new(),
        },
    ])
}

/// What the lots are worth at the price, floored once, worked out apart from the ledger.
fn value(price: i64, lots: i64) -> i64 {
    let exact = i128::from(price) * i128::from(lots) * i128::from(MONEY_PER_POINT);
    i64::try_from(exact.div_euclid(i128::from(PRICE_UNITS))).unwrap()
}

/// A record the run saw: when, whether the market traded, and its trade's price.
struct SeenRecord {
    index: usize,
    ts: Ts,
    tradeable: bool,
    price: Price,
}

proptest! {
    #[test]
    fn fills_follow_activation_lie_on_the_costly_side_and_equity_is_cash_plus_value(
        case in drawn_case(),
    ) {
        let (trades, tbbo) = rows(&case);
        let level = if case.tbbo { TickFidelity::Tbbo } else { TickFidelity::Trades };
        let tape = TapeDay {
            trade_date: TradeDate(20_518),
            tbbo: if case.tbbo { tbbo } else { Vec::new() },
            trades: if case.tbbo { Vec::new() } else { trades.clone() },
            bars: Default::default(),
        };
        let reader = InMemoryMarketData::new(Contract("ESH2026".to_owned()), vec![tape]).unwrap();
        let hours = hours(&case, &trades);
        let settings = RunSettings {
            latency_milliseconds: case.latency_milliseconds,
            slippage: SlippageTicks { market: case.ticks.0, stop: case.ticks.1 },
            limit_fill: if case.touch { LimitFill::Touch } else { LimitFill::Through },
        };
        let instrument =
            InstrumentParameters::new(Price(TICK), Money(MONEY_PER_POINT), LotStep(PRICE_UNITS))
                .unwrap();
        let (mut cash, mut held) = (CAPITAL, 0_i64);
        let ledger = match case.opening {
            None => Ledger::new(instrument, Money(CAPITAL)),
            Some((buys, lots)) => {
                held = side(buys).sign() * lots;
                cash += value(OPENING_PRICE, -held);
                Ledger::holding(instrument, Money(CAPITAL), side(buys), Qty(lots), Price(OPENING_PRICE))
                    .unwrap()
            }
        };
        let mut strategy = ScenarioOrders::new(orders(&case, &trades));
        let mut run = TickRun::new(&reader, level, &hours, settings, ledger, &mut strategy).unwrap();
        let (mut seen, mut mark, mut checked, mut index) = (Vec::new(), None, 0, 0);
        while let Some(stepped) = run.step().unwrap() {
            if let Stepped::Record(record) = stepped {
                let tradeable = hours.is_open(record.ts);
                seen.push(SeenRecord { index, ts: record.ts, tradeable, price: record.price });
                if tradeable {
                    mark = Some(record.price.0);
                }
            }
            for booked in &run.fills()[checked..] {
                let fill = booked.fill;
                let order = run.order(fill.order).unwrap();
                prop_assert!(fill.ts >= order.order.activation, "{fill:?} before {order:?}");
                prop_assert!(index > order.seen_after, "{fill:?} at {index} for {order:?}");
                let filled_on = seen.last().filter(|record| record.index == index);
                prop_assert!(filled_on.is_some_and(|record| record.tradeable), "{fill:?}");
                let saw: Vec<&SeenRecord> = seen
                    .iter()
                    .filter(|record| record.index > order.seen_after)
                    .filter(|record| record.ts >= order.order.activation && record.tradeable)
                    .collect();
                let low = saw.iter().map(|record| record.price).min().unwrap();
                let high = saw.iter().map(|record| record.price).max().unwrap();
                match fill.side {
                    Side::Buy => prop_assert!(fill.price >= low, "{fill:?} below {low}"),
                    Side::Sell => prop_assert!(fill.price <= high, "{fill:?} above {high}"),
                }
                let moved = value(fill.price.0, -fill.side.sign() * fill.lots.0);
                prop_assert_eq!(booked.cash, Money(moved));
                cash += moved;
                held += fill.side.sign() * fill.lots.0;
            }
            checked = run.fills().len();
            let ledger = run.ledger();
            prop_assert_eq!(ledger.cash(), Money(cash));
            prop_assert_eq!(ledger.position().signed_lots(), Qty(held));
            prop_assert_eq!(ledger.mark().map(|price| price.0), mark);
            match (held, mark) {
                (0, _) => prop_assert_eq!(ledger.equity(), Ok(Money(cash))),
                (_, Some(mark)) => {
                    prop_assert_eq!(ledger.equity(), Ok(Money(cash + value(mark, held))));
                }
                (_, None) => prop_assert!(ledger.equity().is_err()),
            }
            index += 1;
        }
    }
}
