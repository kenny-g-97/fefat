//! The text and number values of a strategy specification as types of their own (`08-code-design.md`
//! §3.1): the layout's version, the root, the time zone, and a local time. Each reads from the
//! JSON value the schema states and writes back the same value, so the schema and the run key do
//! not change; a value the schema refuses cannot be read.

use std::fmt;

use serde::{Deserialize, Serialize};

use super::bounds::OutOfBounds;

/// The version of a specification's layout: 1.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(try_from = "u32", into = "u32")]
pub struct SpecVersion(u32);

impl SpecVersion {
    /// The only layout so far.
    pub const ONE: Self = Self(1);
}

impl TryFrom<u32> for SpecVersion {
    type Error = OutOfBounds;

    fn try_from(version: u32) -> Result<Self, Self::Error> {
        if version == Self::ONE.0 {
            return Ok(Self::ONE);
        }
        Err(OutOfBounds::new("spec_version", "1", version))
    }
}

impl From<SpecVersion> for u32 {
    fn from(version: SpecVersion) -> Self {
        version.0
    }
}

/// The root a strategy trades, as the instrument table names it, such as `ES`: one character or
/// more.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(try_from = "String", into = "String")]
pub struct Root(String);

impl TryFrom<String> for Root {
    type Error = OutOfBounds;

    fn try_from(root: String) -> Result<Self, Self::Error> {
        non_empty("instrument", root).map(Self)
    }
}

impl From<Root> for String {
    fn from(root: Root) -> Self {
        root.0
    }
}

impl fmt::Display for Root {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

/// An IANA time zone, such as `America/Chicago`: one character or more. The SDK checks the name
/// against Polars' time-zone database, which converts the local times before a run (`02` §4).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(try_from = "String", into = "String")]
pub struct TimeZoneName(String);

impl TryFrom<String> for TimeZoneName {
    type Error = OutOfBounds;

    fn try_from(name: String) -> Result<Self, Self::Error> {
        non_empty("execution.time.tz", name).map(Self)
    }
}

impl From<TimeZoneName> for String {
    fn from(name: TimeZoneName) -> Self {
        name.0
    }
}

/// A local time of day, written `HH:MM` from 00:00 to 23:59, the schema's
/// `^([01][0-9]|2[0-3]):[0-5][0-9]$`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(try_from = "String", into = "String")]
pub struct LocalTime {
    hour: u8,
    minute: u8,
}

impl TryFrom<String> for LocalTime {
    type Error = OutOfBounds;

    fn try_from(text: String) -> Result<Self, Self::Error> {
        let read = match *text.as_bytes() {
            [hour_tens, hour_units, b':', minute_tens, minute_units] => {
                two_digits(hour_tens, hour_units).zip(two_digits(minute_tens, minute_units))
            }
            _ => None,
        };
        match read {
            Some((hour, minute)) if hour <= 23 && minute <= 59 => Ok(Self { hour, minute }),
            _ => Err(OutOfBounds::new(
                "a local time",
                "HH:MM from 00:00 to 23:59",
                text,
            )),
        }
    }
}

impl From<LocalTime> for String {
    fn from(time: LocalTime) -> Self {
        time.to_string()
    }
}

impl fmt::Display for LocalTime {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{:02}:{:02}", self.hour, self.minute)
    }
}

fn non_empty(field: &'static str, text: String) -> Result<String, OutOfBounds> {
    if text.is_empty() {
        return Err(OutOfBounds::new(
            field,
            "of one character or more",
            "an empty text",
        ));
    }
    Ok(text)
}

fn two_digits(tens: u8, units: u8) -> Option<u8> {
    let both = tens.is_ascii_digit() && units.is_ascii_digit();
    both.then(|| (tens - b'0') * 10 + (units - b'0'))
}
