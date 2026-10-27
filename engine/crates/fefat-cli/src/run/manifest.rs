//! `run.json`, the cases of a batch: each case's instrument in the engines' integers (D-55), its
//! run settings as `fefat.reference.settings.RunSettings` writes them, its trading hours, its
//! capital and the position held when its tape starts, where its records come from and how they
//! are replayed, and what decides its orders: an order scenario's orders, or a `StrategySpec`
//! over its signal rows.

use std::collections::BTreeSet;
use std::iter;
use std::path::PathBuf;

use fefat_core::fidelity::Fidelity;
use fefat_core::instants::Ts;
use fefat_core::instrument::{InstrumentParameters, LotStep, NonPositiveParameter};
use fefat_core::ledger::{Ledger, LedgerError};
use fefat_core::orders::{OcoGroupId, OrderId, OrderKind, Side};
use fefat_core::strategy_spec::StrategySpec;
use fefat_core::units::{Money, Price, Qty};
use fefat_engine::book::{Bracket, BracketLeg, LegPrice};
use fefat_engine::hours::{Halt, Session, TradingHours};
use fefat_engine::settings::{LimitFill, RunSettings, SlippageTicks};
use fefat_engine::strategy::ScenarioOrder;
use fefat_engine::tick_run::Replay;
use serde::Deserialize;
use thiserror::Error;

/// The cases of a batch, in the order their rows' `case` column counts them, from 0.
#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct RunManifest {
    pub(super) cases: Vec<CaseManifest>,
}

/// One case of a batch.
#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct CaseManifest {
    /// A name for the case in errors, such as a scenario's id.
    pub(super) id: String,
    /// The finest data it fills on, `tbbo`, `trades`, or a bar timeframe: each trade date fills
    /// on its finest level at or coarser than this.
    pub(super) fidelity: Fidelity,
    replay: ReplayWord,
    /// The contract its records are of.
    pub(super) contract: String,
    instrument: InstrumentManifest,
    settings: SettingsManifest,
    hours: HoursManifest,
    /// The run's capital, the ledger's starting cash, in micro-units.
    capital: i64,
    position: Option<PositionManifest>,
    pub(super) market_data: MarketDataManifest,
    pub(super) decisions: DecisionsManifest,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct InstrumentManifest {
    tick_size: i64,
    money_per_point: i64,
    lot_step: i64,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct SettingsManifest {
    latency_ms: u32,
    slippage_ticks: SlippageManifest,
    limit_fill: LimitFillWord,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct SlippageManifest {
    market: u32,
    stop: u32,
}

#[derive(Debug, Clone, Copy, Deserialize)]
#[serde(rename_all = "snake_case")]
enum LimitFillWord {
    Through,
    Touch,
}

/// How the case's records are replayed: skipping what no order can act on, or in full.
#[derive(Debug, Clone, Copy, Deserialize)]
#[serde(rename_all = "snake_case")]
enum ReplayWord {
    Skipping,
    Full,
}

#[derive(Debug, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum HoursManifest {
    Always,
    Sessions { sessions: Vec<SessionManifest> },
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct SessionManifest {
    open: i64,
    close: i64,
    halts: Vec<HaltManifest>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct HaltManifest {
    start: i64,
    end: i64,
}

#[derive(Debug, Clone, Copy, Deserialize)]
#[serde(rename_all = "snake_case")]
enum PositionSide {
    Long,
    Short,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct PositionManifest {
    side: PositionSide,
    lots: i64,
    price: i64,
}

/// Where a case's records come from: the batch's own files of the levels it names, or an engine
/// cache's contract folder (step 2.5).
#[derive(Debug, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum MarketDataManifest {
    Tape { levels: Vec<Fidelity> },
    Cache { folder: PathBuf },
}

/// What decides a case's orders.
#[derive(Debug, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum DecisionsManifest {
    Orders { orders: Vec<OrderManifest> },
    Template { strategy: Box<StrategySpec> },
}

#[derive(Debug, Clone, Copy, Deserialize)]
#[serde(rename_all = "snake_case")]
enum SideWord {
    Buy,
    Sell,
}

#[derive(Debug, Clone, Copy, Deserialize)]
#[serde(rename_all = "snake_case")]
enum KindWord {
    Market,
    Stop,
    Limit,
}

impl KindWord {
    const fn word(self) -> &'static str {
        match self {
            Self::Market => "market",
            Self::Stop => "stop",
            Self::Limit => "limit",
        }
    }
}

/// An order of an order scenario, its `oco` group numbered and its bracket's legs named.
#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OrderManifest {
    id: u64,
    placed_at: i64,
    side: SideWord,
    kind: KindWord,
    price: Option<i64>,
    lots: i64,
    oco: Option<u64>,
    bracket: Option<BracketManifest>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct BracketManifest {
    stop: LegManifest,
    target: LegManifest,
}

#[derive(Debug, Clone, Copy, Deserialize)]
#[serde(deny_unknown_fields)]
struct LegManifest {
    id: u64,
    price: i64,
}

impl CaseManifest {
    pub(super) const fn replay(&self) -> Replay {
        match self.replay {
            ReplayWord::Skipping => Replay::Skipping,
            ReplayWord::Full => Replay::Full,
        }
    }

    /// The levels of the batch's files the case reads; none for a case on a cache.
    pub(super) fn tape_levels(&self) -> &[Fidelity] {
        match &self.market_data {
            MarketDataManifest::Tape { levels } => levels,
            MarketDataManifest::Cache { .. } => &[],
        }
    }

    pub(super) fn instrument(&self) -> Result<InstrumentParameters, NonPositiveParameter> {
        let instrument = &self.instrument;
        InstrumentParameters::new(
            Price(instrument.tick_size),
            Money(instrument.money_per_point),
            LotStep(instrument.lot_step),
        )
    }

    pub(super) const fn settings(&self) -> RunSettings {
        let settings = &self.settings;
        RunSettings {
            latency_milliseconds: settings.latency_ms,
            slippage: SlippageTicks {
                market: settings.slippage_ticks.market,
                stop: settings.slippage_ticks.stop,
            },
            limit_fill: match settings.limit_fill {
                LimitFillWord::Through => LimitFill::Through,
                LimitFillWord::Touch => LimitFill::Touch,
            },
        }
    }

    pub(super) fn hours(&self) -> TradingHours {
        let HoursManifest::Sessions { sessions } = &self.hours else {
            return TradingHours::always();
        };
        let sessions = sessions.iter().map(|session| Session {
            open: Ts(session.open),
            close: Ts(session.close),
            halts: session
                .halts
                .iter()
                .map(|halt| Halt {
                    start: Ts(halt.start),
                    end: Ts(halt.end),
                })
                .collect(),
        });
        TradingHours::of_sessions(sessions.collect())
    }

    /// The ledger the case starts from: its capital, and the position held when its tape starts.
    pub(super) fn ledger(&self, instrument: InstrumentParameters) -> Result<Ledger, LedgerError> {
        let capital = Money(self.capital);
        let Some(position) = &self.position else {
            return Ok(Ledger::new(instrument, capital));
        };
        let side = match position.side {
            PositionSide::Long => Side::Buy,
            PositionSide::Short => Side::Sell,
        };
        let (lots, price) = (Qty(position.lots), Price(position.price));
        Ledger::holding(instrument, capital, side, lots, price)
    }
}

/// An order whose kind and price disagree: a stop or a limit without a price, or a market order
/// with one.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
#[error(
    "Expected a price for a stop or a limit and none for a market order, got order {order} of \
     kind {kind} with price {price:?}"
)]
pub struct MispricedOrder {
    /// The order's id.
    order: u64,
    /// Its kind, as `run.json` writes it.
    kind: &'static str,
    /// The price it names, in 1e-9 units.
    price: Option<i64>,
}

