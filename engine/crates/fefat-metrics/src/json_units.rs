//! The engine's units as the metrics' JSON writes them: on the way in, money in micro-units,
//! prices and rates in 1e-9 units, and lots as integers, as the run's config holds them
//! (`fefat_run::config`); on the way out, money as the decimal text it displays as,
//! `-601.810000`, which Python reads as a `Decimal` without rounding.

use fefat_core::costs::Rate;
use fefat_core::units::{Money, Price, Qty};
use serde::{Deserialize, Deserializer, Serializer};

pub(crate) fn money<'de, D: Deserializer<'de>>(deserializer: D) -> Result<Money, D::Error> {
    i64::deserialize(deserializer).map(Money)
}

pub(crate) fn optional_money<'de, D: Deserializer<'de>>(
    deserializer: D,
) -> Result<Option<Money>, D::Error> {
    Option::<i64>::deserialize(deserializer).map(|units| units.map(Money))
}

pub(crate) fn price<'de, D: Deserializer<'de>>(deserializer: D) -> Result<Price, D::Error> {
    i64::deserialize(deserializer).map(Price)
}

pub(crate) fn lots<'de, D: Deserializer<'de>>(deserializer: D) -> Result<Qty, D::Error> {
    i64::deserialize(deserializer).map(Qty)
}

pub(crate) fn rate<'de, D: Deserializer<'de>>(deserializer: D) -> Result<Rate, D::Error> {
    i64::deserialize(deserializer).map(Rate)
}

pub(crate) fn money_text<S: Serializer>(money: &Money, serializer: S) -> Result<S::Ok, S::Error> {
    serializer.collect_str(money)
}
