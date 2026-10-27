//! The orders of a run from placement to fill or cancellation, as `fefat.reference.orders.Book`
//! holds them: each with its state, whether it has rested (F-LMT-04), the point of the run's
//! timeline after which it sees records (F-ACT-01), its OCO group (F-OCO-01), and the bracket its
//! fill places (F-OCO-02).

use fefat_core::orders::{Order, OrderId, OrderKind, OrderRole, OrderState, Side};
use fefat_core::units::{Overflow, Price};

/// Where a bracket's leg is placed: at a price, or a number of ticks from its entry's fill price,
/// against the position for the stop and in its favour for the target (F-OCO-02).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LegPrice {
    /// At this price, wherever the entry fills.
    At(Price),
    /// This many ticks from the entry's fill price.
    TicksFromFill(u32),
}

/// A bracket's stop or target: the id the decision gives it, a new one where it gives none, and
/// where it is placed.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct BracketLeg {
    /// Its id, as an order scenario names it.
    pub id: Option<OrderId>,
    /// Its price.
    pub price: LegPrice,
}

/// The stop and the target placed, as one OCO group, when their entry fills (F-OCO-02).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Bracket {
    /// The stop, a stop-market order against the position.
    pub stop: BracketLeg,
    /// The target, a limit order in the position's favour.
    pub target: BracketLeg,
}

impl Bracket {
    /// The stop's and the target's prices for an entry on `side` filled at `fill`: in ticks, a
    /// buy's stop below the fill and its target above it, a sell's the other way round.
    pub(crate) fn prices(
        &self,
        side: Side,
        fill: Price,
        tick: Price,
    ) -> Result<(Price, Price), Overflow> {
        let stop = match self.stop.price {
            LegPrice::At(price) => price,
            LegPrice::TicksFromFill(ticks) => side.opposite().moved(fill, ticks, tick)?,
        };
        let target = match self.target.price {
            LegPrice::At(price) => price,
            LegPrice::TicksFromFill(ticks) => side.moved(fill, ticks, tick)?,
        };
        Ok((stop, target))
    }
}

/// An order the run holds. Its state and whether it rested change only through the book's
/// transitions: waiting to working at its first record, working to triggered (a stop on TBBO),
/// resting while it works, and closed, filled or cancelled.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkingOrder {
    /// The order as placed.
    pub order: Order,
    state: OrderState,
    rested: bool,
    /// The point of the run's timeline after which it sees records: the decision that placed it,
    /// or the record that filled its entry (F-ACT-01, F-OCO-02).
    pub seen_after: usize,
    /// What it has to do with a bracket.
    pub link: BracketLink,
}

/// How a live order closes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Closing {
    /// It filled whole.
    Filled,
    /// Its OCO group filled, or its strategy cancelled it.
    Cancelled,
}

/// What an order has to do with a bracket (F-OCO-02): nothing, an entry whose fill places one, or
/// one of its legs.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BracketLink {
    /// No bracket.
    Unbracketed,
    /// An entry whose fill places this bracket.
    Entry(Bracket),
    /// A leg of the bracket of this entry; the legs of one entry form one OCO group.
    LegOf(OrderId),
}

impl BracketLink {
    /// The entry whose bracket this order is a leg of.
    pub const fn leg_of(self) -> Option<OrderId> {
        match self {
            Self::LegOf(entry) => Some(entry),
            Self::Unbracketed | Self::Entry(_) => None,
        }
    }
}

impl WorkingOrder {
    /// A new order, waiting for the first record it sees (F-ACT-01).
    pub(crate) const fn placed(order: Order, seen_after: usize, link: BracketLink) -> Self {
        Self {
            order,
            state: OrderState::Waiting,
            rested: false,
            seen_after,
            link,
        }
    }

    /// Where it stands.
    pub const fn state(&self) -> OrderState {
        self.state
    }

    /// Whether it saw a price without filling: a limit filled later rested (F-LMT-04).
    pub const fn has_rested(&self) -> bool {
        self.rested
    }

    /// The stop's or the limit's price; a market order has none.
    pub const fn level(&self) -> Option<Price> {
        match self.order.kind {
            OrderKind::Market => None,
            OrderKind::StopMarket { stop } => Some(stop),
            OrderKind::Limit { limit } => Some(limit),
        }
    }

    fn shares_group_with(&self, other: &Self) -> bool {
        let named = self.order.oco.is_some() && self.order.oco == other.order.oco;
        let bracket = match (self.link, other.link) {
            (BracketLink::LegOf(entry), BracketLink::LegOf(other_entry)) => entry == other_entry,
            _ => false,
        };
        named || bracket
    }
}

/// The orders of a run: the live ones, waiting, working, or triggered, and those filled or
/// cancelled; and the ids it has given orders of its own, from 1.
#[derive(Debug, Clone, Default)]
pub struct Book {
    live: Vec<WorkingOrder>,
    closed: Vec<WorkingOrder>,
    issued: u64,
}

