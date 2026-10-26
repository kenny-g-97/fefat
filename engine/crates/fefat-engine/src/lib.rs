//! The backtest loop over fefat-core. Step 2.6 brings the event loop over the tick level of a
//! `MarketDataReader`, the fill rules of `docs/spec/fill-semantics.md` it applies, the book of
//! orders, the event log, and the strategies it runs: an order scenario's orders and the
//! execution template's basic subset. Bar replay arrives in step 2.7, the full `ExitPlan` in 2.8,
//! and `AccountModel` with costs in 2.9. Pure computation: nothing here opens a file.

pub mod book;
pub mod event_log;
pub mod hours;
mod rules;
pub mod settings;
pub mod strategy;
pub mod template;
pub mod tick_run;
