//! The fidelity of market data (D-51, `docs/spec/fill-semantics.md` §2 and F-TAG-01): the data an
//! order fills on, for a trade date, spelled as the scenarios and `fefat.market.fidelity` spell
//! it: `tbbo`, `trades`, or bars of a timeframe such as `1s`, `1m`, or an import's `5m` (D-49).

use std::cmp::Ordering;
use std::fmt;
use std::str::FromStr;

use serde::{Deserialize, Deserializer, Serialize, Serializer};
use thiserror::Error;

const TIMEFRAME_TEXT: &str = "a bar timeframe such as 1s, 5m, 1h, or 1d";
const FIDELITY_TEXT: &str = "a fidelity: tbbo, trades, or a bar timeframe such as 1s, 1m, or 5m";

/// The unit of a bar timeframe.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum TimeUnit {
    /// Seconds, written `s`.
    Second,
    /// Minutes, written `m`.
    Minute,
    /// Hours, written `h`.
    Hour,
    /// Days, written `d`: a daily bar spans its trade date's session.
    Day,
}

impl TimeUnit {
    const fn seconds(self) -> u64 {
        match self {
            Self::Second => 1,
            Self::Minute => 60,
            Self::Hour => 3_600,
            Self::Day => 86_400,
        }
    }

    const fn letter(self) -> char {
        match self {
            Self::Second => 's',
            Self::Minute => 'm',
            Self::Hour => 'h',
            Self::Day => 'd',
        }
    }
}

/// A bar's length, one or more of a unit, written `1s`, `5m`, `1h`, or `1d`, and ordered by its
/// length, the shortest first.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct Timeframe {
    count: u32,
    unit: TimeUnit,
}

/// A timeframe of no units.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Error)]
#[error("Expected a bar timeframe of one {unit:?} or more, got none")]
pub struct EmptyTimeframe {
    /// The unit asked for.
    pub unit: TimeUnit,
}

impl Timeframe {
    /// 1-second bars.
    pub const ONE_SECOND: Self = Self {
        count: 1,
        unit: TimeUnit::Second,
    };
    /// 1-minute bars.
    pub const ONE_MINUTE: Self = Self {
        count: 1,
        unit: TimeUnit::Minute,
    };
    /// 5-minute bars, the finest data of some imports (D-49).
    pub const FIVE_MINUTES: Self = Self {
        count: 5,
        unit: TimeUnit::Minute,
    };

    /// `count` of `unit`, one or more.
    pub const fn new(count: u32, unit: TimeUnit) -> Result<Self, EmptyTimeframe> {
        if count == 0 {
            return Err(EmptyTimeframe { unit });
        }
        Ok(Self { count, unit })
    }

    /// The length in seconds, nominal for daily bars, whose sessions differ in length.
    pub const fn nominal_seconds(self) -> u64 {
        self.count as u64 * self.unit.seconds()
    }

    /// Whether each bar of this timeframe holds whole bars of `finer`, as it does when its length
    /// is a whole multiple of `finer`'s, both being bucketed from the session's open (`02` §1.4).
    pub(crate) const fn holds_whole(self, finer: Self) -> bool {
        self.nominal_seconds()
            .is_multiple_of(finer.nominal_seconds())
    }

    /// Whether a stored bar lasting `nanoseconds` fits this timeframe: no longer than it, or any
    /// length for a daily bar, whose session a holiday can stretch past a day, as
    /// `fefat.reference.tape.check_tape` reads it.
    pub(crate) const fn fits(self, nanoseconds: i64) -> bool {
        let longest = self.nominal_seconds() as i128 * 1_000_000_000;
        matches!(self.unit, TimeUnit::Day) || nanoseconds as i128 <= longest
    }
}

impl Ord for Timeframe {
    fn cmp(&self, other: &Self) -> Ordering {
        (self.nominal_seconds(), self.count, self.unit).cmp(&(
            other.nominal_seconds(),
            other.count,
            other.unit,
        ))
    }
}

impl PartialOrd for Timeframe {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl fmt::Display for Timeframe {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}{}", self.count, self.unit.letter())
    }
}

