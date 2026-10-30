//! Instants and trade dates as the engine counts them (ADR-0019, D-51): an instant is nanoseconds
//! since the Unix epoch, UTC, the clock of `ts_recv` and `ts_close` (F-CLK-01), and a trade date
//! is days since 1970-01-01, as Arrow's `date32` and the store's `trade_date` hold it.

use std::fmt;
use std::str::FromStr;

use serde::{Deserialize, Deserializer, Serialize, Serializer};
use thiserror::Error;

use crate::units::Overflow;

/// Nanoseconds in a second.
pub const NANOSECONDS_PER_SECOND: i64 = 1_000_000_000;
/// Nanoseconds in a minute, the spacing of the marks a trade path keeps (`03` §4.2).
pub const NANOSECONDS_PER_MINUTE: i64 = 60 * NANOSECONDS_PER_SECOND;
/// Seconds in a UTC day.
pub const SECONDS_PER_DAY: i64 = 86_400;

/// An instant: nanoseconds since 1970-01-01T00:00:00Z, shown as the UTC time a scenario writes,
/// without trailing zeros (`2026-03-05T14:30:00.1Z`), as `fefat.reference.units.instant_text`
/// does.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
#[repr(transparent)]
pub struct Ts(pub i64);

impl Ts {
    /// The instant `nanoseconds` later, or earlier when they are negative, or [`Overflow`] when it
    /// leaves 64 bits: an order decided at a close becomes active the latency later (F-ACT-01).
    pub fn checked_add_nanoseconds(self, nanoseconds: i64) -> Result<Self, Overflow> {
        self.0.checked_add(nanoseconds).map(Self).ok_or(Overflow {
            operation: "an instant moved by nanoseconds",
            left: self.0.into(),
            right: nanoseconds.into(),
        })
    }

    /// The first whole minute of the UTC clock at or after this instant, itself when it is one,
    /// or [`Overflow`] when it leaves 64 bits: the minute boundaries every time zone shares.
    pub fn minute_at_or_after(self) -> Result<Self, Overflow> {
        match self.0.rem_euclid(NANOSECONDS_PER_MINUTE) {
            0 => Ok(self),
            into => self.checked_add_nanoseconds(NANOSECONDS_PER_MINUTE - into),
        }
    }
}

/// A trade date, the date of a session (`02` §1.3): days since 1970-01-01, shown as `2026-03-05`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
#[repr(transparent)]
pub struct TradeDate(pub i32);

impl TradeDate {
    /// The date's proleptic Gregorian year, month, and day.
    pub fn year_month_day(self) -> (i64, i64, i64) {
        civil_from_days(i64::from(self.0))
    }
}

/// Text that spells no trade date.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
#[error("Expected a trade date written YYYY-MM-DD, such as 2026-03-05, got {text:?}")]
pub struct UnreadableTradeDate {
    /// The text given.
    pub text: String,
}

impl FromStr for TradeDate {
    type Err = UnreadableTradeDate;

    /// A date as it displays, `2026-03-05`: four, two, and two digits of a day that exists.
    fn from_str(text: &str) -> Result<Self, Self::Err> {
        let unreadable = || UnreadableTradeDate {
            text: text.to_owned(),
        };
        let digits = |part: &str, width: usize| {
            let all_digits = part.len() == width && part.bytes().all(|byte| byte.is_ascii_digit());
            all_digits.then(|| part.parse::<i64>().ok()).flatten()
        };
        let mut parts = text.split('-');
        let (Some(year), Some(month), Some(day), None) =
            (parts.next(), parts.next(), parts.next(), parts.next())
        else {
            return Err(unreadable());
        };
        let (Some(year), Some(month), Some(day)) =
            (digits(year, 4), digits(month, 2), digits(day, 2))
        else {
            return Err(unreadable());
        };
        let days = i32::try_from(days_from_civil(year, month, day)).map_err(|_| unreadable())?;
        let date = Self(days);
        if date.year_month_day() != (year, month, day) {
            return Err(unreadable());
        }
        Ok(date)
    }
}

/// A trade date serializes as its text, `2026-03-05`, as the engine cache's index holds it.
impl Serialize for TradeDate {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.collect_str(self)
    }
}

impl<'de> Deserialize<'de> for TradeDate {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        let text = String::deserialize(deserializer)?;
        text.parse().map_err(serde::de::Error::custom)
    }
}

impl fmt::Display for Ts {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let seconds = self.0.div_euclid(NANOSECONDS_PER_SECOND);
        let (year, month, day) = civil_from_days(seconds.div_euclid(SECONDS_PER_DAY));
        let second_of_day = seconds.rem_euclid(SECONDS_PER_DAY);
        let (hour, minute, second) = (
            second_of_day / 3_600,
            second_of_day / 60 % 60,
            second_of_day % 60,
        );
        write!(
            formatter,
            "{year:04}-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}"
        )?;
        let fraction = format!("{:09}", self.0.rem_euclid(NANOSECONDS_PER_SECOND));
        let fraction = fraction.trim_end_matches('0');
        if !fraction.is_empty() {
            write!(formatter, ".{fraction}")?;
        }
        formatter.write_str("Z")
    }
}

impl fmt::Display for TradeDate {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let (year, month, day) = civil_from_days(i64::from(self.0));
        write!(formatter, "{year:04}-{month:02}-{day:02}")
    }
}

