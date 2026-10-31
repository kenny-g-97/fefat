//! Trade paths (`03-prop-simulator.md` §4.2, `02` §4, step 2.13): for each flat-to-flat trade, a
//! compact path of the price its position is marked at (F-MRK-01), in its entry contract's prices,
//! each roll's gap taken off (F-ROL-03), so that it runs on unbroken across a roll and takes the
//! old contract's price until the roll's legs fill. It keeps each fill of the trade at its own
//! price: its entry, an addition, an exit, a roll's leg, and the fill that leaves it flat; each new
//! favourable extreme since the last fill or minute, and each new adverse extreme since the last
//! favourable one, fill, or minute; the mark at every whole minute of the UTC clock from its
//! entry's on, the last at or before it, closed hours included, until the fill that leaves it
//! flat; and, after a favourable extreme a bar reached while the bar's adverse extreme lies beyond
//! its close, that adverse extreme, which the bar may have reached after it
//! (`docs/spec/fill-semantics.md` §15). Each fill and each minute restarts the tracking, so that
//! the extremes after any of them, and their order, survive: what a prop rule asks of equity from
//! a reference on a minute or a fill, the compact path answers as the full one does.

use std::fmt;

use fefat_core::instants::{NANOSECONDS_PER_MINUTE, Ts};
use fefat_core::orders::OrderId;
use fefat_core::units::{Overflow, Price};

/// What a run records of its trades' paths.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Recording {
    /// Each trade's compact path, as every saved run keeps it.
    Paths,
    /// None, as a sweep's trials may run (`02` §7): their fills and trades are the same.
    TradesOnly,
    /// Every mark and every fill while a trade is open: the full-resolution path that tests hold
    /// the compact one to.
    #[cfg(test)]
    EveryMark,
}

/// What a point of a trade's path is.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PathPointKind {
    /// A fill of the trade, at its own price, by its order.
    Fill(OrderId),
    /// The mark at a whole minute.
    Minute,
    /// A new favourable extreme since the last fill or minute.
    Favourable,
    /// A new adverse extreme since the last favourable extreme, fill, or minute.
    Adverse,
    /// The adverse extreme of the bar whose favourable extreme the point before it reached, which
    /// the bar may have reached after it (§15).
    PossibleAdverse,
    /// Any other mark, in the full-resolution path of tests.
    #[cfg(test)]
    Mark,
}

impl PathPointKind {
    /// The order of a fill's point, none for any other.
    pub const fn order(self) -> Option<OrderId> {
        match self {
            Self::Fill(order) => Some(order),
            _ => None,
        }
    }

    /// The kind as the `trade_paths` artifact writes it: `fill`, `minute`, `favourable`,
    /// `adverse`, or `possible_adverse`.
    pub const fn name(self) -> &'static str {
        match self {
            Self::Fill(_) => "fill",
            Self::Minute => "minute",
            Self::Favourable => "favourable",
            Self::Adverse => "adverse",
            Self::PossibleAdverse => "possible_adverse",
            #[cfg(test)]
            Self::Mark => "mark",
        }
    }
}

impl fmt::Display for PathPointKind {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.name())
    }
}

/// A point of a trade's path.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PathPoint {
    /// A fill's or a mark's instant, on a bar its close (F-BAR-06), or the minute's.
    pub ts: Ts,
    /// The price, in 1e-9 units of the trade's entry contract.
    pub price: Price,
    /// What it is.
    pub kind: PathPointKind,
}

/// A closed trade's path.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TradePath {
    /// Its points in the order they happened, from its entry's fill to the fill that left it flat.
    pub points: Vec<PathPoint>,
}

/// A price as a trade's path takes it: its distance from the trade's entry price, above zero in
/// the trade's favour, and the price itself in the entry contract's prices.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) struct PathPrice {
    pub(super) distance: Price,
    pub(super) price: Price,
}

/// How much of an open trade's path is kept.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Detail {
    Compact,
    #[cfg(test)]
    Every,
}

/// The path of a trade still open: how much it keeps, the best distance since the last fill or
/// minute, the worst since then or since the last favourable extreme, the last mark, the next
/// whole minute to record, and the points so far.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct PathRecorder {
    detail: Detail,
    favourable: Price,
    adverse: Price,
    last_mark: PathPrice,
    next_minute: Ts,
    points: Vec<PathPoint>,
}

