//! The entries of the execution template, as `fefat.reference.template.entries` places them
//! (`docs/spec/fill-semantics.md` §25): the sides a row enters (F-ENT-01), the order each places
//! (F-ENT-02), the instant up to which a resting entry's time to live has ended (F-ENT-03), and
//! what an entry signal against the position does (F-ENT-04).

use std::num::NonZeroU32;

use fefat_core::instants::Ts;
use fefat_core::ledger::Position;
use fefat_core::orders::{OrderKind, Side, TimeInForce};
use fefat_core::strategy_spec::{EntryOrder, OppositeSignal};
use fefat_core::units::Price;

use super::SignalRow;
use super::exits::column_price;
use crate::strategy::DecisionError;

/// F-ENT-01: the sides a row enters, in order: `long_entry` buys, then `short_entry` sells. Under
/// a market entry a row gives one of them, the rows being refused otherwise; under a limit or a
/// stop entry a row that gives both places the pair, as one OCO group.
pub(super) fn f_ent_01(row: &SignalRow) -> Vec<Side> {
    let signals = [(row.long_entry, Side::Buy), (row.short_entry, Side::Sell)];
    let given = signals.into_iter().filter(|&(given, _)| given);
    given.map(|(_, side)| side).collect()
}

/// F-ENT-02: the order an entry on `side` places, with its price: a market order; a limit or a
/// stop at the row's `entry_price`, which must be there and on the tick; or a limit or a stop
/// `ticks` from the mark at the decision, a buy's limit under it and its stop above it. With no
/// mark yet an offset entry places nothing (none), and the template logs why.
pub(super) fn f_ent_02(
    entry: &EntryOrder,
    side: Side,
    row: &SignalRow,
    mark: Option<Price>,
    tick: Price,
) -> Result<Option<OrderKind>, DecisionError> {
    let entry_price = || column_price(row.entry_price, "entry_price", row, tick);
    let kind = match (entry, mark) {
        (EntryOrder::Market {}, _) => OrderKind::Market,
        (EntryOrder::LimitAtColumn { .. }, _) => OrderKind::Limit {
            limit: entry_price()?,
        },
        (EntryOrder::StopAtColumn { .. }, _) => OrderKind::StopMarket {
            stop: entry_price()?,
        },
        (EntryOrder::LimitOffset { .. } | EntryOrder::StopOffset { .. }, None) => return Ok(None),
        (EntryOrder::LimitOffset { ticks, .. }, Some(mark)) => OrderKind::Limit {
            limit: side.opposite().moved(mark, *ticks, tick)?,
        },
        (EntryOrder::StopOffset { ticks, .. }, Some(mark)) => OrderKind::StopMarket {
            stop: side.moved(mark, *ticks, tick)?,
        },
    };
    Ok(Some(kind))
}

/// F-ENT-03: the instant up to which the entries still live have reached their time to live at
/// the decision `now`: an entry with `time_to_live_bars` n is cancelled at the n-th decision after
/// the one that placed it, so those placed at or before the decision n before `now` go; none
/// without a time to live or before n decisions.
pub(super) fn f_ent_03(entry: &EntryOrder, rows: &[SignalRow], now: Ts) -> Option<Ts> {
    let time_to_live = usize::try_from(time_to_live(entry)?).ok()?;
    let index = rows
        .partition_point(|row| row.ts_close <= now)
        .checked_sub(1)?;
    let placed_by = index.checked_sub(time_to_live)?;
    rows.get(placed_by).map(|row| row.ts_close)
}

/// F-ENT-04: the side an entry signal against the position turns to: holding a long, a
/// `short_entry` closes it under `close` and `reverse`, the second entering short after the exit;
/// a short mirrors it. None when no such signal comes, or under `ignore`.
pub(super) fn f_ent_04(
    on_opposite: OppositeSignal,
    row: &SignalRow,
    position: Position,
) -> Option<Side> {
    let (against, opposite) = match position {
        Position::Flat => return None,
        Position::Long(_) => (Side::Sell, row.short_entry),
        Position::Short(_) => (Side::Buy, row.long_entry),
    };
    (on_opposite != OppositeSignal::Ignore && opposite).then_some(against)
}

/// How long the entries of `entry` work: for their time to live in signal bars, or until they
/// fill.
pub(super) fn time_in_force(entry: &EntryOrder) -> TimeInForce {
    let bars = time_to_live(entry).and_then(NonZeroU32::new);
    bars.map_or(TimeInForce::GoodTillCancelled, TimeInForce::Bars)
}

const fn time_to_live(entry: &EntryOrder) -> Option<u32> {
    match entry {
        EntryOrder::Market {} => None,
        EntryOrder::LimitAtColumn { time_to_live_bars }
        | EntryOrder::StopAtColumn { time_to_live_bars }
        | EntryOrder::LimitOffset {
            time_to_live_bars, ..
        }
        | EntryOrder::StopOffset {
            time_to_live_bars, ..
        } => *time_to_live_bars,
    }
}
