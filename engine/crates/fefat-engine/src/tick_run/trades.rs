//! The trades of a run (`docs/spec/fill-semantics.md` §20, step 2.10): each from the fill that
//! opens a position from flat to the fill that leaves it flat, through the legs of a roll that
//! transfers it (F-ROL-02); a fill that reverses the position crosses flat (S-fill-042), closing
//! the trade with the lots it held and opening the next with the rest. A trade records its
//! entry, its exits, the one that left it flat and why, the rolls it crossed, its money (what its
//! fills' values moved the cash by, their fees, and the funding paid or received while it was
//! open, F-FND-01), its exit plan's initial risk (F-RND-02), and its excursions, the farthest
//! the prices the run marks the position at while it is open (F-MRK-01), and the prices of the
//! fills that close its lots, went against it and for it from its entry's price, in whole ticks,
//! a roll moving that price by its gap as it moves the exit plan's (F-ROL-03); and, from step
//! 2.13, the deepest fall of those prices from the best of them before (`02` §7), on bars in the
//! order of the engine's bar path (F-BAR-02 to F-BAR-04), as the excursions are; the coarsest
//! level its marks and fills came from; and its path (`paths`), which a run may leave out. The
//! legs of a roll that transfers the trade and a fill on the entry's side move no excursion: they
//! are not prices the market took the position to, while a roll that flattens it closes it with
//! its close leg, an exit like any other. A position held when the tape starts, which no fill
//! opened, is no trade, nor is one a roll's leg reopens or one still open when the run ends; a
//! fill on the entry's side while a trade is open adds its money to the trade but not its lots
//! to the entry, which the execution template never sends (`BACKLOG.md`).

use fefat_core::fidelity::Fidelity;
use fefat_core::fills::Fill;
use fefat_core::instants::Ts;
use fefat_core::instrument::{Contract, InstrumentParameters};
use fefat_core::market_data::BarRow;
use fefat_core::orders::{OrderId, OrderRole, Side};
use fefat_core::units::{Money, Overflow, Price, Qty};

use super::paths::{PathPrice, PathRecorder, Recording, TradePath};
use crate::rules::Extreme;

/// A trade a run closed.
#[derive(Debug, Clone, PartialEq)]
pub struct Trade {
    /// The entry's side: a buy opens a long.
    pub side: Side,
    /// The entry's lots.
    pub lots: Qty,
    /// The entry order.
    pub entry_order: OrderId,
    /// When the decision that placed the entry was made, the entry row's close.
    pub entry_decision: Ts,
    /// When the entry filled.
    pub entry_ts: Ts,
    /// At what price.
    pub entry_price: Price,
    /// On which contract.
    pub entry_contract: Contract,
    /// How many fills closed its lots, a roll's legs left out.
    pub exits: u32,
    /// The prices of the fills that closed its lots, averaged by their lots, in 1e-9 units of
    /// its entry contract's prices, each roll's gap taken off a price after it, so that the exit
    /// less the entry is the trade's move.
    pub exit_price: Option<f64>,
    /// When the fill that left it flat filled.
    pub exit_ts: Ts,
    /// That fill's role, the trade's exit reason (F-TAG-01).
    pub exit_reason: OrderRole,
    /// That fill's contract.
    pub exit_contract: Contract,
    /// The rolls it was transferred across.
    pub rolls: u32,
    /// What its fills' values moved the cash by, before fees and funding.
    pub gross_pnl: Money,
    /// Its fills' fees.
    pub fees: Money,
    /// The funding received while it was open, below zero when paid (F-FND-01).
    pub funding: Money,
    /// Its profit and loss, its gross less its fees plus its funding (§20).
    pub pnl: Money,
    /// The ticks from its entry's price to its stop's first level, none without a stop (F-RND-02).
    pub initial_risk_ticks: Option<i64>,
    /// The farthest its prices went against it, in whole ticks.
    pub mae_ticks: i64,
    /// The farthest they went for it, in whole ticks.
    pub mfe_ticks: i64,
    /// That adverse excursion over its entry's lots, in micro-units.
    pub mae: Money,
    /// That favourable excursion over its entry's lots, in micro-units.
    pub mfe: Money,
    /// The deepest fall of its prices from the best of them before, its entry's price first, in
    /// whole ticks, on bars in the order of the engine's bar path; the path's possible adverse
    /// points mark bars whose other order falls further (§15).
    pub max_drawdown_ticks: i64,
    /// That fall over its entry's lots, in micro-units.
    pub max_drawdown: Money,
    /// The coarsest level its marks and fills came from (`03-prop-simulator.md` §4.4).
    pub path_fidelity: Fidelity,
}

