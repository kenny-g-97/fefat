//! The tables of runs' trades, of their paths, and of their accounts at each decision (steps 2.10
//! and 2.13), each row tagged with its run's `case`, as `crate::artifacts` tags the others: a
//! trade per flat-to-flat episode (`docs/spec/fill-semantics.md` §20) with its entry, its exits,
//! the rolls it crossed, its money in micro-units, its initial risk, its excursions, its fall from
//! its peak, and its path's fidelity; each point of each trade's path (`03-prop-simulator.md`
//! §4.2); and the cash, the lots, the price the position is valued at, and the equity after each
//! decision.

use std::sync::Arc;

use arrow_array::{ArrayRef, Float64Array, Int64Array, RecordBatch, StringArray, UInt64Array};
use arrow_schema::ArrowError;
use fefat_core::orders::Side;
use fefat_engine::tick_run::{EquityPoint, PathPoint, RunOutputs, Trade};

use crate::artifacts::{CASE_COLUMN, batch};

type TradeRow<'run> = (i64, &'run Trade);
type PathRow<'run> = (i64, usize, &'run PathPoint);
type EquityRow<'run> = (i64, &'run EquityPoint);

/// Each run's trades, in the order they closed: `side`, `long` or `short`, and `lots` of the
/// entry; the entry's order, the decision that placed it, its fill's instant, price, and
/// contract; the exits, their count and the average of their prices, a float of 1e-9 units, the
/// closing fill's instant, its role as the exit reason, and its contract; the rolls crossed; the
/// gross profit and loss, the fees, the funding received, and the net, `pnl`; the initial risk
/// in ticks; the excursions and the deepest fall from the peak, in ticks and over the entry's lots
/// in micro-units; and the fidelity of its path.
pub fn trades_table(runs: &[(i64, RunOutputs)]) -> Result<RecordBatch, ArrowError> {
    let rows: Vec<TradeRow<'_>> = runs
        .iter()
        .flat_map(|(case, run)| run.trades.iter().map(move |trade| (*case, trade)))
        .collect();
    let int = |value: fn(&TradeRow<'_>) -> i64| -> ArrayRef {
        Arc::new(Int64Array::from_iter_values(rows.iter().map(value)))
    };
    let text = |value: fn(&TradeRow<'_>) -> String| -> ArrayRef {
        Arc::new(StringArray::from_iter_values(rows.iter().map(value)))
    };
    let orders = rows.iter().map(|(_, trade)| trade.entry_order.0);
    let exit_prices = rows.iter().map(|(_, trade)| trade.exit_price);
    let risks = rows.iter().map(|(_, trade)| trade.initial_risk_ticks);
    batch(vec![
        (CASE_COLUMN, int(|(case, _)| *case)),
        ("side", text(|(_, trade)| side_word(trade.side).to_owned())),
        ("lots", int(|(_, trade)| trade.lots.0)),
        (
            "entry_order",
            Arc::new(UInt64Array::from_iter_values(orders)),
        ),
        ("entry_decision", int(|(_, trade)| trade.entry_decision.0)),
        ("entry_ts", int(|(_, trade)| trade.entry_ts.0)),
        ("entry_price", int(|(_, trade)| trade.entry_price.0)),
        (
            "entry_contract",
            text(|(_, trade)| trade.entry_contract.0.clone()),
        ),
        ("exits", int(|(_, trade)| i64::from(trade.exits))),
        (
            "exit_price",
            Arc::new(Float64Array::from(exit_prices.collect::<Vec<_>>())),
        ),
        ("exit_ts", int(|(_, trade)| trade.exit_ts.0)),
        (
            "exit_reason",
            text(|(_, trade)| trade.exit_reason.to_string()),
        ),
        (
            "exit_contract",
            text(|(_, trade)| trade.exit_contract.0.clone()),
        ),
        ("rolls", int(|(_, trade)| i64::from(trade.rolls))),
        ("gross_pnl", int(|(_, trade)| trade.gross_pnl.0)),
        ("fees", int(|(_, trade)| trade.fees.0)),
        ("funding", int(|(_, trade)| trade.funding.0)),
        ("pnl", int(|(_, trade)| trade.pnl.0)),
        (
            "initial_risk_ticks",
            Arc::new(Int64Array::from(risks.collect::<Vec<_>>())),
        ),
        ("mae_ticks", int(|(_, trade)| trade.mae_ticks)),
        ("mfe_ticks", int(|(_, trade)| trade.mfe_ticks)),
        ("mae", int(|(_, trade)| trade.mae.0)),
        ("mfe", int(|(_, trade)| trade.mfe.0)),
        (
            "max_drawdown_ticks",
            int(|(_, trade)| trade.max_drawdown_ticks),
        ),
        ("max_drawdown", int(|(_, trade)| trade.max_drawdown.0)),
        (
            "path_fidelity",
            text(|(_, trade)| trade.path_fidelity.to_string()),
        ),
    ])
}

