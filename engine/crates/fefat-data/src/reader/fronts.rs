//! A run's trade dates served from its fronts' caches (step 2.10, F-ROL-01): each contract's
//! cache serves the trade dates of the window from the first it trades on, the window's first for
//! the first front and each roll's for the new front, to the day before the next roll's, so that
//! a run of months or years reads each session's records of that session's front, at their raw
//! prices, as `load` splices them, and crosses its rolls on one reader.

use fefat_core::fidelity::{Fidelity, Timeframe};
use fefat_core::instants::TradeDate;
use fefat_core::instrument::Contract;
use fefat_core::market_data::{
    BarColumns, MarketDataError, MarketDataReader, TbboColumns, TradeColumns,
};

use super::MappedContract;
use crate::error::CacheError;

/// The trade dates of a window, each from its front's cache.
#[derive(Debug)]
pub struct FrontSequence<'cache> {
    contract: Contract,
    trade_dates: Vec<TradeDate>,
    fronts: Vec<(TradeDate, &'cache MappedContract)>,
}

impl<'cache> FrontSequence<'cache> {
    /// The trade dates from `first` to `last` of `fronts`' caches, in the order the run trades
    /// them: the first front from `first`, and each later one from the trade date of its roll,
    /// `rolls` naming each roll's trade date and new front in the order of their opens. A front
    /// whose cache is of another contract than its roll names, rolls that do not follow one
    /// another after `first`, and a window the caches hold no trade date of are refused.
    pub fn new(
        fronts: &[&'cache MappedContract],
        rolls: &[(TradeDate, Contract)],
        first: TradeDate,
        last: TradeDate,
    ) -> Result<Self, CacheError> {
        let context = || format!("the window from {first} to {last}");
        let Some((&opening, later)) = fronts.split_first() else {
            return Err(CacheError::refused(
                "a cache of each front",
                "none",
                context(),
            ));
        };
        if later.len() != rolls.len() {
            let expected = format!(
                "a cache of the first front and one per roll, {}",
                rolls.len() + 1
            );
            return Err(CacheError::refused(
                expected,
                fronts.len().to_string(),
                context(),
            ));
        }
        let mut spans = vec![(first, opening)];
        for (&front, (from, contract)) in later.iter().zip(rolls) {
            let after = spans.last().map_or(first, |(start, _)| *start);
            if *from <= after || *from > last {
                let expected = format!("a roll's trade date after {after}, by {last}");
                return Err(CacheError::refused(expected, from.to_string(), context()));
            }
            if front.contract() != contract {
                let expected = format!("the cache of {} from {from}", contract.0);
                return Err(CacheError::refused(
                    expected,
                    front.contract().0.clone(),
                    context(),
                ));
            }
            spans.push((*from, front));
        }
        let trade_dates = served_dates(&spans, last);
        if trade_dates.is_empty() {
            let expected = format!("trade dates from {first} to {last} in the fronts' caches");
            return Err(CacheError::refused(expected, "none", context()));
        }
        Ok(Self {
            contract: opening.contract().clone(),
            trade_dates,
            fronts: spans,
        })
    }

    /// The cache serving `trade_date`, the last front from its date or before.
    fn front_of(&self, trade_date: TradeDate) -> Result<&'cache MappedContract, MarketDataError> {
        let served = self.trade_dates.binary_search(&trade_date).is_ok();
        let after = self.fronts.partition_point(|(from, _)| *from <= trade_date);
        let front = after
            .checked_sub(1)
            .and_then(|index| self.fronts.get(index));
        match front {
            Some((_, front)) if served => Ok(front),
            Some(_) | None => Err(self.unknown(trade_date)),
        }
    }

    fn unknown(&self, trade_date: TradeDate) -> MarketDataError {
        let (first, last) = match (self.trade_dates.first(), self.trade_dates.last()) {
            (Some(&first), Some(&last)) => (first, last),
            _ => (trade_date, trade_date),
        };
        MarketDataError::UnknownTradeDate {
            contract: self.contract.clone(),
            trade_date,
            first,
            last,
        }
    }
}

/// The trade dates each front's cache serves, from its span's first to the day before the next
/// span's, or to `last` for the last front.
fn served_dates(spans: &[(TradeDate, &MappedContract)], last: TradeDate) -> Vec<TradeDate> {
    let ends = spans.iter().skip(1).map(|(from, _)| Some(*from));
    let ends = ends.chain([None]);
    let mut trade_dates = Vec::new();
    for ((from, front), until) in spans.iter().zip(ends) {
        let served = front.trade_dates().iter().copied().filter(|date| {
            *date >= *from && *date <= last && until.is_none_or(|until| *date < until)
        });
        trade_dates.extend(served);
    }
    trade_dates
}

impl MarketDataReader for FrontSequence<'_> {
    /// The first front, which the run's first roll rolls from (F-ROL-01).
    fn contract(&self) -> &Contract {
        &self.contract
    }

    fn trade_dates(&self) -> &[TradeDate] {
        &self.trade_dates
    }

    fn levels(&self, trade_date: TradeDate) -> Result<&[Fidelity], MarketDataError> {
        self.front_of(trade_date)?.levels(trade_date)
    }

    fn bars(
        &self,
        trade_date: TradeDate,
        timeframe: Timeframe,
    ) -> Result<BarColumns<'_>, MarketDataError> {
        self.front_of(trade_date)?.bars(trade_date, timeframe)
    }

    fn trades(&self, trade_date: TradeDate) -> Result<TradeColumns<'_>, MarketDataError> {
        self.front_of(trade_date)?.trades(trade_date)
    }

    fn tbbo(&self, trade_date: TradeDate) -> Result<TbboColumns<'_>, MarketDataError> {
        self.front_of(trade_date)?.tbbo(trade_date)
    }

    fn offsets(
        &self,
        trade_date: TradeDate,
        timeframe: Timeframe,
        finer: Fidelity,
    ) -> Result<&[u32], MarketDataError> {
        self.front_of(trade_date)?
            .offsets(trade_date, timeframe, finer)
    }
}
