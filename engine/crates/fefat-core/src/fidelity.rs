//! The fidelity of market data (D-51, `docs/spec/fill-semantics.md` §2 and F-TAG-01): the data an
//! order fills on, for a trade date, spelled as the scenarios and `fefat.market.fidelity` spell
//! it: `tbbo`, `trades`, or bars of a timeframe such as `1s`, `1m`, or an import's `5m` (D-49).

use std::cmp::Ordering;
use std::fmt;

use thiserror::Error;

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
    const fn nominal_seconds(self) -> u64 {
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
    /// Whether every record of this level belongs inside one of `timeframe`'s bars: a tick
    /// always, a bar when `timeframe`'s length is a whole multiple of its own. Bars that do not
    /// nest, such as 1-minute and 90-second bars, can be served side by side.
    pub(crate) const fn nests_in(self, timeframe: Timeframe) -> bool {
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

#[cfg(test)]
mod tests {
    use super::*;

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
    fn a_timeframe_holds_one_unit_or_more() {
        assert_eq!(
            Timeframe::new(0, TimeUnit::Minute),
            Err(EmptyTimeframe {
                unit: TimeUnit::Minute
            })
        );
    }
}
