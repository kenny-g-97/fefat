//! The orders of a run from placement to fill or cancellation, as `fefat.reference.orders.Book`
//! holds them: each with its state, whether it has rested (F-LMT-04), the point of the run's
//! timeline after which it sees records (F-ACT-01), its OCO group (F-OCO-01), and the exit plan its
//! fill places (F-OCO-02, F-PLN-01); and the plans of the entries that have filled, while a leg of
//! theirs lives, which move their stops and settle their open lots (F-PLN-02 to F-PLN-04).

use std::collections::BTreeMap;

use fefat_core::instants::Ts;
use fefat_core::orders::{Order, OrderId, OrderKind, OrderRole, OrderState, Side};
use fefat_core::units::{Overflow, Price, Qty};

use crate::exit_plan::{ExitPlan, LivePlan};

mod plans;

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

/// The stop and the target placed when their entry fills (F-OCO-02): an order scenario's
/// bracket, an exit plan of one stop and one target for the whole entry (`ExitPlan::from`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Bracket {
    /// The stop, a stop-market order against the position.
    pub stop: BracketLeg,
    /// The target, a limit order in the position's favour.
    pub target: BracketLeg,
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

/// What an order has to do with an exit plan (F-OCO-02, F-PLN-01): nothing, an entry whose fill
/// places one, or one of its legs.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum BracketLink {
    /// No exit plan.
    Unbracketed,
    /// An entry whose fill places this plan.
    Entry(Box<ExitPlan>),
    /// A leg of the plan of this entry; the plan settles its legs' open lots (F-PLN-02).
    LegOf(OrderId),
}

