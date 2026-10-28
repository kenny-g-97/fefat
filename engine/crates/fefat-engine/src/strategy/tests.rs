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