/// A price the run marks the position at (F-MRK-01): when, at what price of the run's front, on
/// which level, and, at a bar's extreme pseudo-tick (F-BAR-01), which extreme it is and the bar.
#[derive(Debug, Clone, Copy)]
pub(super) struct Mark {
    pub(super) ts: Ts,
    pub(super) price: Price,
    pub(super) fidelity: Fidelity,
    pub(super) extreme: Option<(Extreme, BarRow)>,
}

/// The values of the trade open that `can_skip` reads and a mark can move (step 2.15): its best
/// price as a distance from its entry, and its path's best and worst since its last point and its
/// next whole minute (`PathRecorder::tracking`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) struct Tracking {
    favourable: Price,
    path: Option<(Price, Price, Ts)>,
}

/// A trade still open.
#[derive(Debug, Clone, PartialEq)]
struct OpenTrade {
    entry: Fill,
    entry_decision: Ts,
    entry_contract: Contract,
    initial_risk_ticks: Option<i64>,
    reference: Price,
    exits: u32,
    exit_lots: i128,
    exit_value: i128,
    rolls: u32,
    gross_pnl: Money,
    fees: Money,
    funding: Money,
    adverse: Price,
    favourable: Price,
    drawdown: Price,
    coarsest: Fidelity,
    path: Option<PathRecorder>,
}

/// The run's trades: what it records of their paths, the lots its fills hold, the trade open,
/// and those closed with their paths.
#[derive(Debug, Clone, PartialEq)]
pub(super) struct TradeBook {
    recording: Recording,
    held: i64,
    open: Option<OpenTrade>,
    closed: Vec<Trade>,
    paths: Vec<TradePath>,
}

/// A fill as the trades take it: the fill, when its order was placed, the cash its value moved,
/// its contract, whether it left the position flat, its exit plan's initial risk in ticks
/// (F-RND-02), and its price as the run marks prices, its own, or a roll's close leg's plus the
/// gap it was priced less (F-ROL-02, F-ROL-03).
#[derive(Debug, Clone, Copy)]
pub(super) struct TradedFill<'fill> {
    pub(super) fill: &'fill Fill,
    pub(super) placed_at: Ts,
    pub(super) cash: Money,
    pub(super) contract: &'fill Contract,
    pub(super) flat_after: bool,
    pub(super) initial_risk_ticks: Option<i64>,
    pub(super) marked: Price,
}

impl TradedFill<'_> {
    /// The fill's lots, positive for a buy.
    const fn signed_lots(&self) -> i64 {
        match self.fill.side {
            Side::Buy => self.fill.lots.0,
            Side::Sell => -self.fill.lots.0,
        }
    }
}

impl TradeBook {
    /// The trades of a run that starts holding `held` lots, positive long, each with its path.
    pub(super) const fn holding(held: i64) -> Self {
        Self {
            recording: Recording::Paths,
            held,
            open: None,
            closed: Vec::new(),
            paths: Vec::new(),
        }
    }

    /// The trades, recording of their paths what `recording` says.
    pub(super) fn recording(self, recording: Recording) -> Self {
        Self { recording, ..self }
    }

    /// The trades closed, in the order they closed, and their paths in the same order, none when
    /// the run records none.
    pub(super) fn into_closed(self) -> (Vec<Trade>, Vec<TradePath>) {
        (self.closed, self.paths)
    }