/// Each run's trade paths, a row for each point in the order they happened: `trade`, the trade's
/// place among its run's trades from 0; the point's instant, its price in 1e-9 units of the
/// trade's entry contract, and its kind, `fill`, `minute`, `favourable`, `adverse`, or
/// `possible_adverse`; and a fill's order, null for any other point.
pub fn trade_paths_table(runs: &[(i64, RunOutputs)]) -> Result<RecordBatch, ArrowError> {
    let rows: Vec<PathRow<'_>> = runs
        .iter()
        .flat_map(|(case, run)| {
            let paths = run.trade_paths.iter().enumerate();
            paths.flat_map(move |(trade, path)| {
                path.points.iter().map(move |point| (*case, trade, point))
            })
        })
        .collect();
    let int = |value: fn(&PathRow<'_>) -> i64| -> ArrayRef {
        Arc::new(Int64Array::from_iter_values(rows.iter().map(value)))
    };
    let kinds = rows.iter().map(|(_, _, point)| point.kind.to_string());
    let orders = rows
        .iter()
        .map(|(_, _, point)| point.kind.order().map(|order| order.0));
    batch(vec![
        (CASE_COLUMN, int(|(case, _, _)| *case)),
        ("trade", int(|(_, trade, _)| *trade as i64)),
        ("ts", int(|(_, _, point)| point.ts.0)),
        ("price", int(|(_, _, point)| point.price.0)),
        ("kind", Arc::new(StringArray::from_iter_values(kinds))),
        (
            "order",
            Arc::new(UInt64Array::from(orders.collect::<Vec<_>>())),
        ),
    ])
}

/// Each run's account after each decision, in their order: when, the cash, the lots held,
/// positive long, the price the position is valued at, and the equity, the last two null for an
/// open position before its first mark.
pub fn equity_table(runs: &[(i64, RunOutputs)]) -> Result<RecordBatch, ArrowError> {
    let rows: Vec<EquityRow<'_>> = runs
        .iter()
        .flat_map(|(case, run)| run.equity.iter().map(move |point| (*case, point)))
        .collect();
    let int = |value: fn(&EquityRow<'_>) -> i64| -> ArrayRef {
        Arc::new(Int64Array::from_iter_values(rows.iter().map(value)))
    };
    let marks = rows.iter().map(|(_, point)| point.mark.map(|mark| mark.0));
    let equities = rows
        .iter()
        .map(|(_, point)| point.equity.map(|equity| equity.0));
    batch(vec![
        (CASE_COLUMN, int(|(case, _)| *case)),
        ("ts", int(|(_, point)| point.ts.0)),
        ("cash", int(|(_, point)| point.cash.0)),
        ("position", int(|(_, point)| point.position.0)),
        (
            "mark",
            Arc::new(Int64Array::from(marks.collect::<Vec<_>>())),
        ),
        (
            "equity",
            Arc::new(Int64Array::from(equities.collect::<Vec<_>>())),
        ),
    ])
}

const fn side_word(side: Side) -> &'static str {
    match side {
        Side::Buy => "long",
        Side::Sell => "short",
    }
}