impl Book {
    /// A new id for an order the run places itself: 1, then 2, and so on.
    pub(crate) fn new_id(&mut self) -> OrderId {
        self.issued += 1;
        OrderId(self.issued)
    }

    pub(crate) fn place(&mut self, order: WorkingOrder) {
        self.live.push(order);
    }

    /// The live orders, in the order they were placed.
    pub(crate) fn live(&self) -> impl Iterator<Item = &WorkingOrder> {
        self.live.iter()
    }

    /// The live orders and the ids given, without the closed orders: the book a bar is replayed
    /// on with its extremes the other way round (F-BAR-05), which the run then drops, as
    /// `Book.copied` copies the reference's.
    pub(crate) fn trial(&self) -> Self {
        Self {
            live: self.live.clone(),
            closed: Vec::new(),
            issued: self.issued,
        }
    }

    /// The ids of the live orders in `state` whose kind `wanted` keeps, lowest first: a snapshot
    /// that a loop over them checks again order by order, since a fill can cancel its group while
    /// the loop runs (`Book.each`).
    pub(crate) fn ids_in(
        &self,
        state: OrderState,
        wanted: impl Fn(&OrderKind) -> bool,
    ) -> Vec<OrderId> {
        let mut ids: Vec<OrderId> = self
            .live
            .iter()
            .filter(|order| order.state == state && wanted(&order.order.kind))
            .map(|order| order.order.id)
            .collect();
        ids.sort_unstable();
        ids
    }

    /// The ids of the live orders, lowest first.
    pub(crate) fn live_ids(&self) -> Vec<OrderId> {
        let mut ids: Vec<OrderId> = self.live.iter().map(|order| order.order.id).collect();
        ids.sort_unstable();
        ids
    }

    /// The live order `id` while it is still in `state`.
    pub(crate) fn live_in(&self, id: OrderId, state: OrderState) -> Option<&WorkingOrder> {
        self.live
            .iter()
            .find(|order| order.order.id == id && order.state == state)
    }

    /// Waiting to working: the order `id` sees its first record (F-ACT-01). None when no live
    /// order `id` waits.
    pub(crate) fn activate(&mut self, id: OrderId) -> Option<&WorkingOrder> {
        let order = self.live_in_mut(id, OrderState::Waiting)?;
        order.state = OrderState::Working;
        Some(order)
    }

    /// Working to triggered: a stop on TBBO that a trade reached, filled at the next tradeable
    /// record's quote (F-STP-02). None when no live order `id` works.
    pub(crate) fn trigger(&mut self, id: OrderId) -> Option<()> {
        self.live_in_mut(id, OrderState::Working)?.state = OrderState::Triggered;
        Some(())
    }

    /// The working order `id` saw a price without filling: it rests (F-LMT-04). None when no live
    /// order `id` works.
    pub(crate) fn rest(&mut self, id: OrderId) -> Option<()> {
        self.live_in_mut(id, OrderState::Working)?.rested = true;
        Some(())
    }

    /// Closes the live order `id`, filled or cancelled, and returns it.
    pub(crate) fn close(&mut self, id: OrderId, closing: Closing) -> Option<WorkingOrder> {
        let index = self.live.iter().position(|order| order.order.id == id)?;
        let mut order = self.live.remove(index);
        order.state = match closing {
            Closing::Filled => OrderState::Filled,
            Closing::Cancelled => OrderState::Cancelled,
        };
        self.closed.push(order.clone());
        Some(order)
    }

    fn live_in_mut(&mut self, id: OrderId, state: OrderState) -> Option<&mut WorkingOrder> {
        self.live
            .iter_mut()
            .find(|order| order.order.id == id && order.state == state)
    }

    /// The live orders of `order`'s OCO group, lowest id first (F-OCO-01).
    pub(crate) fn group_of(&self, order: &WorkingOrder) -> Vec<OrderId> {
        let mut ids: Vec<OrderId> = self
            .live
            .iter()
            .filter(|other| order.shares_group_with(other))
            .map(|other| other.order.id)
            .collect();
        ids.sort_unstable();
        ids
    }

    /// Whether any order is live.
    pub(crate) fn has_live(&self) -> bool {
        !self.live.is_empty()
    }

    /// Whether a market order is on its way out of the position: the exit that flatten placed,
    /// or a stop triggered on TBBO, a market order from its trigger that no decision cancels
    /// (F-STP-02).
    pub(crate) fn is_exiting(&self) -> bool {
        self.live.iter().any(|order| {
            order.order.role == OrderRole::Exit || order.state == OrderState::Triggered
        })
    }

    /// The order `id`, live or closed.
    pub fn order(&self, id: OrderId) -> Option<&WorkingOrder> {
        self.live
            .iter()
            .chain(&self.closed)
            .find(|order| order.order.id == id)
    }

    /// Every order of the run, by id, each in its last state.
    pub fn into_orders(self) -> Vec<WorkingOrder> {
        let mut orders = self.closed;
        orders.extend(self.live);
        orders.sort_by_key(|order| order.order.id);
        orders
    }
}
