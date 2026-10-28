//! What a case of `run.json` pays and rolls across (step 2.9): its fee table, its schedules in
//! the order of their dates, a perpetual's funding rates, and a future's rolls as the roll
//! calendar gives them, each read into the engines' integers.

use fefat_core::costs::{FeeRate, FeeSchedule, FeeTable, FeeTableError, FundingRate, Rate};
use fefat_core::instants::{TradeDate, Ts};
use fefat_core::instrument::Contract;
use fefat_core::rolls::{Roll, RollReason};
use fefat_core::units::{Money, Price};
use serde::Deserialize;

/// A fee table, its schedules in the order of their dates, all of its kind.
#[derive(Debug, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum FeesManifest {
    Futures {
        schedules: Vec<FuturesScheduleManifest>,
    },
    Crypto {
        schedules: Vec<CryptoScheduleManifest>,
    },
}

/// A futures fee from a trade date, in days since 1970-01-01, per contract per side in
/// micro-units.
#[derive(Debug, Clone, Copy, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct FuturesScheduleManifest {
    effective_from: i32,
    per_contract_side: i64,
}

/// A crypto fee from a trade date, its maker and taker rates in 1e-9 units.
#[derive(Debug, Clone, Copy, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct CryptoScheduleManifest {
    effective_from: i32,
    maker_rate: i64,
    taker_rate: i64,
}

/// A funding rate in 1e-9 units, paid at `ts`.
#[derive(Debug, Clone, Copy, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct FundingManifest {
    ts: i64,
    rate: i64,
}

/// A roll as the roll calendar gives it.
#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct RollManifest {
    session_open: i64,
    rolled_from: String,
    contract: String,
    gap: i64,
    reason: RollReasonWord,
}

#[derive(Debug, Clone, Copy, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub(super) enum RollReasonWord {
    Volume,
    OpenInterest,
    Calendar,
    Expiry,
}

impl FeesManifest {
    /// The fee table, its schedules in the order of their dates (F-FEE-01).
    pub(super) fn table(&self) -> Result<FeeTable, FeeTableError> {
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

impl FundingManifest {
    /// The funding rate, paid at its time (F-FND-01).
    pub(super) const fn rate(&self) -> FundingRate {
        FundingRate {
            ts: Ts(self.ts),
            rate: Rate(self.rate),
        }
    }
}

impl RollManifest {
    /// The roll, from the contract rolled from to the new front at its session's open (F-ROL-01).
    pub(super) fn roll(&self) -> Roll {
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