    /// `traded`, the next fill: it opens a trade from flat, unless a roll's leg reopens a position
    /// no trade holds; closes some of the open trade's lots; transfers it; leaves it flat and
    /// closes it; or reverses it, closing it and opening the next.
    pub(super) fn filled(
        &mut self,
        traded: &TradedFill<'_>,
        instrument: &InstrumentParameters,
    ) -> Result<(), Overflow> {
        let before = self.held;
        self.held += traded.signed_lots();
        if before != 0 && self.held != 0 && (before > 0) != (self.held > 0) {
            return self.reversed(traded, before.abs(), instrument);
        }
        let Some(open) = &mut self.open else {
            if before == 0 && !matches!(traded.fill.role, OrderRole::Roll(_)) {
                self.open = Some(OpenTrade::of(traded, self.recording)?);
            }
            return Ok(());
        };
        open.count(traded)?;
        if traded.flat_after {
            self.close(traded, instrument)?;
        }
        Ok(())
    }

    /// The open trade, closed by `traded`, the fill that left it flat.
    fn close(
        &mut self,
        traded: &TradedFill<'_>,
        instrument: &InstrumentParameters,
    ) -> Result<(), Overflow> {
        let Some(open) = self.open.take() else {
            return Ok(());
        };
        let (trade, path) = open.closed_by(traded, instrument)?;
        self.closed.push(trade);
        self.paths.extend(path);
        Ok(())
    }

    /// `traded` reverses the position, crossing flat (S-fill-042): its `closing` lots close the
    /// open trade and the rest open the next, the fill's value and fee shared by their lots, the
    /// closing trade's share rounded against the trader (F-FEE-03).
    fn reversed(
        &mut self,
        traded: &TradedFill<'_>,
        closing: i64,
        instrument: &InstrumentParameters,
    ) -> Result<(), Overflow> {
        let fill = traded.fill;
        let lots = fill.lots.0;
        let cash = share(traded.cash, closing, lots)?;
        let fee = Money(0).checked_sub(share(Money(0).checked_sub(fill.fee)?, closing, lots)?)?;
        let closed_part = Fill {
            lots: Qty(closing),
            fee,
            ..*fill
        };
        let opened_part = Fill {
            lots: Qty(lots - closing),
            fee: fill.fee.checked_sub(fee)?,
            ..*fill
        };
        let closes = TradedFill {
            fill: &closed_part,
            cash,
            flat_after: true,
            ..*traded
        };
        let opens = TradedFill {
            fill: &opened_part,
            cash: traded.cash.checked_sub(cash)?,
            ..*traded
        };
        if let Some(open) = &mut self.open {
            open.count(&closes)?;
        }
        self.close(&closes, instrument)?;
        self.open = Some(OpenTrade::of(&opens, self.recording)?);
        Ok(())
    }

    /// The position marked as `mark` says (F-MRK-01), which the open trade's excursions and its
    /// path follow.
    pub(super) fn marked(&mut self, mark: &Mark) -> Result<(), Overflow> {
        match &mut self.open {
            Some(open) => open.marked(mark),
            None => Ok(()),
        }
    }

    /// The prices from `low` to `high` that a block of records passed over reached while the
    /// trade stayed open, as a full replay would mark them; `can_skip` holds the block to no new
    /// best price, so that the order of its prices moves no fall from the best.
    pub(super) fn reached(&mut self, low: Price, high: Price) -> Result<(), Overflow> {
        let Some(open) = &mut self.open else {
            return Ok(());
        };
        for price in [low, high] {
            let distance = open.distance(price)?;
            open.excursion(distance)?;
        }
        Ok(())
    }

    /// Whether a skip may pass over the records from the one at `first` to the one at `last`,
    /// inside `bar`, whose range bounds their prices (`02` §4): with a trade open, the bar reaches
    /// no price better than the trade's best, so that its prices' order moves no fall from it,
    /// and, where the trade's path is recorded, they would add no point to it.
    pub(super) fn can_skip(&self, bar: &BarRow, first: Ts, last: Ts) -> Result<bool, Overflow> {
        let Some(open) = &self.open else {
            return Ok(true);
        };
        let (low, high) = (open.distance(bar.low)?, open.distance(bar.high)?);
        let (best, worst) = (low.max(high), low.min(high));
        let below_the_best = best <= open.favourable;
        match &open.path {
            Some(path) => Ok(below_the_best && path.can_skip(first, last, best, worst)?),
            None => Ok(below_the_best),
        }
    }

