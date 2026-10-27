//! The tick loop's part of the determinism digest (step 2.6): the seeded tape's trades and then
//! its TBBO records run through `TickRun` with seeded orders, and every order, fill, and entry of
//! the event log, with the final cash and position, hashed in order.

use fefat_core::ledger::Ledger;
use fefat_core::market_data::MarketDataReader;
use fefat_core::orders::{OrderId, OrderKind, Side};
use fefat_core::units::{MONEY_UNITS, Money, Price, Qty};
use fefat_engine::book::{Bracket, BracketLeg, LegPrice};
use fefat_engine::hours::TradingHours;
use fefat_engine::settings::RunSettings;
use fefat_engine::strategy::{ScenarioOrder, ScenarioOrders};
use fefat_engine::tick_run::{RunOutputs, TickFidelity, TickRun};

use super::{DeterminismError, es, hash_numbers};
use crate::seeded_tape::{SEEDED_TRADE_DATE, SplitMix64, TICK};

/// Every hundredth trade of the seeded tape's instant decides an order of the loop's run.
const TRADES_PER_ORDER: usize = 100;

/// BLAKE3 over every order, fill, and entry of the event log, and the final cash and position, of
/// the tick loop on the seeded tape's trades and then its TBBO records, with the same seeded
/// orders and the specification's default settings.
pub(super) fn loop_run_hash(
    reader: &impl MarketDataReader,
    generator: &mut SplitMix64,
) -> Result<blake3::Hash, DeterminismError> {
    let orders = seeded_orders(reader, generator)?;
    let hours = TradingHours::always();
    let mut hasher = blake3::Hasher::new();
    for level in [TickFidelity::Trades, TickFidelity::Tbbo] {
        let mut strategy = ScenarioOrders::new(orders.clone());
        let ledger = Ledger::new(es()?, Money(50_000 * MONEY_UNITS));
        let settings = RunSettings::defaults_for(level.fidelity());
        let run = TickRun::new(reader, level, &hours, settings, ledger, &mut strategy)?;
        hash_outputs(&mut hasher, &run.run()?);
    }
    Ok(hasher.finalize())
}

/// An order at every hundredth trade's instant: market, stop, or limit, on either side, one to
/// eight ticks from that trade's price, of one to five lots, every market entry with a bracket of
/// four to twelve ticks each way.
fn seeded_orders(
    reader: &impl MarketDataReader,
    generator: &mut SplitMix64,
) -> Result<Vec<ScenarioOrder>, DeterminismError> {
    let trades = reader.trades(SEEDED_TRADE_DATE)?;
    let decided = trades
        .ts_recv
        .iter()
        .zip(trades.price)
        .step_by(TRADES_PER_ORDER);
    let mut orders = Vec::new();
    for (number, (&placed_at, &price)) in (1_u64..).zip(decided) {
        let side = if generator.below(2) == 1 {
            Side::Buy
        } else {
            Side::Sell
        };
        let away = Price(TICK * (1 + generator.below(8)));
        let level = if generator.below(2) == 1 {
            price.checked_add(away)?
        } else {
            price.checked_sub(away)?
        };
        let kind = match generator.below(3) {
            0 => OrderKind::Market,
            1 => OrderKind::StopMarket { stop: level },
            _ => OrderKind::Limit { limit: level },
        };
        let mut leg = |id: u64| BracketLeg {
            id: Some(OrderId(id)),
            price: LegPrice::TicksFromFill(4 + generator.below_u32(9)),
        };
        let bracket = (kind == OrderKind::Market).then(|| Bracket {
            stop: leg(1_000 + number),
            target: leg(2_000 + number),
        });
        orders.push(ScenarioOrder {
            placed_at,
            id: OrderId(number),
            side,
            lots: Qty(1 + generator.below(5)),
            kind,
            oco: None,
            bracket,
        });
    }
    Ok(orders)
}

fn hash_outputs(hasher: &mut blake3::Hasher, outputs: &RunOutputs) {
    hash_numbers(
        hasher,
        [outputs.orders.len(), outputs.fills.len(), outputs.log.len()]
            .map(|count| count as i64)
            .into_iter(),
    );
    for order in &outputs.orders {
        let placed = &order.order;
        let level = order.level().map_or(0, |price| price.0);
        let oco = placed.oco.map_or(0, |group| group.0 as i64);
        let entry = order.link.leg_of().map_or(0, |entry| entry.0 as i64);
        hash_numbers(
            hasher,
            [placed.id.0 as i64, placed.side.sign(), level, placed.lots.0].into_iter(),
        );
        hash_numbers(
            hasher,
            [placed.placed_at.0, placed.activation.0, oco, entry].into_iter(),
        );
        hash_words(
            hasher,
            [
                placed.kind.to_string(),
                placed.role.to_string(),
                order.state().to_string(),
            ],
        );
    }
    for booked in &outputs.fills {
        let fill = &booked.fill;
        let flags = [fill.flags.ambiguous, fill.flags.size_exceeded].map(i64::from);
        hash_numbers(
            hasher,
            [
                fill.order.0 as i64,
                fill.side.sign(),
                fill.lots.0,
                fill.ts.0,
                fill.price.0,
            ]
            .into_iter(),
        );
        hash_numbers(
            hasher,
            [
                fill.slippage_ticks,
                fill.fee.0,
                booked.cash.0,
                flags[0],
                flags[1],
            ]
            .into_iter(),
        );
        hash_words(
            hasher,
            [
                fill.rule.id().to_owned(),
                fill.fidelity.to_string(),
                fill.liquidity.to_string(),
                fill.role.to_string(),
            ],
        );
    }
    for entry in &outputs.log {
        let order = entry.order.map_or(0, |order| order.0 as i64);
        hash_numbers(hasher, [entry.ts.0, order].into_iter());
        hash_words(
            hasher,
            [
                entry.kind.to_string(),
                entry.rule.unwrap_or("").to_owned(),
                entry.text.clone(),
            ],
        );
    }
    let held = outputs.ledger.position().signed_lots();
    hash_numbers(hasher, [outputs.ledger.cash().0, held.0].into_iter());
}

/// Each word framed by its length, so that two lists of words never share their bytes.
fn hash_words<const N: usize>(hasher: &mut blake3::Hasher, words: [String; N]) {
    for word in words {
        hasher.update(&(word.len() as u64).to_le_bytes());
        hasher.update(word.as_bytes());
    }
}
