//! The ledger's accounting (F-MRK-01, F-FEE-03), by hand and against a model in plain integers.

use proptest::prelude::*;

use super::*;
use crate::fidelity::Fidelity;
use crate::fills::{FillFlags, Liquidity, PricingRule};
use crate::instants::Ts;
use crate::instrument::LotStep;
use crate::orders::{OrderId, OrderRole};
use crate::units::{MONEY_UNITS, PRICE_UNITS};

const STARTING_CASH: Money = Money(50_000 * MONEY_UNITS);

/// The tick, the money per point per lot, and the lot step of real products: ES, MNQ, MCL, and
/// BTCUSDT-PERP's lots of 0.001 BTC, each tick worth a whole number of micro-units.
const PRODUCTS: [(i64, i64, i64); 4] = [
    (250_000_000, 50_000_000, PRICE_UNITS),
    (250_000_000, 2_000_000, PRICE_UNITS),
    (10_000_000, 100_000_000, PRICE_UNITS),
    (100_000_000, 1_000, 1_000_000),
];

fn instrument((tick, money_per_point, lot_step): (i64, i64, i64)) -> InstrumentParameters {
    InstrumentParameters::new(Price(tick), Money(money_per_point), LotStep(lot_step)).unwrap()
}

fn es() -> InstrumentParameters {
    instrument(PRODUCTS[0])
}

fn points(points: i64) -> Price {
    Price(points * PRICE_UNITS)
}

fn dollars(dollars: i64) -> Money {
    Money(dollars * MONEY_UNITS)
}

fn fill(side: Side, lots: i64, price: Price, fee: Money) -> Fill {
    Fill {
        order: OrderId(1),
        role: OrderRole::Entry,
        side,
        lots: Qty(lots),
        ts: Ts(0),
        price,
        rule: PricingRule::MarketAtTrade,
        fidelity: Fidelity::Trades,
        liquidity: Liquidity::Taker,
        slippage_ticks: 1,
        flags: FillFlags::default(),
        fee,
    }
}

#[test]
fn a_long_round_trip_books_its_profit() {
    let mut ledger = Ledger::new(es(), STARTING_CASH);
    ledger
        .book(&fill(Side::Buy, 2, points(5_000), Money(0)))
        .unwrap();
    ledger.mark_at(points(5_001));
    assert_eq!(ledger.cash(), dollars(-450_000));
    assert_eq!(ledger.position_value(), Ok(dollars(500_100)));
    assert_eq!(ledger.equity(), Ok(dollars(50_100)));
    ledger
        .book(&fill(Side::Sell, 2, points(5_001), Money(0)))
        .unwrap();
    assert_eq!(ledger.position(), Position::Flat);
    assert_eq!(ledger.cash(), dollars(50_100));
    assert_eq!(ledger.equity(), Ok(dollars(50_100)));
}

#[test]
fn a_short_round_trip_mirrors_it() {
    let mut ledger = Ledger::new(es(), STARTING_CASH);
    ledger
        .book(&fill(Side::Sell, 2, points(5_001), Money(0)))
        .unwrap();
    ledger.mark_at(points(5_000));
    assert_eq!(ledger.cash(), dollars(550_100));
    assert_eq!(ledger.position_value(), Ok(dollars(-500_000)));
    assert_eq!(ledger.equity(), Ok(dollars(50_100)));
    ledger
        .book(&fill(Side::Buy, 2, points(5_000), Money(0)))
        .unwrap();
    assert_eq!(ledger.position(), Position::Flat);
    assert_eq!(ledger.equity(), Ok(dollars(50_100)));
}

#[test]
fn a_fill_larger_than_the_position_reverses_it_through_flat() {
    let mut ledger = Ledger::new(es(), STARTING_CASH);
    ledger
        .book(&fill(Side::Buy, 1, points(5_000), Money(0)))
        .unwrap();
    ledger
        .book(&fill(Side::Sell, 3, points(5_000), Money(0)))
        .unwrap();
    assert_eq!(ledger.position(), Position::Short(HeldLots(Qty(2))));
    assert_eq!(ledger.position().signed_lots(), Qty(-2));
}

#[test]
fn a_short_beyond_64_bits_of_lots_is_refused() {
    let short = Position::Flat.after(Side::Sell, Qty(i64::MAX)).unwrap();
    assert_eq!(short.signed_lots(), Qty(-i64::MAX));
    assert!(matches!(
        short.after(Side::Sell, Qty(1)),
        Err(LedgerError::Overflow(_))
    ));
}

