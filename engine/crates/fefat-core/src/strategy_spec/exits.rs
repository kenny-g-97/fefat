//! The exits, time rules, and limits of the execution template (`02-engine-and-data.md` §2.1).

use schemars::JsonSchema;
use serde::{Deserialize, Serialize};

/// The stop placed against the position when an entry fills, a stop-market order (F-STP).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum StopRule {
    /// `ticks` from the entry's fill price.
    Ticks {
        /// The distance from the fill, in ticks.
        #[schemars(range(min = 1))]
        ticks: u32,
    },
    /// `percent` % of the entry's fill price from it.
    Percent {
        /// The distance from the fill, as a percentage of its price: `0.5` is 0.5 %.
        #[schemars(extend("exclusiveMinimum" = 0))]
        percent: f64,
    },
    /// `multiple` times a feature of the entry's signal bar, such as its ATR, from the fill.
    Atr {
        /// The multiple of the feature.
        #[schemars(extend("exclusiveMinimum" = 0))]
        multiple: f64,
        /// The feature's column in the signal frame, such as `atr`.
        #[schemars(length(min = 1))]
        feature: String,
    },
    /// The signal frame's `stop_price` on the entry's signal bar, a raw price.
    Column {},
}

/// A target placed when an entry fills, a limit order (F-LMT) that closes `fraction` of the
/// position still open.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Target {
    /// Where the target is.
    pub price: TargetPrice,
    /// The fraction of the position still open that the target closes: 1 closes the rest.
    #[serde(default = "the_rest")]
    #[schemars(range(max = 1), extend("exclusiveMinimum" = 0))]
    pub fraction: f64,
}

/// A target closes the rest of the position unless a document says otherwise.
const fn the_rest() -> f64 {
    1.0
}

/// Where a target is.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum TargetPrice {
    /// `ticks` from the entry's fill price, in the position's favour.
    Ticks {
        /// The distance from the fill, in ticks.
        #[schemars(range(min = 1))]
        ticks: u32,
    },
    /// `multiple` times a feature of the entry's signal bar, such as its ATR, from the fill.
    Atr {
        /// The multiple of the feature.
        #[schemars(extend("exclusiveMinimum" = 0))]
        multiple: f64,
        /// The feature's column in the signal frame, such as `atr`.
        #[schemars(length(min = 1))]
        feature: String,
    },
    /// `multiple` times the trade's initial risk, the distance from the fill to its first stop.
    RMultiple {
        /// The multiple of the initial risk.
        #[schemars(extend("exclusiveMinimum" = 0))]
        multiple: f64,
    },
    /// The signal frame's `target_price` on the entry's signal bar, a raw price.
    Column {},
}

/// When the stop moves to the entry's fill price, `offset_ticks` beyond it in the position's
/// favour.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Breakeven {
    /// What moves the stop.
    pub trigger: ProfitTrigger,
    /// The ticks beyond the fill price in the position's favour; below zero, short of it.
    #[serde(default)]
    pub offset_ticks: i64,
}

/// A point a trade reaches in its favour.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum ProfitTrigger {
    /// The price `ticks` from the entry's fill in the position's favour.
    Ticks {
        /// The distance from the fill, in ticks.
        #[schemars(range(min = 1))]
        ticks: u32,
    },
    /// A profit of `multiple` times the trade's initial risk.
    RMultiple {
        /// The multiple of the initial risk.
        #[schemars(extend("exclusiveMinimum" = 0))]
        multiple: f64,
    },
    /// The fill of a target, counted from 1.
    AfterTarget {
        /// The target, counted from 1.
        #[schemars(range(min = 1, max = 3))]
        target: u8,
    },
}

/// A stop that follows the price once the trade reaches its activation.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Trailing {
    /// How far behind the price the stop follows.
    pub by: TrailBy,
    /// The ticks the stop moves at a time; without it, every tick.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    #[schemars(with = "u32", range(min = 1))]
    pub step_ticks: Option<u32>,
    /// The point from which the stop follows; without it, from the entry's fill.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    #[schemars(with = "ProfitTrigger")]
    pub activation: Option<ProfitTrigger>,
    /// When the stop moves.
    #[serde(default)]
    pub update: TrailUpdate,
}

/// How far behind the price a trailing stop follows.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, JsonSchema)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum TrailBy {
    /// `ticks` behind the best price since the activation.
    Ticks {
        /// The distance behind the best price, in ticks.
        #[schemars(range(min = 1))]
        ticks: u32,
    },
    /// `multiple` times a feature of the signal bars, such as their ATR, behind the best price.
    Atr {
        /// The multiple of the feature.
        #[schemars(extend("exclusiveMinimum" = 0))]
        multiple: f64,
        /// The feature's column in the signal frame, such as `atr`.
        #[schemars(length(min = 1))]
        feature: String,
    },
    /// At the signal frame's `trail_ref` of each signal bar, a raw price.
    Column {},
}