    /// What `can_skip` reads of the trade open that a mark can move (step 2.15): its best and,
    /// where its path is recorded, the path's tracking; none while the run is flat.
    pub(super) fn tracking(&self) -> Option<Tracking> {
        let open = self.open.as_ref()?;
        Some(Tracking {
            favourable: open.favourable,
            path: open.path.as_ref().map(PathRecorder::tracking),
        })
    }

    /// A funding payment while the trade is open, the change to the cash (F-FND-01).
    pub(super) fn funded(&mut self, change: Money) -> Result<(), Overflow> {
        if let Some(open) = &mut self.open {
            open.funding = open.funding.checked_add(change)?;
        }
        Ok(())
    }

    /// A roll moved every price the run holds by `gap` (F-ROL-03).
    pub(super) fn shifted(&mut self, gap: Price) -> Result<(), Overflow> {
        if let Some(open) = &mut self.open {
            open.reference = open.reference.checked_add(gap)?;
        }
        Ok(())
    }

    /// Whether a trade is open.
    pub(super) const fn is_open(&self) -> bool {
        self.open.is_some()
    }
}

impl OpenTrade {
    /// The trade `traded`, its entry, opens, with its exit plan's initial risk, and its path as
    /// `recording` keeps it, from the entry's fill.
    fn of(traded: &TradedFill<'_>, recording: Recording) -> Result<Self, Overflow> {
        let entry = traded.fill;
        let at_entry = PathPrice {
            distance: Price(0),
            price: entry.price,
        };
        let path = PathRecorder::opened(recording, entry.ts, at_entry, entry.order)?;
        Ok(Self {
            entry: *entry,
            entry_decision: traded.placed_at,
            entry_contract: traded.contract.clone(),
            initial_risk_ticks: traded.initial_risk_ticks,
            reference: entry.price,
            exits: 0,
            exit_lots: 0,
            exit_value: 0,
            rolls: 0,
            gross_pnl: traded.cash,
            fees: entry.fee,
            funding: Money(0),
            adverse: Price(0),
            favourable: Price(0),
            drawdown: Price(0),
            coarsest: entry.fidelity,
            path,
        })
    }

    /// A fill after the entry: its money counts, it is a point of the path, a roll's close leg
    /// counts a roll, and any other fill against the entry's side counts an exit, its price an
    /// excursion.
    fn count(&mut self, traded: &TradedFill<'_>) -> Result<(), Overflow> {
        let fill = traded.fill;
        self.gross_pnl = self.gross_pnl.checked_add(traded.cash)?;
        self.fees = self.fees.checked_add(fill.fee)?;
        self.coarsest = self.coarsest.max(fill.fidelity);
        let at = self.path_price(traded.marked)?;
        if let Some(path) = &mut self.path {
            path.filled(fill.ts, at, fill.order)?;
        }
        let against = fill.side != self.entry.side;
        let transfer_leg = matches!(fill.role, OrderRole::Roll(_)) && !traded.flat_after;
        if transfer_leg {
            self.rolls += u32::from(against);
            return Ok(());
        }
        if against {
            self.excursion(at.distance)?;
            self.exits += 1;
            self.exit_lots += i128::from(fill.lots.0);
            self.exit_value += i128::from(at.price.0) * i128::from(fill.lots.0);
        }
        Ok(())
    }

    /// The position marked as `mark` says: its excursions, its level, and its path follow.
    fn marked(&mut self, mark: &Mark) -> Result<(), Overflow> {
        let at = self.path_price(mark.price)?;
        self.excursion(at.distance)?;
        self.coarsest = self.coarsest.max(mark.fidelity);
        if self.path.is_none() {
            return Ok(());
        }
        let adverse_after = self.adverse_after(mark)?;
        if let Some(path) = &mut self.path {
            path.marked(mark.ts, at, adverse_after)?;
        }
        Ok(())
    }

