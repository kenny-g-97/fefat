//! The decision context's rules that no scenario reaches alone.

use fefat_core::instants::Ts;
use fefat_core::instrument::{InstrumentParameters, LotStep};
use fefat_core::ledger::Ledger;
use fefat_core::orders::{ExitReason, OrderId, OrderKind, OrderState, Side};
use fefat_core::units::{Money, Price, Qty};

use super::{DecisionContext, ScenarioOrder};
use crate::book::Book;

#[test]
fn flatten_leaves_a_stop_triggered_on_tbbo_to_fill_as_the_market_order_it_is() {
    // F-STP-02, S-template-005: no decision cancels a triggered stop.
    let (mut book, mut log) = (Book::default(), Vec::new());
    let es = InstrumentParameters::new(Price(250_000_000), Money(50_000_000), LotStep(1));
    let ledger = Ledger::new(es.unwrap(), Money(0));
    let stop = ScenarioOrder {
        placed_at: Ts(0),
        id: OrderId(1),
        side: Side::Sell,
        lots: Qty(1),
        kind: OrderKind::StopMarket {
            stop: Price(4_999_000_000_000),
        },
        oco: None,
        bracket: None,
    };
    let mut placing = DecisionContext::new(&mut book, &mut log, &ledger, &[], Ts(0), 0, 0);
    placing.place(&stop).unwrap();
    book.activate(OrderId(1)).unwrap();
    book.trigger(OrderId(1)).unwrap();

    let mut later = DecisionContext::new(&mut book, &mut log, &ledger, &[], Ts(1), 1, 0);
    later.flatten(ExitReason::Strategy).unwrap();

    let still = book.live_in(OrderId(1), OrderState::Triggered);
    assert_eq!(still.map(|order| order.order.id), Some(OrderId(1)));
    assert_eq!(log.len(), 1, "{log:?}");
}

#[test]
fn equity_before_a_rolls_legs_values_the_position_at_its_own_contracts_price() {
    // F-ROL-03: until a roll's legs fill, the mark is the new front's and the position is worth
    // its own contract's price, the mark less the roll's gap, as the run's equity points are.
    let (mut book, mut log) = (Book::default(), Vec::new());
    let es = InstrumentParameters::new(Price(250_000_000), Money(50_000_000), LotStep(1));
    let bought = Price(5_000_000_000_000);
    let mut ledger = Ledger::holding(es.unwrap(), Money(0), Side::Buy, Qty(1), bought).unwrap();
    ledger.mark_at(Price(5_024_000_000_000));
    let gap = Price(20_000_000_000);

    let context = DecisionContext::new(&mut book, &mut log, &ledger, &[], Ts(0), 0, 0);
    let rolling = context.before_the_legs(gap);

    // Four points above the fill at 50 USD a point, where the mark alone gives 24.
    assert_eq!(rolling.equity(), Ok(Money(200_000_000)));
}
