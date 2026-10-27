//! The backtest loop over fefat-core. Step 2.6 brings the event loop over the tick level of a
//! `MarketDataReader`, the fill rules of `docs/spec/fill-semantics.md` it applies, the book of
//! orders, the event log, and the strategies it runs: an order scenario's orders and the
//! execution template's basic subset. Step 2.7 adds the replay of bars as pseudo-ticks, the
//! descent that skips the records no order can act on, and the template's flat-by. The full
//! `ExitPlan` arrives in 2.8, and `AccountModel` with costs in 2.9. Pure computation: nothing here
//! opens a file.

pub mod book;
pub mod event_log;
mod exact_decimal;
pub mod hours;
mod rules;
pub mod settings;
pub mod strategy;
pub mod template;
pub mod tick_run;