impl PathRecorder {
    /// The path `recording` keeps of a trade that its entry, `order`, opens at `ts` at `entry`;
    /// none when it keeps no path.
    pub(super) fn opened(
        recording: Recording,
        ts: Ts,
        entry: PathPrice,
        order: OrderId,
    ) -> Result<Option<Self>, Overflow> {
        let detail = match recording {
            Recording::Paths => Detail::Compact,
            Recording::TradesOnly => return Ok(None),
            #[cfg(test)]
            Recording::EveryMark => Detail::Every,
        };
        let mut path = Self {
            detail,
            favourable: entry.distance,
            adverse: entry.distance,
            last_mark: entry,
            next_minute: ts.minute_at_or_after()?,
            points: Vec::new(),
        };
        path.push(ts, entry.price, PathPointKind::Fill(order));
        Ok(Some(path))
    }

    /// The position marked at `ts` at `mark`; at a bar's favourable extreme, `adverse_after` is
    /// the bar's adverse extreme beyond its close (§15).
    pub(super) fn marked(
        &mut self,
        ts: Ts,
        mark: PathPrice,
        adverse_after: Option<PathPrice>,
    ) -> Result<(), Overflow> {
        self.minutes_before(ts)?;
        self.last_mark = mark;
        #[cfg(test)]
        if self.keeps_every_mark() {
            self.push(ts, mark.price, PathPointKind::Mark);
            return Ok(());
        }
        if mark.distance > self.favourable {
            self.restart(mark.distance);
            self.push(ts, mark.price, PathPointKind::Favourable);
            if let Some(adverse) = adverse_after {
                self.push(ts, adverse.price, PathPointKind::PossibleAdverse);
            }
        } else if mark.distance < self.adverse {
            self.adverse = mark.distance;
            self.push(ts, mark.price, PathPointKind::Adverse);
        }
        Ok(())
    }

    /// The fill of `order` at `ts` at `fill`, where the tracking restarts.
    pub(super) fn filled(
        &mut self,
        ts: Ts,
        fill: PathPrice,
        order: OrderId,
    ) -> Result<(), Overflow> {
        self.minutes_before(ts)?;
        self.push(ts, fill.price, PathPointKind::Fill(order));
        self.restart(fill.distance);
        Ok(())
    }

    /// Whether a skip may pass over records from the one at `first` to the one at `last`, at
    /// distances from `worst` to `best`, which a full replay would mark without a point: no whole
    /// minute from the first to just before the last, whose mark is a record's in the block, and,
    /// from the minute the first record would restart the tracking at or from the tracking as it
    /// stands, neither a new favourable extreme nor a new adverse one.
    pub(super) fn can_skip(
        &self,
        first: Ts,
        last: Ts,
        best: Price,
        worst: Price,
    ) -> Result<bool, Overflow> {
        if self.keeps_every_mark() || first.minute_at_or_after()? < last {
            return Ok(false);
        }
        let (favourable, adverse) = match self.next_minute < first {
            true => (self.last_mark.distance, self.last_mark.distance),
            false => (self.favourable, self.adverse),
        };
        Ok(best <= favourable && worst >= adverse)
    }

    /// The path, its trade closed.
    pub(super) fn into_path(self) -> TradePath {
        TradePath {
            points: self.points,
        }
    }

    /// The mark at each whole minute before `ts` not yet recorded, the last at or before it,
    /// each restarting the tracking.
    fn minutes_before(&mut self, ts: Ts) -> Result<(), Overflow> {
        if self.keeps_every_mark() {
            return Ok(());
        }
        while self.next_minute < ts {
            self.push(
                self.next_minute,
                self.last_mark.price,
                PathPointKind::Minute,
            );
            self.restart(self.last_mark.distance);
            let next = self
                .next_minute
                .checked_add_nanoseconds(NANOSECONDS_PER_MINUTE)?;
            self.next_minute = next;
        }
        Ok(())
    }

    /// The tracking from a point at `distance`: the best and the worst since are its own.
    const fn restart(&mut self, distance: Price) {
        self.favourable = distance;
        self.adverse = distance;
    }

    fn push(&mut self, ts: Ts, price: Price, kind: PathPointKind) {
        self.points.push(PathPoint { ts, price, kind });
    }

    const fn keeps_every_mark(&self) -> bool {
        match self.detail {
            Detail::Compact => false,
            #[cfg(test)]
            Detail::Every => true,
        }
    }
}