/// Text that spells no fidelity or timeframe.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
#[error("Expected {expected}, got {text:?}")]
pub struct UnreadableFidelity {
    /// What the text should spell.
    pub expected: &'static str,
    /// The text given.
    pub text: String,
}

impl FromStr for Timeframe {
    type Err = UnreadableFidelity;

    /// A timeframe written `<count><s|m|h|d>`, the count without leading zeros, as
    /// `fefat.market.schema.Timeframe.parse` reads it.
    fn from_str(text: &str) -> Result<Self, Self::Err> {
        let unreadable = || UnreadableFidelity {
            expected: TIMEFRAME_TEXT,
            text: text.to_owned(),
        };
        let (count, letter) = text
            .split_at_checked(text.len().saturating_sub(1))
            .ok_or_else(unreadable)?;
        let unit = match letter {
            "s" => TimeUnit::Second,
            "m" => TimeUnit::Minute,
            "h" => TimeUnit::Hour,
            "d" => TimeUnit::Day,
            _ => return Err(unreadable()),
        };
        if count.starts_with('0') || !count.bytes().all(|byte| byte.is_ascii_digit()) {
            return Err(unreadable());
        }
        let count = count.parse().map_err(|_| unreadable())?;
        Self::new(count, unit).map_err(|_| unreadable())
    }
}

/// The data an order fills on, for a trade date, ordered finest first: TBBO records, trade
/// prints, then bars from the shortest timeframe up (`02` §1.6).
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Fidelity {
    /// Trades, each with the best bid and ask just before it.
    Tbbo,
    /// Trade prints alone.
    Trades,
    /// Stored bars of a timeframe.
    Bars(Timeframe),
}

impl Fidelity {
    /// Whether every record of this level belongs inside one of `timeframe`'s intraday bars: a
    /// tick always, a bar when `timeframe`'s length is a whole multiple of its own. Bars that do
    /// not nest, such as 1-minute and 90-second bars, can be served side by side, and a daily bar
    /// spans its session alone, so the prints of the break after its close, which keep its trade
    /// date, and their bars lie outside it (D-43).
    pub const fn nests_in(self, timeframe: Timeframe) -> bool {
        if matches!(timeframe.unit, TimeUnit::Day) {
            return false;
        }
        match self {
            Self::Bars(finer) => timeframe.holds_whole(finer),
            Self::Tbbo | Self::Trades => true,
        }
    }
}

impl fmt::Display for Fidelity {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Tbbo => formatter.write_str("tbbo"),
            Self::Trades => formatter.write_str("trades"),
            Self::Bars(timeframe) => write!(formatter, "{timeframe}"),
        }
    }
}

impl FromStr for Fidelity {
    type Err = UnreadableFidelity;

    /// A fidelity as it displays, and as `fefat.market.fidelity.parse_fidelity` reads it:
    /// `tbbo`, `trades`, or a bar timeframe.
    fn from_str(text: &str) -> Result<Self, Self::Err> {
        match text {
            "tbbo" => Ok(Self::Tbbo),
            "trades" => Ok(Self::Trades),
            _ => text
                .parse()
                .map(Self::Bars)
                .map_err(|_| UnreadableFidelity {
                    expected: FIDELITY_TEXT,
                    text: text.to_owned(),
                }),
        }
    }
}

/// A fidelity serializes as its text, `trades` or `1m`, as the engine cache's index holds it.
impl Serialize for Fidelity {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.collect_str(self)
    }
}

impl<'de> Deserialize<'de> for Fidelity {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let text = String::deserialize(deserializer)?;
        text.parse().map_err(serde::de::Error::custom)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_fidelity_serializes_as_its_text_and_refuses_other_text() {
        let level = Fidelity::Bars(Timeframe::FIVE_MINUTES);

        let written = serde_json::to_string(&[level, Fidelity::Tbbo]).unwrap();
        let refused = serde_json::from_str::<Fidelity>("\"tick\"").unwrap_err();

        assert_eq!(written, "[\"5m\",\"tbbo\"]");
        assert_eq!(
            serde_json::from_str::<Vec<Fidelity>>(&written).unwrap(),
            [level, Fidelity::Tbbo]
        );
        assert!(
            refused
                .to_string()
                .starts_with("Expected a fidelity: tbbo, trades")
        );
    }

