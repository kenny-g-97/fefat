//! The settings a run fills under, which every run records (`docs/spec/fill-semantics.md` §2): the
//! latency (F-ACT-01), the slippage ticks per order class (F-SLP-01), and when limits fill
//! (F-LMT-01, F-LMT-02), as `fefat.reference.settings.RunSettings` holds them.

use fefat_core::fidelity::Fidelity;

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
