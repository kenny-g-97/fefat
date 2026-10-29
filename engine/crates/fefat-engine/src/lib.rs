//! The backtest loop over fefat-core. Step 2.6 brings the event loop over the tick level of a
//! `MarketDataReader`, the fill rules of `docs/spec/fill-semantics.md` it applies, the book of
//! orders, the event log, and the strategies it runs: an order scenario's orders and the
//! execution template. Step 2.7 adds the replay of bars as pseudo-ticks, the descent that skips
//! the records no order can act on, and the template's flat-by; step 2.8 the full exit plan; and
//! step 2.9 the run's fees, funding, and rolls, with a cost line for each fee and payment. Pure
//! computation: nothing here opens a file.

pub mod book;
pub mod event_log;
mod exact_decimal;
pub mod exit_plan;
pub mod hours;
mod rules;
pub mod settings;
pub mod strategy;
pub mod template;
pub mod tick_run;
