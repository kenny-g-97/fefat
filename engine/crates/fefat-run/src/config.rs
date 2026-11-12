//! A run's config (step 2.10): what a run reads beside its specification and its signal frame,
//! every setting applied, in the engines' integers (D-51, D-55): the finest data it fills on, its
//! instrument, its run settings as `fefat.reference.settings.RunSettings` writes them, the hours
//! its market trades in, its capital and the position held when its tape starts, and what it pays
//! and rolls across (step 2.9), its fee table, a perpetual's funding rates, and a future's rolls,
//! each left out where it has none. `fefat.reference.run_documents` writes it as JSON. The run
//! key hashes it as serde writes it (`02` §4), so that two runs that differ in a setting have two
//! keys; from step 5.3 it also holds the parameter count of a saved strategy version, which the
//! engine never reads and the run key covers.

use fefat_core::costs::{FeeRate, FeeSchedule, FeeTable, FeeTableError, FundingRate, Rate};
use fefat_core::fidelity::Fidelity;
use fefat_core::instants::{TradeDate, Ts};
use fefat_core::instrument::{Contract, InstrumentParameters, LotStep, NonPositiveParameter};
use fefat_core::ledger::{Ledger, LedgerError};
use fefat_core::orders::Side;
use fefat_core::rolls::{Roll, RollReason};
use fefat_core::units::{Money, Price, Qty};
use fefat_engine::hours::{Halt, Session, TradingHours};
use fefat_engine::settings::{LimitFill, RollHandling, RunCosts, RunSettings, SlippageTicks};
use serde::{Deserialize, Serialize};