/// The proleptic Gregorian year, month, and day of `days` since 1970-01-01, by Howard Hinnant's
/// `civil_from_days` (<https://howardhinnant.github.io/date_algorithms.html>).
fn civil_from_days(days: i64) -> (i64, i64, i64) {
    let shifted = days + 719_468;
    let era = shifted.div_euclid(146_097);
    let day_of_era = shifted.rem_euclid(146_097);
    let year_of_era =
        (day_of_era - day_of_era / 1_460 + day_of_era / 36_524 - day_of_era / 146_096) / 365;
    let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    let month_index = (5 * day_of_year + 2) / 153;
    let day = day_of_year - (153 * month_index + 2) / 5 + 1;
    let month = if month_index < 10 {
        month_index + 3
    } else {
        month_index - 9
    };
    (year_of_era + era * 400 + i64::from(month <= 2), month, day)
}

/// The days since 1970-01-01 of a proleptic Gregorian date, by Howard Hinnant's
/// `days_from_civil`, the inverse of [`civil_from_days`] on the dates that exist.
fn days_from_civil(year: i64, month: i64, day: i64) -> i64 {
    let year = year - i64::from(month <= 2);
    let era = year.div_euclid(400);
    let year_of_era = year.rem_euclid(400);
    let day_of_year = (153 * ((month + 9) % 12) + 2) / 5 + day - 1;
    let day_of_era = year_of_era * 365 + year_of_era / 4 - year_of_era / 100 + day_of_year;
    era * 146_097 + day_of_era - 719_468
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn instants_read_as_the_scenarios_write_them() {
        assert_eq!(
            Ts(1_772_721_000_100_000_000).to_string(),
            "2026-03-05T14:30:00.1Z"
        );
        assert_eq!(Ts(0).to_string(), "1970-01-01T00:00:00Z");
        assert_eq!(Ts(-1).to_string(), "1969-12-31T23:59:59.999999999Z");
    }

    #[test]
    fn an_instant_moved_beyond_64_bits_is_an_error_not_a_wrap() {
        let latency = 100_000_000;
        assert_eq!(
            Ts(1_000).checked_add_nanoseconds(latency),
            Ok(Ts(100_001_000))
        );
        assert_eq!(Ts(0).checked_add_nanoseconds(-1), Ok(Ts(-1)));
        assert!(Ts(i64::MAX).checked_add_nanoseconds(1).is_err());
    }

    #[test]
    fn the_minute_at_or_after_an_instant_is_itself_on_a_whole_minute_and_the_next_one_inside() {
        let minute = NANOSECONDS_PER_MINUTE;
        // 2026-03-05T14:30:00Z, a whole minute.
        let whole = Ts(1_772_721_000 * NANOSECONDS_PER_SECOND);
        assert_eq!(whole.minute_at_or_after(), Ok(whole));
        assert_eq!(
            Ts(whole.0 + 1).minute_at_or_after(),
            Ok(Ts(whole.0 + minute))
        );
        assert_eq!(
            Ts(whole.0 + minute - 1).minute_at_or_after(),
            Ok(Ts(whole.0 + minute))
        );
        assert_eq!(Ts(-1).minute_at_or_after(), Ok(Ts(0)));
        assert_eq!(Ts(-minute - 1).minute_at_or_after(), Ok(Ts(-minute)));
        assert!(Ts(i64::MAX).minute_at_or_after().is_err());
    }

    #[test]
    fn a_trade_date_serializes_as_its_text_and_refuses_a_day_that_does_not_exist() {
        let written = serde_json::to_string(&TradeDate(20_517)).unwrap();

        assert_eq!(written, "\"2026-03-05\"");
        assert_eq!(
            serde_json::from_str::<TradeDate>(&written).unwrap(),
            TradeDate(20_517)
        );
        assert!(serde_json::from_str::<TradeDate>("\"2026-02-30\"").is_err());
    }

    #[test]
    fn trade_dates_read_as_iso_dates() {
        assert_eq!(TradeDate(0).to_string(), "1970-01-01");
        assert_eq!(TradeDate(20_517).to_string(), "2026-03-05");
        assert_eq!(TradeDate(11_016).to_string(), "2000-02-29");
        assert_eq!(TradeDate(-1).to_string(), "1969-12-31");
    }

    #[test]
    fn every_trade_date_from_1900_to_2100_parses_as_it_displays() {
        for days in -25_567..=47_846 {
            let date = TradeDate(days);
            assert_eq!(date.to_string().parse(), Ok(date), "day {days}");
        }
        assert_eq!(TradeDate(20_517).year_month_day(), (2026, 3, 5));
    }

    #[test]
    fn text_that_spells_no_day_that_exists_is_refused() {
        let refused = [
            "2026-02-29",
            "2026-02-30",
            "2026-13-01",
            "2026-00-10",
            "2026-03-00",
            "2026-3-05",
            "26-03-05",
            "20260305",
            "2026-03-05T00",
            "2026-03-05-01",
            "+026-03-05",
            "",
        ];
        for text in refused {
            assert_eq!(
                text.parse::<TradeDate>(),
                Err(UnreadableTradeDate {
                    text: text.to_owned()
                }),
                "{text:?}"
            );
        }
        assert_eq!("2024-02-29".parse(), Ok(TradeDate(19_782)));
    }

    fn days_in_month(year: i64, month: i64) -> i64 {
        let leap = (year % 4 == 0 && year % 100 != 0) || year % 400 == 0;
        match month {
            2 if leap => 29,
            2 => 28,
            4 | 6 | 9 | 11 => 30,
            _ => 31,
        }
    }

    #[test]
    fn every_day_from_1900_to_2100_follows_the_one_before() {
        let mut expected = (1900, 1, 1);
        for days in -25_567..=47_846 {
            assert_eq!(civil_from_days(days), expected, "day {days}");
            let (year, month, day) = expected;
            expected = if day < days_in_month(year, month) {
                (year, month, day + 1)
            } else if month < 12 {
                (year, month + 1, 1)
            } else {
                (year + 1, 1, 1)
            };
        }
        assert_eq!(expected, (2101, 1, 1));
    }
}
