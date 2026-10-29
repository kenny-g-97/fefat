//! The trades of a run (`docs/spec/fill-semantics.md` §20, step 2.10): each from the fill that
//! opens a position from flat to the fill that leaves it flat, through the legs of a roll that
//! transfers it (F-ROL-02). A trade records its entry, its exits, the one that left it flat and
//! why, the rolls it crossed, its money (what its fills' values moved the cash by, their fees,
//! and the funding paid or received while it was open, F-FND-01), its initial risk (F-RND-02),
//! and its excursions, the farthest the prices the run marks the position at (F-MRK-01) went
//! against it and for it from its entry's price, in whole ticks, a roll moving that price by its
//! gap as it moves the exit plan's (F-ROL-03). A position held when the tape starts, which no
//! fill opened, is no trade, nor is one still open when the run ends.

use fefat_core::fills::Fill;
use fefat_core::instants::Ts;
use fefat_core::instrument::{Contract, InstrumentParameters};
use fefat_core::orders::{Order, OrderId, OrderKind, OrderRole, Side};
use fefat_core::units::{Money, Overflow, Price, Qty};

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
    /// Their prices, averaged by their lots, in 1e-9 units; none when no fill closed lots against
    /// the entry's side, as when one fill reversed the position, which a strategy's own orders can.
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
    /// The farthest the marks went against it, in whole ticks.
    pub mae_ticks: i64,
    /// The farthest they went for it, in whole ticks.
    pub mfe_ticks: i64,
    /// That adverse excursion over its entry's lots, in micro-units.
    pub mae: Money,
    /// That favourable excursion over its entry's lots, in micro-units.
    pub mfe: Money,
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
}

/// The run's trades: the lots its fills hold, the trade open, and those closed.
#[derive(Debug, Clone, PartialEq)]
pub(super) struct TradeBook {
    held: i64,
    open: Option<OpenTrade>,
    closed: Vec<Trade>,
}

/// A fill as the trades take it: the fill, when its order was placed, the cash its value moved,
/// its contract, whether it left the position flat, and the legs its exit plan placed.
pub(super) struct TradedFill<'fill> {
    pub(super) fill: &'fill Fill,
    pub(super) placed_at: Ts,
    pub(super) cash: Money,
    pub(super) contract: &'fill Contract,
    pub(super) flat_after: bool,
    pub(super) legs: &'fill [Order],
}

impl TradeBook {
    /// The trades of a run that starts holding `held` lots, positive long.
    pub(super) const fn holding(held: i64) -> Self {
        Self {
            held,
            open: None,
            closed: Vec::new(),
        }
    }

    /// The trades closed, in the order they closed.
    pub(super) fn into_closed(self) -> Vec<Trade> {
        self.closed
    }

    /// `traded`, the next fill: it opens a trade from flat, closes some of the open trade's lots,
    /// transfers it, or leaves it flat and closes it.
    pub(super) fn filled(
        &mut self,
        traded: &TradedFill<'_>,
        instrument: &InstrumentParameters,
    ) -> Result<(), Overflow> {
        let fill = traded.fill;
        let signed = match fill.side {
            Side::Buy => fill.lots.0,
            Side::Sell => -fill.lots.0,
        };
        let from_flat = self.held == 0;
        self.held += signed;
        let Some(open) = &mut self.open else {
            if from_flat {
                self.open = Some(OpenTrade::of(traded, instrument.tick_size())?);
            }
            return Ok(());
        };
        open.count(traded)?;
        if traded.flat_after
            && let Some(open) = self.open.take()
        {
            self.closed.push(open.closed_by(traded, instrument)?);
        }
        Ok(())
    }

    /// The position marked at `price` (F-MRK-01), which the open trade's excursions follow.
    pub(super) fn marked(&mut self, price: Price) -> Result<(), Overflow> {
        match &mut self.open {
            Some(open) => open.marked(price),
            None => Ok(()),
        }
    }

    /// The prices from `low` to `high` that a block of records passed over reached while the
    /// trade stayed open, as a full replay would mark them.
    pub(super) fn reached(&mut self, low: Price, high: Price) -> Result<(), Overflow> {
        self.marked(low)?;
        self.marked(high)
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
    /// The trade `traded`, its entry, opens, its initial risk the ticks to its plan's stop.
    fn of(traded: &TradedFill<'_>, tick: Price) -> Result<Self, Overflow> {
        let entry = traded.fill;
        let stop = traded.legs.iter().find_map(|leg| match leg.kind {
            OrderKind::StopMarket { stop } => Some(stop),
            OrderKind::Market | OrderKind::Limit { .. } => None,
        });
        let initial_risk_ticks = stop
            .map(|stop| {
                Ok::<_, Overflow>(entry.price.checked_sub(stop)?.0.saturating_abs() / tick.0)
            })
            .transpose()?;
        Ok(Self {
            entry: *entry,
            entry_decision: traded.placed_at,
            entry_contract: traded.contract.clone(),
            initial_risk_ticks,
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
        })
    }

    /// A fill after the entry: its money counts, a roll's close leg counts a roll, and any other
    /// fill against the entry's side counts an exit.
    fn count(&mut self, traded: &TradedFill<'_>) -> Result<(), Overflow> {
        let fill = traded.fill;
        self.gross_pnl = self.gross_pnl.checked_add(traded.cash)?;
        self.fees = self.fees.checked_add(fill.fee)?;
        let against = fill.side != self.entry.side;
        let transfer_leg = matches!(fill.role, OrderRole::Roll(_)) && !traded.flat_after;
        if transfer_leg {
            self.rolls += u32::from(against);
            return Ok(());
        }
        if against {
            self.exits += 1;
            self.exit_lots += i128::from(fill.lots.0);
            self.exit_value += i128::from(fill.price.0) * i128::from(fill.lots.0);
        }
        Ok(())
    }

    /// The marks' distance from the entry's price, which a roll moves, for the entry's side.
    fn marked(&mut self, price: Price) -> Result<(), Overflow> {
        let distance = match self.entry.side {
            Side::Buy => price.checked_sub(self.reference)?,
            Side::Sell => self.reference.checked_sub(price)?,
        };
        self.favourable = self.favourable.max(distance);
        self.adverse = self.adverse.max(Price(0).checked_sub(distance)?);
        Ok(())
    }

    /// The trade, closed by `traded`, the fill that left it flat.
    fn closed_by(
        self,
        traded: &TradedFill<'_>,
        instrument: &InstrumentParameters,
    ) -> Result<Trade, Overflow> {
        let tick = instrument.tick_size().0;
        let (mae_ticks, mfe_ticks) = (self.adverse.0 / tick, self.favourable.0 / tick);
        let lots = self.entry.lots;
        let excursion = |ticks: i64| instrument.value(Price(ticks * tick), lots);
        let pnl = self
            .gross_pnl
            .checked_sub(self.fees)?
            .checked_add(self.funding)?;
        Ok(Trade {
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
        })
    }
}

/// `value` over `lots`, the average price of the exits; none without exits.
fn average(value: i128, lots: i128) -> Option<f64> {
    (lots != 0).then(|| value as f64 / lots as f64)
}