    #[test]
    fn fidelities_read_as_the_scenarios_spell_them() {
        let spelled: Vec<String> = [
            Fidelity::Tbbo,
            Fidelity::Trades,
            Fidelity::Bars(Timeframe::ONE_SECOND),
            Fidelity::Bars(Timeframe::FIVE_MINUTES),
            Fidelity::Bars(Timeframe::new(1, TimeUnit::Day).unwrap()),
        ]
        .iter()
        .map(ToString::to_string)
        .collect();
        assert_eq!(spelled, ["tbbo", "trades", "1s", "5m", "1d"]);
    }

    #[test]
    fn fidelities_sort_finest_first() {
        let ninety_seconds = Fidelity::Bars(Timeframe::new(90, TimeUnit::Second).unwrap());
        let mut levels = vec![
            Fidelity::Bars(Timeframe::FIVE_MINUTES),
            Fidelity::Trades,
            ninety_seconds,
            Fidelity::Bars(Timeframe::ONE_MINUTE),
            Fidelity::Tbbo,
            Fidelity::Bars(Timeframe::ONE_SECOND),
        ];
        levels.sort();
        assert_eq!(
            levels,
            [
                Fidelity::Tbbo,
                Fidelity::Trades,
                Fidelity::Bars(Timeframe::ONE_SECOND),
                Fidelity::Bars(Timeframe::ONE_MINUTE),
                ninety_seconds,
                Fidelity::Bars(Timeframe::FIVE_MINUTES),
            ]
        );
    }

    #[test]
    fn sixty_seconds_and_one_minute_are_two_timeframes_of_one_length() {
        let sixty_seconds = Timeframe::new(60, TimeUnit::Second).unwrap();
        assert_ne!(sixty_seconds, Timeframe::ONE_MINUTE);
        assert_eq!(
            sixty_seconds.nominal_seconds(),
            Timeframe::ONE_MINUTE.nominal_seconds()
        );
        assert_ne!(sixty_seconds.cmp(&Timeframe::ONE_MINUTE), Ordering::Equal);
    }

    #[test]
    fn fidelities_parse_as_they_display() {
        let levels = [
            Fidelity::Tbbo,
            Fidelity::Trades,
            Fidelity::Bars(Timeframe::ONE_SECOND),
            Fidelity::Bars(Timeframe::new(90, TimeUnit::Second).unwrap()),
            Fidelity::Bars(Timeframe::ONE_MINUTE),
            Fidelity::Bars(Timeframe::new(60, TimeUnit::Second).unwrap()),
            Fidelity::Bars(Timeframe::new(4, TimeUnit::Hour).unwrap()),
            Fidelity::Bars(Timeframe::new(1, TimeUnit::Day).unwrap()),
        ];
        for level in levels {
            assert_eq!(level.to_string().parse(), Ok(level), "{level}");
        }
    }

    #[test]
    fn text_that_spells_no_fidelity_is_refused() {
        for text in [
            "tick", "", "m", "5", "0m", "05m", "+5m", "5M", "1 m", "1mm", "5é",
        ] {
            let refused = text.parse::<Fidelity>();
            assert_eq!(
                refused,
                Err(UnreadableFidelity {
                    expected: FIDELITY_TEXT,
                    text: text.to_owned()
                }),
                "{text:?}"
            );
        }
        assert_eq!(
            "tick".parse::<Fidelity>().unwrap_err().to_string(),
            "Expected a fidelity: tbbo, trades, or a bar timeframe such as 1s, 1m, or 5m, got \
             \"tick\""
        );
        assert!("99999999999s".parse::<Timeframe>().is_err());
    }

    #[test]
    fn a_timeframe_holds_one_unit_or_more() {
        assert_eq!(
            Timeframe::new(0, TimeUnit::Minute),
            Err(EmptyTimeframe {
                unit: TimeUnit::Minute
            })
        );
    }
}