impl BracketLink {
    /// The entry whose plan this order is a leg of.
    pub const fn leg_of(&self) -> Option<OrderId> {
        match self {
            Self::LegOf(entry) => Some(*entry),
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

    /// A market order already sent, a roll's leg, which no decision cancels and which fills on the
    /// first tradeable record or bar after it (F-ROL-02).
    pub(crate) const fn sent(order: Order, seen_after: usize) -> Self {
        Self {
            order,
            state: OrderState::Triggered,
            rested: false,
            seen_after,
            link: BracketLink::Unbracketed,
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
        self.order.oco.is_some() && self.order.oco == other.order.oco
    }
}

/// A live order a roll moved by its gap, from `before` to `after` (F-ROL-03).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Shift {
    /// The order.
    pub order: OrderId,
    /// Its stop's or limit's price before.
    pub before: Price,
    /// Its price after.
    pub after: Price,
}

/// The orders of a run: the live ones, waiting, working, or triggered, and those filled or
/// cancelled; the ids it has given orders of its own, from 1; the live exit plans, by their
/// entries' ids; and the memory of the last snapshot of ids given back (`give_back_ids`).
#[derive(Debug, Clone, Default)]
pub struct Book {
    live: Vec<WorkingOrder>,
    closed: Vec<WorkingOrder>,
    issued: u64,
    plans: BTreeMap<OrderId, LivePlan>,
    spare_ids: Vec<OrderId>,
}

impl Book {
    /// A new id for an order the run places itself: 1, then 2, and so on, after the ids a
    /// strategy reserved.
    pub(crate) fn new_id(&mut self) -> OrderId {
        self.issued += 1;
        OrderId(self.issued)
    }

    /// Keeps the ids through `highest`, which a strategy gives its own orders, from the run's
    /// (F-ROL-02).
    pub(crate) fn reserve_through(&mut self, highest: Option<OrderId>) {
        self.issued = self.issued.max(highest.map_or(0, |id| id.0));
    }

    /// F-ROL-02: the market order already on its way out of all the position's `lots` by `side`
    /// and active by the roll at `at` (F-ACT-01), an exit flatten placed or a stop of its plan
    /// triggered on TBBO, which does a roll's close leg's work; the lowest id should there be more.
    pub(crate) fn on_its_way_out(&self, side: Side, lots: Qty, at: Ts) -> Option<OrderId> {
        let on_its_way = |order: &&WorkingOrder| match order.order.role {
            OrderRole::Exit(_) => true,
            OrderRole::Entry | OrderRole::Roll(_) => false,
            OrderRole::Stop | OrderRole::Target(_) => {
                order.state == OrderState::Triggered && order.link.leg_of().is_some()
            }
        };
        self.live
            .iter()
            .filter(|order| order.order.side == side && order.order.lots == lots)
            .filter(|order| order.order.activation <= at)
            .filter(on_its_way)
            .map(|order| order.order.id)
            .min()
    }

    /// F-ROL-04: with `roll_handling: flatten`, the position's exit plans and any exit on its way
    /// out of part of it are cancelled, the roll's close leg doing their work, but for `exiting`,
    /// an order on its way out of all its lots, which does the close leg's work instead
    /// (F-ROL-02); their ids, lowest first.
    pub(crate) fn cancel_for_roll(&mut self, exiting: Option<OrderId>) -> Vec<OrderId> {
        let closes = |order: &WorkingOrder| {
            let plan_or_exit =
                order.link.leg_of().is_some() || matches!(order.order.role, OrderRole::Exit(_));
            plan_or_exit && Some(order.order.id) != exiting
        };
        let mut ids: Vec<OrderId> = self
            .live
            .iter()
            .filter(|order| closes(order))
            .map(|order| order.order.id)
            .collect();
        ids.sort_unstable();
        for &id in &ids {
            self.close(id, Closing::Cancelled);
        }
        ids
    }

    /// F-ROL-03: a roll's `gap` moves every live stop and limit, returned by id, lowest first, a
    /// stop triggered on TBBO among them; the prices that entries still to fill name for their
    /// plans, and the live plans' fill and best prices, move with it.
    pub(crate) fn shift_by(&mut self, gap: Price) -> Result<Vec<Shift>, Overflow> {
        let mut shifts = Vec::new();
        for order in &mut self.live {
            if let BracketLink::Entry(plan) = &mut order.link {
                plan.shift_by(gap)?;
            }
            let Some(before) = order.level() else {
                continue;
            };
            let after = before.checked_add(gap)?;
            order.order.kind = match order.order.kind {
                OrderKind::StopMarket { .. } => OrderKind::StopMarket { stop: after },
                OrderKind::Limit { .. } => OrderKind::Limit { limit: after },
                OrderKind::Market => OrderKind::Market,
            };
            let id = order.order.id;
            shifts.push(Shift {
                order: id,
                before,
                after,
            });
        }
        shifts.sort_unstable_by_key(|shift| shift.order);
        for plan in self.plans.values_mut() {
            plan.shift_by(gap)?;
        }
        Ok(shifts)
    }

    pub(crate) fn place(&mut self, order: WorkingOrder) {
        self.live.push(order);
    }

    /// The live orders, in the order they were placed.
    pub(crate) fn live(&self) -> impl Iterator<Item = &WorkingOrder> {
        self.live.iter()
    }

    /// The live orders, the ids given, and the live plans, without the closed orders: the book a
    /// bar is replayed on with its extremes the other way round (F-BAR-05), which the run then
    /// drops, as `Book.copied` copies the reference's.
    pub(crate) fn trial(&self) -> Self {
        Self {
            live: self.live.clone(),
            closed: Vec::new(),
            issued: self.issued,
            plans: self.plans.clone(),
            spare_ids: Vec::new(),
        }
    }

    /// The ids of the live orders in `state` whose kind `wanted` keeps, lowest first: a snapshot
    /// that a loop over them checks again order by order, since a fill can cancel its group while
    /// the loop runs (`Book.each`). It reuses the memory of the snapshot last given back
    /// (`give_back_ids`), so that the loops the engine runs at every record allocate nothing.
    pub(crate) fn ids_in(
        &mut self,
        state: OrderState,
        wanted: impl Fn(&OrderKind) -> bool,
    ) -> Vec<OrderId> {
        let mut ids = std::mem::take(&mut self.spare_ids);
        ids.clear();
        let live = self.live.iter();
        let kept = live.filter(|order| order.state == state && wanted(&order.order.kind));
        ids.extend(kept.map(|order| order.order.id));
        ids.sort_unstable();
        ids
    }

    /// Keeps the memory of `ids`, a snapshot of `ids_in` that a loop has done with, for the next.
    pub(crate) fn give_back_ids(&mut self, ids: Vec<OrderId>) {
        self.spare_ids = ids;
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

    /// Closes the live order `id`, filled or cancelled, and returns it; its plan leaves with its
    /// last leg.
    pub(crate) fn close(&mut self, id: OrderId, closing: Closing) -> Option<WorkingOrder> {
        let index = self.live.iter().position(|order| order.order.id == id)?;
        let mut order = self.live.remove(index);
        order.state = match closing {
            Closing::Filled => OrderState::Filled,
            Closing::Cancelled => OrderState::Cancelled,
        };
        if let Some(entry) = order.link.leg_of()
            && !self
                .live
                .iter()
                .any(|other| other.link.leg_of() == Some(entry))
        {
            self.plans.remove(&entry);
        }
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

    /// Whether a market order is on its way out of the position: an exit that flatten placed, or
    /// a stop triggered on TBBO, a market order from its trigger that no decision cancels
    /// (F-STP-02).
    pub(crate) fn is_exiting(&self) -> bool {
        self.live.iter().any(|order| match order.order.role {
            OrderRole::Exit(_) | OrderRole::Roll(_) => true,
            OrderRole::Entry => false,
            OrderRole::Stop | OrderRole::Target(_) => order.state == OrderState::Triggered,
        })
    }

    /// Whether an entry stop triggered on TBBO is on its way into a position, a market order from
    /// its trigger that no decision cancels (F-STP-02, F-ENT-03).
    pub(crate) fn is_entering(&self) -> bool {
        self.live.iter().any(|order| {
            order.order.role == OrderRole::Entry && order.state == OrderState::Triggered
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
