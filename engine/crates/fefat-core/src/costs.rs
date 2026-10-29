//! What a run pays (`docs/spec/fill-semantics.md` §14, step 2.9), as `fefat.reference.costs` and
//! `fefat.reference.money` work it out: a dated fee table, each schedule in force from its trade
//! date until the next one's, the first also before its date, which the run warns of (F-FEE-01);
//! a fill's fee, per contract per side for a future (F-FEE-01) or in basis points of its value
//! for crypto, maker or taker (F-FEE-02); a perpetual's funding payment (F-FND-01); and the cost
//! lines a run records, each amount with its reason. Every amount is worked out exactly in 128
//! bits and rounded once against the trader, and one that leaves 64 bits is an error (F-FEE-03).

use thiserror::Error;

use crate::fills::Liquidity;
use crate::instants::{TradeDate, Ts};
use crate::instrument::InstrumentParameters;
use crate::orders::OrderId;
use crate::units::{Money, Overflow, PRICE_UNITS, Price, Qty};

/// A rate in 1e-9 units: a funding rate of 0.0001 is 100_000, and a fee of 2 basis points,
/// 0.0002, is 200_000, as the store holds a funding rate (ADR-0019).
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Rate(pub i64);

/// A fee: a future's charge per contract per side (F-FEE-01), or a crypto instrument's rates of a
/// limit that rested and of every other fill (F-FEE-02).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FeeRate {
    /// The charge per contract per side, in micro-units.
    Futures {
        /// What one contract pays each time it is bought or sold.
        per_contract_side: Money,
    },
    /// The rates of the value traded.
    Crypto {
        /// The rate of a limit that rested (F-LMT-04), negative for a rebate.
        maker: Rate,
        /// The rate of every other fill.
        taker: Rate,
    },
}

impl FeeRate {
    /// The fee of `lots` of `instrument` filled at `price` as `liquidity`: the charge per
    /// contract per side times the contracts (F-FEE-01), or the rate of `|price × lots × point
    /// value|` (F-FEE-02), rounded up to the micro-unit, so that a charge rounds up and a rebate
    /// toward nothing (F-FEE-03).
    pub fn fee(
        &self,
        instrument: &InstrumentParameters,
        price: Price,
        lots: Qty,
        liquidity: Liquidity,
    ) -> Result<Money, Overflow> {
        let overflow = Overflow {
            operation: "a fill's fee",
            left: price.0.into(),
            right: lots.0.into(),
        };
        let units = i128::from(PRICE_UNITS);
        let (exact, divisor) = match *self {
            Self::Futures { per_contract_side } => {
                let contracts = i128::from(lots.0).checked_mul(instrument.lot_step().0.into());
                let charge =
                    contracts.and_then(|count| count.checked_mul(per_contract_side.0.into()));
                (charge, units)
            }
            Self::Crypto { maker, taker } => {
                let rate = match liquidity {
                    Liquidity::Maker => maker,
                    Liquidity::Taker => taker,
                };
                let value = i128::from(price.0)
                    .checked_mul(lots.0.into())
                    .and_then(|value| value.checked_mul(instrument.money_per_point().0.into()));
                let charge =
                    value.and_then(|value| value.checked_abs()?.checked_mul(rate.0.into()));
                (charge, units * units)
            }
        };
        let charged = exact
            .and_then(i128::checked_neg)
            .map(|owed| owed.div_euclid(divisor))
            .and_then(i128::checked_neg)
            .ok_or(overflow)?;
        i64::try_from(charged).map(Money).map_err(|_| overflow)
    }
}

/// A fee in force from a trade date.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FeeSchedule {
    /// The trade date it takes effect on.
    pub effective_from: TradeDate,
    /// The fee.
    pub fee: FeeRate,
}

/// A fee table that cannot be: no schedule, schedules out of the order of their dates, or fees
/// of both kinds.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Error)]
pub enum FeeTableError {
    /// A table without a schedule.
    #[error("Expected a fee table of one schedule or more, got none")]
    Empty,
    /// A schedule that does not take effect after the one before it.
    #[error(
        "Expected the schedules of a fee table in the order of their dates, each date once, got \
         {next} after {previous}"
    )]
    OutOfOrder {
        /// The earlier schedule's date.
        previous: TradeDate,
        /// The date after it.
        next: TradeDate,
    },
    /// A futures fee and a crypto fee in one table.
    #[error(
        "Expected the schedules of a fee table to price one kind of fill, got futures and crypto fees"
    )]
    MixedKinds,
}

/// The fee table a run prices its fills with (F-FEE-01): each schedule in force from its date
/// until the next one's, the first also before its date.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FeeTable {
    first: FeeSchedule,
    later: Vec<FeeSchedule>,
}