/// What a run reads beside its specification and its signal frame.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RunConfig {
    /// The finest data it fills on, `tbbo`, `trades`, or a bar timeframe: each trade date fills
    /// on its finest level at or coarser than this (D-58).
    pub fidelity: Fidelity,
    instrument: InstrumentConfig,
    settings: SettingsConfig,
    hours: HoursConfig,
    /// The run's capital, the ledger's starting cash, in micro-units.
    capital: i64,
    position: Option<PositionConfig>,
    /// The fee table, none where the run names none.
    #[serde(default)]
    fees: Option<FeesConfig>,
    /// A perpetual's funding rates, in the order of their times.
    #[serde(default)]
    funding: Vec<FundingConfig>,
    /// A future's rolls, in the order of their opens.
    #[serde(default)]
    rolls: Vec<RollConfig>,
    /// The parameters a saved strategy version declares, which its metrics' robustness summary
    /// counts (step 5.3); the engine reads none of it, and a config without one writes the
    /// JSON it wrote before, so that the run key covers the count and no other run's key moves.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    declared_parameters: Option<u32>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct InstrumentConfig {
    tick_size: i64,
    money_per_point: i64,
    lot_step: i64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct SettingsConfig {
    latency_ms: u32,
    slippage_ticks: SlippageConfig,
    limit_fill: LimitFillWord,
    #[serde(default)]
    roll_handling: RollHandlingWord,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum RollHandlingWord {
    #[default]
    Transfer,
    Flatten,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct SlippageConfig {
    market: u32,
    stop: u32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum LimitFillWord {
    Through,
    Touch,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum HoursConfig {
    Always,
    Sessions { sessions: Vec<SessionConfig> },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct SessionConfig {
    open: i64,
    close: i64,
    halts: Vec<HaltConfig>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct HaltConfig {
    start: i64,
    end: i64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum PositionSide {
    Long,
    Short,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct PositionConfig {
    side: PositionSide,
    lots: i64,
    price: i64,
}

/// A fee table, its schedules in the order of their dates, all of its kind.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum FeesConfig {
    Futures {
        schedules: Vec<FuturesScheduleConfig>,
    },
    Crypto {
        schedules: Vec<CryptoScheduleConfig>,
    },
}

/// A futures fee from a trade date, in days since 1970-01-01, per contract per side in
/// micro-units.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct FuturesScheduleConfig {
    effective_from: i32,
    per_contract_side: i64,
}

/// A crypto fee from a trade date, its maker and taker rates in 1e-9 units.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct CryptoScheduleConfig {
    effective_from: i32,
    maker_rate: i64,
    taker_rate: i64,
}

/// A funding rate in 1e-9 units, paid at `ts`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct FundingConfig {
    ts: i64,
    rate: i64,
}

/// A roll as the roll calendar gives it, with the trade date of the session it opens, from which
/// the new front serves the run.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct RollConfig {
    trade_date: i32,
    session_open: i64,
    rolled_from: String,
    contract: String,
    gap: i64,
    reason: RollReasonWord,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
enum RollReasonWord {
    Volume,
    OpenInterest,
    Calendar,
    Expiry,
}

impl RunConfig {
    /// The instrument's parameters in the engines' integers.
    pub fn instrument(&self) -> Result<InstrumentParameters, NonPositiveParameter> {
        let instrument = &self.instrument;
        InstrumentParameters::new(
            Price(instrument.tick_size),
            Money(instrument.money_per_point),
            LotStep(instrument.lot_step),
        )
    }

    /// The run settings of F-ACT-01, F-SLP-01, F-LMT-01, and F-LMT-02.
    pub const fn settings(&self) -> RunSettings {
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

    /// What a roll does with an open position (F-ROL-02, F-ROL-04).
    pub const fn roll_handling(&self) -> RollHandling {
        match self.settings.roll_handling {
            RollHandlingWord::Transfer => RollHandling::Transfer,
            RollHandlingWord::Flatten => RollHandling::Flatten,
        }
    }

    /// What the run pays: its fee table and its funding rates (§14).
    pub fn costs(&self) -> Result<RunCosts, FeeTableError> {
        let fees = self.fees.as_ref().map(FeesConfig::table).transpose()?;
        let funding = self.funding.iter().map(FundingConfig::rate).collect();
        Ok(RunCosts { fees, funding })
    }

    /// The run's rolls, in the order of their opens (F-ROL-01).
    pub fn rolls(&self) -> Vec<Roll> {
        self.rolls.iter().map(RollConfig::roll).collect()
    }

    /// Each roll's trade date and new front, in the order of their opens: the first trade date
    /// each front after the first serves.
    pub fn fronts_from(&self) -> Vec<(TradeDate, Contract)> {
        let fronts = self.rolls.iter().map(|roll| {
            let contract = Contract(roll.contract.clone());
            (TradeDate(roll.trade_date), contract)
        });
        fronts.collect()
    }

    /// The hours its market trades in (F-SES-02).
    pub fn hours(&self) -> TradingHours {
        let HoursConfig::Sessions { sessions } = &self.hours else {
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

    /// The ledger the run starts from: its capital, and the position held when its tape starts.
    pub fn ledger(&self, instrument: InstrumentParameters) -> Result<Ledger, LedgerError> {
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

impl FeesConfig {
    /// The fee table, its schedules in the order of their dates (F-FEE-01).
    fn table(&self) -> Result<FeeTable, FeeTableError> {
        let schedules = match self {
            Self::Futures { schedules } => schedules
                .iter()
                .map(|schedule| FeeSchedule {
                    effective_from: TradeDate(schedule.effective_from),
                    fee: FeeRate::Futures {
                        per_contract_side: Money(schedule.per_contract_side),
                    },
                })
                .collect(),
            Self::Crypto { schedules } => schedules
                .iter()
                .map(|schedule| FeeSchedule {
                    effective_from: TradeDate(schedule.effective_from),
                    fee: FeeRate::Crypto {
                        maker: Rate(schedule.maker_rate),
                        taker: Rate(schedule.taker_rate),
                    },
                })
                .collect(),
        };
        FeeTable::new(schedules)
    }
}

impl FundingConfig {
    /// The funding rate, paid at its time (F-FND-01).
    const fn rate(&self) -> FundingRate {
        FundingRate {
            ts: Ts(self.ts),
            rate: Rate(self.rate),
        }
    }
}

impl RollConfig {
    /// The roll, from the contract rolled from to the new front at its session's open (F-ROL-01).
    fn roll(&self) -> Roll {
        Roll {
            session_open: Ts(self.session_open),
            rolled_from: Contract(self.rolled_from.clone()),
            contract: Contract(self.contract.clone()),
            gap: Price(self.gap),
            reason: match self.reason {
                RollReasonWord::Volume => RollReason::Volume,
                RollReasonWord::OpenInterest => RollReason::OpenInterest,
                RollReasonWord::Calendar => RollReason::Calendar,
                RollReasonWord::Expiry => RollReason::Expiry,
            },
        }
    }
}
