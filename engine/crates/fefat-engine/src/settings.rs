//! The settings a run fills under, which every run records (`docs/spec/fill-semantics.md` §2): the
//! latency (F-ACT-01), the slippage ticks per order class (F-SLP-01), and when limits fill
//! (F-LMT-01, F-LMT-02), as `fefat.reference.settings.RunSettings` holds them; what a roll does with
//! an open position (F-ROL-02, F-ROL-04); and what the run pays, its fee table and a perpetual's
//! funding rates (§14).

use fefat_core::costs::{FeeTable, FundingRate, ScheduleUse};
use fefat_core::fidelity::Fidelity;
use fefat_core::fills::Liquidity;
use fefat_core::instants::TradeDate;
use fefat_core::instrument::InstrumentParameters;
use fefat_core::units::{Money, Overflow, Price, Qty};

/// When a limit fills.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LimitFill {
    /// Once the market trades through its price (F-LMT-01), the default.
    Through,
    /// Once the market touches its price (F-LMT-02).
    Touch,
}

/// Whole ticks by which market and stop-market fills are worse than their reference (F-SLP-01).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SlippageTicks {
    /// The ticks of a market order.
    pub market: u32,
    /// The ticks of a stop-market order.
    pub stop: u32,
}

/// The run settings of F-ACT-01, F-SLP-01, F-LMT-01, and F-LMT-02.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RunSettings {
    /// How long after the decision that placed it an order becomes active, in milliseconds.
    pub latency_milliseconds: u32,
    /// The slippage ticks of each order class.
    pub slippage: SlippageTicks,
    /// When limits fill.
    pub limit_fill: LimitFill,
}

impl RunSettings {
    /// The specification's defaults on `fidelity` (D-51): active 100 ms after the decision, no
    /// slippage ticks on TBBO, which fills at the quote, one on every other fidelity, and limits
    /// that fill when the market trades through them.
    pub const fn defaults_for(fidelity: Fidelity) -> Self {
        let ticks = match fidelity {
            Fidelity::Tbbo => 0,
            Fidelity::Trades | Fidelity::Bars(_) => 1,
        };
        Self {
            latency_milliseconds: 100,
            slippage: SlippageTicks {
                market: ticks,
                stop: ticks,
            },
            limit_fill: LimitFill::Through,
        }
    }

    /// The latency in nanoseconds.
    pub fn latency_nanoseconds(&self) -> i64 {
        i64::from(self.latency_milliseconds) * 1_000_000
    }
}

/// What a roll does with an open position.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum RollHandling {
    /// Transfers it to the new front by two legs (F-ROL-02), the default.
    #[default]
    Transfer,
    /// Closes it by the close leg alone (F-ROL-04).
    Flatten,
}

/// What a run pays (§14): its fee table, none when the run names none, and a perpetual's funding
/// rates, in the order of their times.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct RunCosts {
    /// The fee table that prices each fill (F-FEE-01, F-FEE-02).
    pub fees: Option<FeeTable>,
    /// The funding rates of a perpetual (F-FND-01).
    pub funding: Vec<FundingRate>,
}

impl RunCosts {
    /// The fee of `lots` of `instrument` filled at `price` as `liquidity` on `trade_date`, and
    /// whether the fee table's first schedule priced it before its date (F-FEE-01); nothing
    /// without a fee table.
    pub fn fee(
        &self,
        instrument: &InstrumentParameters,
        price: Price,
        lots: Qty,
        liquidity: Liquidity,
        trade_date: TradeDate,
    ) -> Result<(Money, ScheduleUse), Overflow> {
        let Some(table) = &self.fees else {
            return Ok((Money(0), ScheduleUse::OnItsDate));
        };
        let (fee, used) = table.in_force(trade_date);
        Ok((fee.fee(instrument, price, lots, liquidity)?, used))
    }
}