impl FeeTable {
    /// The table of `schedules`, in the order of their dates, each date once, all of one kind.
    pub fn new(schedules: Vec<FeeSchedule>) -> Result<Self, FeeTableError> {
        let mut schedules = schedules.into_iter();
        let first = schedules.next().ok_or(FeeTableError::Empty)?;
        let later: Vec<FeeSchedule> = schedules.collect();
        let mut previous = first;
        for &schedule in &later {
            if schedule.effective_from <= previous.effective_from {
                return Err(FeeTableError::OutOfOrder {
                    previous: previous.effective_from,
                    next: schedule.effective_from,
                });
            }
            let futures = matches!(schedule.fee, FeeRate::Futures { .. });
            if futures != matches!(first.fee, FeeRate::Futures { .. }) {
                return Err(FeeTableError::MixedKinds);
            }
            previous = schedule;
        }
        Ok(Self { first, later })
    }

    /// One fee in force on every date, which never warns.
    pub const fn always(fee: FeeRate) -> Self {
        Self {
            first: FeeSchedule {
                effective_from: TradeDate(i32::MIN),
                fee,
            },
            later: Vec::new(),
        }
    }

    /// The fee in force on `trade_date`, and whether it is the first schedule's, taken before its
    /// date, which the run warns of (F-FEE-01).
    pub fn in_force(&self, trade_date: TradeDate) -> (FeeRate, ScheduleUse) {
        let latest = self
            .later
            .iter()
            .rev()
            .find(|schedule| schedule.effective_from <= trade_date);
        match latest {
            Some(schedule) => (schedule.fee, ScheduleUse::OnItsDate),
            None if trade_date < self.first.effective_from => {
                (self.first.fee, ScheduleUse::BeforeItsDate)
            }
            None => (self.first.fee, ScheduleUse::OnItsDate),
        }
    }
}

/// How the schedule that priced a fill was used (F-FEE-01): in force on the fill's trade date, or
/// the table's first, taken for a trade date before it, which the run warns of.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ScheduleUse {
    /// The schedule in force on the fill's trade date, or no fee table.
    OnItsDate,
    /// The table's first schedule, taken for a trade date before its own.
    BeforeItsDate,
}

/// A perpetual's funding rate, paid at `ts` (F-FND-01).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FundingRate {
    /// The funding time.
    pub ts: Ts,
    /// The rate.
    pub rate: Rate,
}

/// F-FND-01: what a funding time at `rate` moves the cash of a position of `signed_lots`,
/// positive long, by, at `mark`: the position pays signed lots × mark × point value × rate, so a
/// long pays a positive rate; the change is that amount's negative, rounded toward minus
/// infinity of the cash (F-FEE-03).
pub fn funding_change(
    instrument: &InstrumentParameters,
    signed_lots: Qty,
    mark: Price,
    rate: Rate,
) -> Result<Money, Overflow> {
    let overflow = Overflow {
        operation: "a funding payment",
        left: mark.0.into(),
        right: rate.0.into(),
    };
    let units = i128::from(PRICE_UNITS);
    let change = i128::from(mark.0)
        .checked_mul(signed_lots.0.into())
        .and_then(|value| value.checked_mul(instrument.money_per_point().0.into()))
        .and_then(|value| value.checked_mul(rate.0.into()))
        .and_then(i128::checked_neg)
        .map(|change| change.div_euclid(units * units))
        .ok_or(overflow)?;
    i64::try_from(change).map(Money).map_err(|_| overflow)
}

/// Why a run paid an amount.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CostReason {
    /// The fee of this order's fill (F-FEE-01, F-FEE-02).
    Fee {
        /// The order that filled.
        order: OrderId,
    },
    /// A funding payment at this rate (F-FND-01).
    Funding {
        /// The rate.
        rate: Rate,
    },
}