/// When a trailing stop moves.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum TrailUpdate {
    /// As the price moves inside a bar.
    #[default]
    Intrabar,
    /// At each signal bar's close.
    BarClose,
}

/// Entry windows and time exits, in local time of `tz`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct TimeRules {
    /// The IANA time zone of the local times, such as `America/Chicago`.
    #[schemars(length(min = 1))]
    pub tz: String,
    /// The local times in which entries may be placed; without any, at any time.
    #[serde(default)]
    pub windows: Vec<EntryWindow>,
    /// The local time, `HH:MM`, from which each trade date the position is closed and no entry
    /// is placed: at the first signal close at or after that time on the trade date's own day,
    /// which must fall inside its session, outside its halts, and on the signal bars' grid.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    #[schemars(with = "String", regex(pattern = r"^([01][0-9]|2[0-3]):[0-5][0-9]$"))]
    pub flat_by: Option<String>,
    /// The signal bars a position may stay open.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    #[schemars(with = "u32", range(min = 1))]
    pub max_bars: Option<u32>,
    /// The minutes a position may stay open.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    #[schemars(with = "u32", range(min = 1))]
    pub max_minutes: Option<u32>,
    /// Whether the position is closed before each session's close.
    #[serde(default)]
    pub no_overnight: bool,
    /// Whether the position is closed before the last session of each week closes.
    #[serde(default)]
    pub no_weekend: bool,
}

/// A stretch of local time in which entries may be placed.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct EntryWindow {
    /// The local time, `HH:MM`, at which the window opens.
    #[schemars(regex(pattern = r"^([01][0-9]|2[0-3]):[0-5][0-9]$"))]
    pub start: String,
    /// The local time, `HH:MM`, at which the window closes; before `start`, it runs past
    /// midnight.
    #[schemars(regex(pattern = r"^([01][0-9]|2[0-3]):[0-5][0-9]$"))]
    pub end: String,
    /// The days on which the window holds; without them, every day.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    #[schemars(with = "Vec<Weekday>", length(min = 1))]
    pub weekdays: Option<Vec<Weekday>>,
}

/// A day of the week.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(rename_all = "snake_case")]
pub enum Weekday {
    Monday,
    Tuesday,
    Wednesday,
    Thursday,
    Friday,
    Saturday,
    Sunday,
}

/// Filters on entries: a blackout column, daily limits, a cooldown after a loss, and fresh
/// signals.
#[derive(Debug, Clone, PartialEq, Default, Serialize, Deserialize, JsonSchema)]
#[serde(default, deny_unknown_fields)]
pub struct Limits {
    /// A boolean feature column of the signal frame: no entry on a bar where it is true.
    #[serde(skip_serializing_if = "Option::is_none")]
    #[schemars(with = "String", length(min = 1))]
    pub blackout: Option<String>,
    /// The entries allowed each trade date.
    #[serde(skip_serializing_if = "Option::is_none")]
    #[schemars(with = "u32", range(min = 1))]
    pub max_trades_per_day: Option<u32>,
    /// The losing trades after which no entry is placed that trade date.
    #[serde(skip_serializing_if = "Option::is_none")]
    #[schemars(with = "u32", range(min = 1))]
    pub max_losses_per_day: Option<u32>,
    /// The loss, in the account's currency, after which no entry is placed that trade date.
    #[serde(skip_serializing_if = "Option::is_none")]
    #[schemars(with = "f64", extend("exclusiveMinimum" = 0))]
    pub daily_loss_stop: Option<f64>,
    /// The profit, in the account's currency, after which no entry is placed that trade date.
    #[serde(skip_serializing_if = "Option::is_none")]
    #[schemars(with = "f64", extend("exclusiveMinimum" = 0))]
    pub profit_lock: Option<f64>,
    /// How long no entry is placed after a losing trade.
    #[serde(skip_serializing_if = "Option::is_none")]
    #[schemars(with = "Cooldown")]
    pub cooldown_after_loss: Option<Cooldown>,
    /// Whether an entry needs a signal that was false on the bar before, so that a signal still
    /// true after an exit does not enter again.
    pub fresh_signal: bool,
}

/// How long no entry is placed after a losing trade.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, JsonSchema)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Cooldown {
    /// The next `bars` signal bars.
    Bars {
        /// The signal bars without entries.
        #[schemars(range(min = 1))]
        bars: u32,
    },
    /// The next `minutes` minutes.
    Minutes {
        /// The minutes without entries.
        #[schemars(range(min = 1))]
        minutes: u32,
    },
}