    /// At a bar's extreme in the trade's favour, the bar's other extreme when it lies beyond the
    /// bar's close, which the bar may have reached after it (§15); none at any other mark.
    fn adverse_after(&self, mark: &Mark) -> Result<Option<PathPrice>, Overflow> {
        let Some((reached, bar)) = mark.extreme else {
            return Ok(None);
        };
        let favourable = match self.entry.side {
            Side::Buy => Extreme::High,
            Side::Sell => Extreme::Low,
        };
        let adverse = favourable.other().of(&bar);
        let beyond = self.distance(adverse)? < self.distance(bar.close)?;
        if reached != favourable || !beyond {
            return Ok(None);
        }
        self.path_price(adverse).map(Some)
    }

    /// The distance of `price`, as the run marks prices, from the entry's price, which a roll
    /// moves, above zero in the trade's favour.
    fn distance(&self, price: Price) -> Result<Price, Overflow> {
        match self.entry.side {
            Side::Buy => price.checked_sub(self.reference),
            Side::Sell => self.reference.checked_sub(price),
        }
    }

    /// `price`, as the run marks prices, as the path takes it: its distance from the entry's
    /// price, and its price in the entry contract's prices, each roll's gap taken off.
    fn path_price(&self, price: Price) -> Result<PathPrice, Overflow> {
        let crossed = self.reference.checked_sub(self.entry.price)?;
        Ok(PathPrice {
            distance: self.distance(price)?,
            price: price.checked_sub(crossed)?,
        })
    }

    /// A price at `distance` from the entry's: the farthest against the trade and for it, and
    /// the deepest fall from the best before it.
    fn excursion(&mut self, distance: Price) -> Result<(), Overflow> {
        self.favourable = self.favourable.max(distance);
        self.adverse = self.adverse.max(Price(0).checked_sub(distance)?);
        let fall = self.favourable.checked_sub(distance)?;
        self.drawdown = self.drawdown.max(fall);
        Ok(())
    }

    /// The trade, closed by `traded`, the fill that left it flat, and its path.
    fn closed_by(
        self,
        traded: &TradedFill<'_>,
        instrument: &InstrumentParameters,
    ) -> Result<(Trade, Option<TradePath>), Overflow> {
        let tick = instrument.tick_size().0;
        let (mae_ticks, mfe_ticks) = (self.adverse.0 / tick, self.favourable.0 / tick);
        let max_drawdown_ticks = self.drawdown.0 / tick;
        let lots = self.entry.lots;
        let excursion = |ticks: i64| instrument.value(Price(ticks * tick), lots);
        let pnl = self
            .gross_pnl
            .checked_sub(self.fees)?
            .checked_add(self.funding)?;
        let trade = Trade {
            side: self.entry.side,
            lots,
            entry_order: self.entry.order,
            entry_decision: self.entry_decision,
            entry_ts: self.entry.ts,
            entry_price: self.entry.price,
            entry_contract: self.entry_contract,
            exits: self.exits,
            exit_price: average(self.exit_value, self.exit_lots),
            exit_ts: traded.fill.ts,
            exit_reason: traded.fill.role,
            exit_contract: traded.contract.clone(),
            rolls: self.rolls,
            gross_pnl: self.gross_pnl,
            fees: self.fees,
            funding: self.funding,
            pnl,
            initial_risk_ticks: self.initial_risk_ticks,
            mae_ticks,
            mfe_ticks,
            mae: excursion(mae_ticks)?,
            mfe: excursion(mfe_ticks)?,
            max_drawdown_ticks,
            max_drawdown: excursion(max_drawdown_ticks)?,
            path_fidelity: self.coarsest,
        };
        Ok((trade, self.path.map(PathRecorder::into_path)))
    }
}

/// `value` over `lots`, the average price of the exits; none without exits.
fn average(value: i128, lots: i128) -> Option<f64> {
    (lots != 0).then(|| value as f64 / lots as f64)
}

/// The share of `amount` that `part` of `whole` lots take, rounded down.
fn share(amount: Money, part: i64, whole: i64) -> Result<Money, Overflow> {
    let product = i128::from(amount.0) * i128::from(part);
    let shared = product.div_euclid(i128::from(whole));
    i64::try_from(shared).map(Money).map_err(|_| Overflow {
        operation: "a share of a fill's money",
        left: product,
        right: whole.into(),
    })
}