/// An amount a run pays, below zero when the trader receives it, with its reason: gross profit
/// and loss less the cost lines is the net.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct CostLine {
    /// When it was paid.
    pub ts: Ts,
    /// What the trader paid, in micro-units.
    pub amount: Money,
    /// Why.
    pub reason: CostReason,
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::instrument::LotStep;
    use crate::units::MONEY_UNITS;

    fn es() -> InstrumentParameters {
        InstrumentParameters::new(
            Price(250_000_000),
            Money(50 * MONEY_UNITS),
            LotStep(PRICE_UNITS),
        )
        .unwrap()
    }

    fn btc() -> InstrumentParameters {
        InstrumentParameters::new(Price(100_000_000), Money(1_000), LotStep(1_000_000)).unwrap()
    }

    fn price(units: i64, nanos: i64) -> Price {
        Price(units * PRICE_UNITS + nanos)
    }

    #[test]
    fn a_futures_fill_pays_its_charge_per_contract_per_side() {
        // S-fill-028: 2 contracts at 2.50 a side pay 5.00.
        let fee = FeeRate::Futures {
            per_contract_side: Money(2_500_000),
        };

        let paid = fee.fee(&es(), price(5_000, 250_000_000), Qty(2), Liquidity::Taker);

        assert_eq!(paid, Ok(Money(5_000_000)));
    }

    #[test]
    fn a_crypto_fill_pays_its_rate_of_the_value_rounded_up() {
        // S-fill-029: 0.013 BTC at 65200.1 taker 5 bps = 0.42380065, rounded up to 0.423801.
        let fee = FeeRate::Crypto {
            maker: Rate(200_000),
            taker: Rate(500_000),
        };

        let taker = fee.fee(
            &btc(),
            price(65_200, 100_000_000),
            Qty(13),
            Liquidity::Taker,
        );
        let maker = fee.fee(&btc(), price(65_000, 0), Qty(13), Liquidity::Maker);

        assert_eq!(taker, Ok(Money(423_801)));
        assert_eq!(maker, Ok(Money(169_000)));
    }

    #[test]
    fn a_rebate_rounds_toward_nothing_as_the_trader_receives_it() {
        // A maker rebate of 1 bp on 0.001 BTC at 65000.1: -0.00650001, received as -0.0065.
        let fee = FeeRate::Crypto {
            maker: Rate(-100_000),
            taker: Rate(500_000),
        };

        let paid = fee.fee(&btc(), price(65_000, 100_000_000), Qty(1), Liquidity::Maker);

        assert_eq!(paid, Ok(Money(-6_500)));
    }

    #[test]
    fn funding_is_paid_by_a_long_at_a_positive_rate_rounded_against_the_trader() {
        // S-fill-032: 0.013 BTC long at 65010.3 and 0.0001 pays 0.08451339, a change of -0.084514.
        let change = funding_change(&btc(), Qty(13), price(65_010, 300_000_000), Rate(100_000));
        // S-fill-029: the short receives 0.08466081, rounded down to 0.084660.
        let received = funding_change(&btc(), Qty(-13), price(65_123, 700_000_000), Rate(100_000));

        assert_eq!(change, Ok(Money(-84_514)));
        assert_eq!(received, Ok(Money(84_660)));
    }

    #[test]
    fn the_schedule_in_force_prices_a_date_and_the_first_one_the_dates_before_it() {
        // S-fill-062: 2.00 from 2026-03-06 and 2.50 from 2026-03-07.
        let schedule = |day: i32, cents: i64| FeeSchedule {
            effective_from: TradeDate(day),
            fee: FeeRate::Futures {
                per_contract_side: Money(cents * 10_000),
            },
        };
        let table = FeeTable::new(vec![schedule(20_518, 200), schedule(20_519, 250)]).unwrap();
        let charge = |(fee, used): (FeeRate, ScheduleUse)| match fee {
            FeeRate::Futures { per_contract_side } => (per_contract_side.0, used),
            FeeRate::Crypto { .. } => (0, used),
        };

        assert_eq!(
            charge(table.in_force(TradeDate(20_517))),
            (2_000_000, ScheduleUse::BeforeItsDate)
        );
        assert_eq!(
            charge(table.in_force(TradeDate(20_518))),
            (2_000_000, ScheduleUse::OnItsDate)
        );
        assert_eq!(
            charge(table.in_force(TradeDate(20_521))),
            (2_500_000, ScheduleUse::OnItsDate)
        );
        assert_eq!(
            FeeTable::new(vec![schedule(20_519, 250), schedule(20_518, 200)]),
            Err(FeeTableError::OutOfOrder {
                previous: TradeDate(20_519),
                next: TradeDate(20_518)
            })
        );
        assert_eq!(FeeTable::new(Vec::new()), Err(FeeTableError::Empty));
    }

    #[test]
    fn an_amount_beyond_64_bits_is_refused_and_a_table_prices_one_kind_of_fill() {
        // F-FEE-03: a fee or a funding change that fits no i64 is an error, never wrapped; a fee
        // table prices futures or crypto fills, not both (F-FEE-01).
        let futures = FeeRate::Futures {
            per_contract_side: Money(i64::MAX),
        };
        let crypto = FeeRate::Crypto {
            maker: Rate(0),
            taker: Rate(0),
        };
        let dated = |day: i32, fee: FeeRate| FeeSchedule {
            effective_from: TradeDate(day),
            fee,
        };
        let huge = Qty(1_000_000_000_000);

        assert!(
            futures
                .fee(&es(), price(5_000, 0), Qty(2), Liquidity::Taker)
                .is_err()
        );
        assert!(funding_change(&btc(), huge, price(65_000, 0), Rate(1_000_000_000)).is_err());
        assert_eq!(
            FeeTable::new(vec![dated(20_518, futures), dated(20_519, crypto)]),
            Err(FeeTableError::MixedKinds)
        );
    }
}