/// Two orders of a case, or an order and a bracket's leg, under one id, which the reference's
/// scenarios refuse as well (`fefat.reference.scenarios`).
#[derive(Debug, Clone, PartialEq, Eq, Error)]
#[error(
    "Expected every order and bracket leg of a case under an id of its own, got order {order} twice"
)]
pub struct RepeatedOrderId {
    /// The id given twice.
    order: u64,
}

/// `orders`, refused when two of them, or an order and a bracket's leg, share an id.
pub(super) fn with_distinct_ids(
    orders: Vec<ScenarioOrder>,
) -> Result<Vec<ScenarioOrder>, RepeatedOrderId> {
    let mut given = BTreeSet::new();
    for order in &orders {
        let legs = order
            .bracket
            .iter()
            .flat_map(|bracket| [bracket.stop.id, bracket.target.id]);
        for id in iter::once(Some(order.id)).chain(legs).flatten() {
            if !given.insert(id) {
                return Err(RepeatedOrderId { order: id.0 });
            }
        }
    }
    Ok(orders)
}

impl OrderManifest {
    /// The order the scenario places, refused when its kind and its price disagree.
    pub(super) fn scenario_order(&self) -> Result<ScenarioOrder, MispricedOrder> {
        let kind = match (self.kind, self.price) {
            (KindWord::Market, None) => OrderKind::Market,
            (KindWord::Stop, Some(stop)) => OrderKind::StopMarket { stop: Price(stop) },
            (KindWord::Limit, Some(limit)) => OrderKind::Limit {
                limit: Price(limit),
            },
            (kind, price) => {
                return Err(MispricedOrder {
                    order: self.id,
                    kind: kind.word(),
                    price,
                });
            }
        };
        let leg = |leg: LegManifest| BracketLeg {
            id: Some(OrderId(leg.id)),
            price: LegPrice::At(Price(leg.price)),
        };
        Ok(ScenarioOrder {
            placed_at: Ts(self.placed_at),
            id: OrderId(self.id),
            side: match self.side {
                SideWord::Buy => Side::Buy,
                SideWord::Sell => Side::Sell,
            },
            lots: Qty(self.lots),
            kind,
            oco: self.oco.map(OcoGroupId),
            bracket: self.bracket.as_ref().map(|bracket| Bracket {
                stop: leg(bracket.stop),
                target: leg(bracket.target),
            }),
        })
    }
}
