//! The strategy specification of a signal strategy (`02-engine-and-data.md` §2.1, D-53): the JSON
//! document that the strategy builder emits, the SDK writes (`fefat.strategy`), and the engine
//! reads beside a signal frame aligned to the signal bars' closes.
//!
//! Its JSON schema is generated from these types: `just gen-schema` writes [`schema_text`] into
//! `python/fefat/src/fefat/strategy/strategy_spec.schema.json`, and a test fails when the
//! committed file differs. Serde reads a document and the schema states its bounds, which the
//! SDK's models enforce; the engine checks them when it first reads specs (step 2.6). An optional
//! rule left out is not used, and a document leaves it out rather than writing null.

mod exits;
#[cfg(test)]
mod tests;

pub use exits::{
    Breakeven, Cooldown, EntryWindow, Limits, ProfitTrigger, StopRule, Target, TargetPrice,
    TimeRules, TrailBy, TrailUpdate, Trailing, Weekday,
};

use schemars::JsonSchema;
use schemars::generate::SchemaSettings;
use serde::{Deserialize, Serialize};

/// A signal strategy's specification: the instrument it trades, the timeframe of the signal bars
/// whose closes decide, and its execution template.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct StrategySpec {
    /// The version of the document's layout: 1.
    #[schemars(range(min = 1, max = 1))]
    pub spec_version: u32,
    /// The root the strategy trades, as the instrument table names it, such as `ES`.
    #[schemars(length(min = 1))]
    pub instrument: String,
    /// The timeframe of the signal bars, such as `5m`: a count, then `s`, `m`, `h`, or `d`.
    #[schemars(regex(pattern = r"^[1-9][0-9]*[smhd]$"))]
    pub timeframe: String,
    /// What the strategy does with its signals.
    pub execution: Execution,
}

/// The execution template: how the strategy enters on its signals, protects and closes a
/// position, filters its entries, and sizes them.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Execution {
    /// The order an entry signal places.
    pub entry: EntryOrder,
    /// What an entry signal against the open position does.
    #[serde(default)]
    pub on_opposite_signal: OppositeSignal,
    /// The stop placed against the position when an entry fills.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    #[schemars(with = "StopRule")]
    pub stop: Option<StopRule>,
    /// The targets placed when an entry fills, three at most, each closing a fraction of the
    /// position still open; with the stop, they form one OCO group.
    #[serde(default)]
    #[schemars(length(max = 3))]
    pub targets: Vec<Target>,
    /// When the stop moves to the entry's fill price.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    #[schemars(with = "Breakeven")]
    pub breakeven: Option<Breakeven>,
    /// How the stop follows the price.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    #[schemars(with = "Trailing")]
    pub trailing: Option<Trailing>,
    /// Entry windows and time exits, in local time.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    #[schemars(with = "TimeRules")]
    pub time: Option<TimeRules>,
    /// A blackout column, daily limits, a cooldown, and fresh signals, which filter entries.
    #[serde(default)]
    pub limits: Limits,
    /// How many units an entry trades.
    pub sizing: Sizing,
    /// Whether the signal frame's `long_exit` and `short_exit` close the position.
    #[serde(default = "signal_exits_on")]
    pub signal_exit: bool,
}

/// Signal exits are on unless a document turns them off.
const fn signal_exits_on() -> bool {
    true
}

/// The order an entry signal places: a market order, or a limit or a stop-market order at the
/// signal frame's `entry_price` or a number of ticks from the signal bar's close. With a limit or
/// a stop entry, a bar with both entry signals places a buy and a sell as one OCO group, the long
/// and short pair; with a market entry, such a bar is refused.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum EntryOrder {
    /// A market order (F-MKT).
    Market {},
    /// A limit order at the signal frame's `entry_price` (F-LMT).
    LimitAtColumn {
        /// The signal bars the order works before it is cancelled; without it, until it fills.
        #[serde(default, skip_serializing_if = "Option::is_none")]
        #[schemars(with = "u32", range(min = 1))]
        time_to_live_bars: Option<u32>,
    },
    /// A limit order `ticks` from the signal bar's close, below it for a buy and above it for a
    /// sell (F-LMT).
    LimitOffset {
        /// The distance from the close, in ticks.
        ticks: u32,
        /// The signal bars the order works before it is cancelled; without it, until it fills.
        #[serde(default, skip_serializing_if = "Option::is_none")]
        #[schemars(with = "u32", range(min = 1))]
        time_to_live_bars: Option<u32>,
    },
    /// A stop-market order at the signal frame's `entry_price` (F-STP).
    StopAtColumn {
        /// The signal bars the order works before it is cancelled; without it, until it fills.
        #[serde(default, skip_serializing_if = "Option::is_none")]
        #[schemars(with = "u32", range(min = 1))]
        time_to_live_bars: Option<u32>,
    },
    /// A stop-market order `ticks` from the signal bar's close, above it for a buy and below it
    /// for a sell (F-STP).
    StopOffset {
        /// The distance from the close, in ticks.
        ticks: u32,
        /// The signal bars the order works before it is cancelled; without it, until it fills.
        #[serde(default, skip_serializing_if = "Option::is_none")]
        #[schemars(with = "u32", range(min = 1))]
        time_to_live_bars: Option<u32>,
    },
}

/// What an entry signal against the open position does.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum OppositeSignal {
    /// Nothing: the position stays open.
    #[default]
    Ignore,
    /// The position is closed.
    Close,
    /// The position is closed and an entry is placed the other way.
    Reverse,
}

/// How many units an entry trades: contracts for futures, the base asset for crypto, in whole lot
/// steps of the instrument. The signal frame's `size_mult` multiplies the size where it is given.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Sizing {
    /// The same units on every entry.
    Fixed {
        /// The units of each entry.
        #[schemars(extend("exclusiveMinimum" = 0))]
        units: f64,
    },
    /// The units whose value at the entry is `amount` in the account's currency.
    Notional {
        /// The value of each entry, in the account's currency.
        #[schemars(extend("exclusiveMinimum" = 0))]
        amount: f64,
    },
    /// The units whose loss at the stop is `amount` in the account's currency.
    RiskAmount {
        /// The loss at the stop, in the account's currency.
        #[schemars(extend("exclusiveMinimum" = 0))]
        amount: f64,
    },
    /// The units whose loss at the stop is `percent` % of equity: the run's capital and its
    /// closed profit and loss.
    RiskPercent {
        /// The loss at the stop, as a percentage of equity: `1` is 1 %.
        #[schemars(extend("exclusiveMinimum" = 0))]
        percent: f64,
    },
}

/// The JSON schema of [`StrategySpec`], draft 2020-12, as the SDK and the builder form read it.
#[must_use]
pub fn schema() -> schemars::Schema {
    SchemaSettings::draft2020_12()
        .into_generator()
        .into_root_schema_for::<StrategySpec>()
}

/// [`schema`] as the committed file holds it: JSON indented by two spaces, ending with a newline.
#[must_use]
pub fn schema_text() -> String {
    format!("{:#}\n", schema().as_value())
}