#[test]
fn a_maker_rebate_is_received_as_a_negative_fee() {
    let btc = instrument(PRODUCTS[3]);
    let mut ledger = Ledger::new(btc, STARTING_CASH);
    let one_basis_point = Money(-78_000);
    ledger
        .book(&fill(Side::Buy, 13, points(60_000), one_basis_point))
        .unwrap();
    assert_eq!(
        ledger.cash(),
        Money(STARTING_CASH.0 - 780 * MONEY_UNITS + 78_000)
    );
}

#[test]
fn the_debug_check_allows_the_widest_rounding_of_a_correct_booking() {
    let fraction_of_a_micro_unit = instrument((1, 1, 1));
    let mut lowest = Ledger::new(fraction_of_a_micro_unit, Money(0));
    lowest.mark_at(Price(999_999_999));
    lowest
        .book(&fill(Side::Buy, 1, Price(1), Money(0)))
        .unwrap();
    assert_eq!(lowest.equity(), Ok(Money(-1)));
    let mut highest = Ledger::new(fraction_of_a_micro_unit, Money(0));
    highest
        .book(&fill(Side::Buy, 1, Price(0), Money(0)))
        .unwrap();
    highest.mark_at(Price(999_999_999));
    highest
        .book(&fill(Side::Sell, 1, Price(0), Money(0)))
        .unwrap();
    assert_eq!(highest.equity(), Ok(Money(0)));
}

#[test]
fn a_fee_is_paid_from_the_cash_apart_from_the_fills_value() {
    let mut ledger = Ledger::new(es(), STARTING_CASH);
    let moved = ledger
        .book(&fill(Side::Buy, 1, points(5_000), Money(2_500_000)))
        .unwrap();
    assert_eq!(moved, dollars(-250_000));
    assert_eq!(ledger.cash(), Money(dollars(-200_000).0 - 2_500_000));
}

#[test]
fn an_inexact_amount_rounds_against_the_trader_on_either_side() {
    let fraction_of_a_micro_unit = instrument((1, 1, 1));
    for side in [Side::Buy, Side::Sell] {
        let mut ledger = Ledger::new(fraction_of_a_micro_unit, Money(0));
        ledger
            .book(&fill(side, 1, Price(333_333_333), Money(0)))
            .unwrap();
        ledger.mark_at(Price(333_333_333));
        assert_eq!(ledger.equity(), Ok(Money(-1)), "{side:?}");
    }
}

#[test]
fn a_fill_of_no_lots_is_refused_and_books_nothing() {
    let mut ledger = Ledger::new(es(), STARTING_CASH);
    let refused = ledger.book(&fill(Side::Buy, 0, points(5_000), Money(0)));
    assert_eq!(refused, Err(LedgerError::NonPositiveLots { lots: Qty(0) }));
    assert_eq!(ledger, Ledger::new(es(), STARTING_CASH));
}

#[test]
fn an_open_position_has_no_equity_before_its_first_mark() {
    let mut ledger = Ledger::new(es(), STARTING_CASH);
    assert_eq!(ledger.equity(), Ok(STARTING_CASH));
    ledger
        .book(&fill(Side::Buy, 1, points(5_000), Money(0)))
        .unwrap();
    let unmarked = LedgerError::UnmarkedPosition {
        position: Position::Long(HeldLots(Qty(1))),
    };
    assert_eq!(ledger.equity(), Err(unmarked));
}

#[test]
fn a_fill_beyond_64_bits_is_refused_and_books_nothing() {
    let mut ledger = Ledger::new(es(), Money(i64::MAX));
    let refused = ledger.book(&fill(Side::Sell, 1, points(5_000), Money(0)));
    assert!(matches!(refused, Err(LedgerError::Overflow(_))));
    assert_eq!(ledger, Ledger::new(es(), Money(i64::MAX)));
}

/// One random fill and the mark after it, in ticks of the instrument.
#[derive(Debug, Clone, Copy)]
struct Step {
    side: Side,
    lots: i64,
    price_ticks: i64,
    fee: i64,
    mark_ticks: i64,
}

fn steps() -> impl Strategy<Value = Vec<Step>> {
    let ticks = -20_000_i64..=20_000;
    let step = (
        any::<bool>(),
        1_i64..=50,
        ticks.clone(),
        0_i64..=5_000_000,
        ticks,
    )
        .prop_map(|(buys, lots, price_ticks, fee, mark_ticks)| Step {
            side: if buys { Side::Buy } else { Side::Sell },
            lots,
            price_ticks,
            fee,
            mark_ticks,
        });
    proptest::collection::vec(step, 1..60)
}

fn real_products() -> impl Strategy<Value = InstrumentParameters> {
    proptest::sample::select(PRODUCTS.to_vec()).prop_map(instrument)
}

fn any_instrument() -> impl Strategy<Value = InstrumentParameters> {
    let inexact = (1_i64..=PRICE_UNITS, 1_i64..=100_000_000)
        .prop_map(|(tick, money_per_point)| instrument((tick, money_per_point, PRICE_UNITS)));
    prop_oneof![real_products(), inexact]
}

/// The ledger's arithmetic redone in plain integers: each fill's value worked out exactly and
/// floored once, then paid or received with its fee, and the position's value at the mark
/// floored once.
struct Model {
    cash: i128,
    lots: i128,
    mark: i128,
    money_per_point: i128,
}

impl Model {
    fn book(&mut self, step: Step, tick: i64) {
        let bought = i128::from(match step.side {
            Side::Buy => step.lots,
            Side::Sell => -step.lots,
        });
        let price = i128::from(step.price_ticks * tick);
        self.cash += floor_of_billionths(-bought * price * self.money_per_point);
        self.cash -= i128::from(step.fee);
        self.lots += bought;
        self.mark = i128::from(step.mark_ticks * tick);
    }

    fn position_value(&self) -> i128 {
        floor_of_billionths(self.lots * self.mark * self.money_per_point)
    }
}

/// `exact / 1e9` rounded toward minus infinity, written without `div_euclid`, so that the model
/// does not repeat the ledger's arithmetic.
fn floor_of_billionths(exact: i128) -> i128 {
    let billion = 1_000_000_000;
    if exact >= 0 {
        exact / billion
    } else {
        -((-exact + billion - 1) / billion)
    }
}

/// The ledger's equity after each step, the prices and marks mirrored about `pivot_ticks` and
/// every side flipped when a pivot is given.
fn equities(
    instrument: InstrumentParameters,
    steps: &[Step],
    pivot_ticks: Option<i64>,
) -> Result<Vec<Money>, LedgerError> {
    let tick = instrument.tick_size().0;
    let mirror = |ticks: i64| pivot_ticks.map_or(ticks, |pivot| 2 * pivot - ticks);
    let mut ledger = Ledger::new(instrument, STARTING_CASH);
    let mut equities = Vec::new();
    for step in steps {
        let side = if pivot_ticks.is_some() {
            step.side.opposite()
        } else {
            step.side
        };
        let price = Price(mirror(step.price_ticks) * tick);
        ledger.book(&fill(side, step.lots, price, Money(step.fee)))?;
        ledger.mark_at(Price(mirror(step.mark_ticks) * tick));
        equities.push(ledger.equity()?);
    }
    Ok(equities)
}

proptest! {
    #[test]
    fn equity_is_cash_plus_position_value_under_random_fills(
        instrument in any_instrument(),
        steps in steps(),
    ) {
        let tick = instrument.tick_size().0;
        let money_per_point = i128::from(instrument.money_per_point().0);
        let mut ledger = Ledger::new(instrument, STARTING_CASH);
        let mut model = Model { cash: STARTING_CASH.0.into(), lots: 0, mark: 0, money_per_point };
        for step in steps {
            let price = Price(step.price_ticks * tick);
            ledger.book(&fill(step.side, step.lots, price, Money(step.fee)))?;
            ledger.mark_at(Price(step.mark_ticks * tick));
            model.book(step, tick);
            prop_assert_eq!(i128::from(ledger.cash().0), model.cash);
            prop_assert_eq!(i128::from(ledger.equity()?.0), model.cash + model.position_value());
        }
    }

    #[test]
    fn well_formed_fills_never_leave_a_negative_quantity(
        instrument in any_instrument(),
        steps in steps(),
    ) {
        let tick = instrument.tick_size().0;
        let mut ledger = Ledger::new(instrument, STARTING_CASH);
        let mut bought = 0;
        for step in steps {
            ledger.book(&fill(step.side, step.lots, Price(step.price_ticks * tick), Money(0)))?;
            bought += step.side.sign() * step.lots;
            let held = match ledger.position() {
                Position::Flat => 0,
                Position::Long(held) | Position::Short(held) => {
                    prop_assert!(held.lots().0 > 0, "{:?} holds no lots", ledger.position());
                    ledger.position().signed_lots().0
                }
            };
            prop_assert_eq!(held, bought);
        }
    }

    #[test]
    fn a_short_mirrors_a_long(
        instrument in real_products(),
        steps in steps(),
        pivot_ticks in 0_i64..=20_000,
    ) {
        let original = equities(instrument, &steps, None)?;
        let mirrored = equities(instrument, &steps, Some(pivot_ticks))?;
        prop_assert_eq!(original, mirrored);
    }
}
