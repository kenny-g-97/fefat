//! The tables of runs' outputs, each row tagged with its run's `case`, the place of the run in its
//! batch: the fills, each with the contract it is of and its trade date; the orders in their last
//! state; the event log; the cost lines; and the trades, their paths, and the accounts at each
//! decision (`crate::trade_tables`). `fefat-cli run` writes them for a batch, and `fefat_engine`
//! gives a single run's without the tag.

use std::sync::Arc;

use arrow_array::{
    ArrayRef, BooleanArray, Date32Array, Int64Array, RecordBatch, StringArray, UInt64Array,
};
use arrow_schema::{ArrowError, Field, Schema};
use fefat_core::costs::{CostLine, CostReason};
use fefat_engine::book::WorkingOrder;
use fefat_engine::event_log::LogEntry;
use fefat_engine::tick_run::{BookedFill, RunOutputs};

use crate::trade_tables::{equity_table, trade_paths_table, trades_table};

type FillRow<'run> = (i64, &'run BookedFill);
type OrderRow<'run> = (i64, &'run WorkingOrder);
type LogRow<'run> = (i64, &'run LogEntry);
type CostRow<'run> = (i64, &'run CostLine);

/// The name of the column that tags each row with its run's place in a batch.
pub const CASE_COLUMN: &str = "case";

/// Each table of `runs`, by name: `fills`, `orders`, `log`, `costs`, `trades`, `trade_paths`, and
/// `equity`.
pub fn run_tables(
    runs: &[(i64, RunOutputs)],
) -> Result<Vec<(&'static str, RecordBatch)>, ArrowError> {
    Ok(vec![
        ("fills", fills_table(runs)?),
        ("orders", orders_table(runs)?),
        ("log", log_table(runs)?),
        ("costs", costs_table(runs)?),
        ("trades", trades_table(runs)?),
        ("trade_paths", trade_paths_table(runs)?),
        ("equity", equity_table(runs)?),
    ])
}

/// `table` without its `case` column, the table of one run.
pub fn untagged(mut table: RecordBatch) -> Result<RecordBatch, ArrowError> {
    let index = table.schema().index_of(CASE_COLUMN)?;
    table.remove_column(index);
    Ok(table)
}

/// Each run's fills, in the order they happened (F-TAG-01): the order, its role, side, and lots,
/// when and at what price, the rule that priced it, its fidelity and liquidity, its slippage in
/// ticks, its flags, its fee and the cash its value moved, in micro-units, and its contract.
pub fn fills_table(runs: &[(i64, RunOutputs)]) -> Result<RecordBatch, ArrowError> {
    let rows: Vec<FillRow<'_>> = runs
        .iter()
        .flat_map(|(case, run)| run.fills.iter().map(move |booked| (*case, booked)))
        .collect();
    let int = |value: fn(&FillRow<'_>) -> i64| -> ArrayRef {
        Arc::new(Int64Array::from_iter_values(rows.iter().map(value)))
    };
    let text = |value: fn(&FillRow<'_>) -> String| -> ArrayRef {
        Arc::new(StringArray::from_iter_values(rows.iter().map(value)))
    };
    let flag = |value: fn(&FillRow<'_>) -> bool| -> ArrayRef {
        Arc::new(BooleanArray::from(
            rows.iter().map(value).collect::<Vec<_>>(),
        ))
    };
    let order = UInt64Array::from_iter_values(rows.iter().map(|(_, booked)| booked.fill.order.0));
    batch(vec![
        (CASE_COLUMN, int(|(case, _)| *case)),
        ("order", Arc::new(order)),
        ("role", text(|(_, booked)| booked.fill.role.to_string())),
        ("side", text(|(_, booked)| booked.fill.side.to_string())),
        ("lots", int(|(_, booked)| booked.fill.lots.0)),
        ("ts", int(|(_, booked)| booked.fill.ts.0)),
        ("price", int(|(_, booked)| booked.fill.price.0)),
        ("rule", text(|(_, booked)| booked.fill.rule.id().to_owned())),
        (
            "fidelity",
            text(|(_, booked)| booked.fill.fidelity.to_string()),
        ),
        (
            "liquidity",
            text(|(_, booked)| booked.fill.liquidity.to_string()),
        ),
        (
            "slippage_ticks",
            int(|(_, booked)| booked.fill.slippage_ticks),
        ),
        ("ambiguous", flag(|(_, booked)| booked.fill.flags.ambiguous)),
        (
            "size_exceeded",
            flag(|(_, booked)| booked.fill.flags.size_exceeded),
        ),
        ("fee", int(|(_, booked)| booked.fill.fee.0)),
        ("cash", int(|(_, booked)| booked.cash.0)),
        ("contract", text(|(_, booked)| booked.contract.0.clone())),
        (
            "trade_date",
            Arc::new(Date32Array::from_iter_values(
                rows.iter().map(|(_, booked)| booked.trade_date.0),
            )),
        ),
    ])
}

/// Each run's cost lines, in the order they were paid: when, why, `fee` of an order or
/// `funding` at a rate in 1e-9 units, and the amount the trader paid in micro-units.
pub fn costs_table(runs: &[(i64, RunOutputs)]) -> Result<RecordBatch, ArrowError> {
    let rows: Vec<CostRow<'_>> = runs
        .iter()
        .flat_map(|(case, run)| run.cost_lines.iter().map(move |line| (*case, line)))
        .collect();
    let int = |value: fn(&CostRow<'_>) -> i64| -> ArrayRef {
        Arc::new(Int64Array::from_iter_values(rows.iter().map(value)))
    };
    let reasons = rows.iter().map(|(_, line)| match line.reason {
        CostReason::Fee { .. } => "fee",
        CostReason::Funding { .. } => "funding",
    });
    let orders = rows.iter().map(|(_, line)| match line.reason {
        CostReason::Fee { order } => Some(order.0),
        CostReason::Funding { .. } => None,
    });
    let rates = rows.iter().map(|(_, line)| match line.reason {
        CostReason::Fee { .. } => None,
        CostReason::Funding { rate } => Some(rate.0),
    });
    batch(vec![
        (CASE_COLUMN, int(|(case, _)| *case)),
        ("ts", int(|(_, line)| line.ts.0)),
        ("reason", Arc::new(StringArray::from_iter_values(reasons))),
        (
            "order",
            Arc::new(UInt64Array::from(orders.collect::<Vec<_>>())),
        ),
        (
            "rate",
            Arc::new(Int64Array::from(rates.collect::<Vec<_>>())),
        ),
        ("amount", int(|(_, line)| line.amount.0)),
    ])
}

/// Each run's orders in their last state, by id.
pub fn orders_table(runs: &[(i64, RunOutputs)]) -> Result<RecordBatch, ArrowError> {
    let rows: Vec<OrderRow<'_>> = runs
        .iter()
        .flat_map(|(case, run)| run.orders.iter().map(move |order| (*case, order)))
        .collect();
    let int = |value: fn(&OrderRow<'_>) -> i64| -> ArrayRef {
        Arc::new(Int64Array::from_iter_values(rows.iter().map(value)))
    };
    let id = |value: fn(&OrderRow<'_>) -> Option<u64>| -> ArrayRef {
        Arc::new(UInt64Array::from(
            rows.iter().map(value).collect::<Vec<_>>(),
        ))
    };
    let text = |value: fn(&OrderRow<'_>) -> String| -> ArrayRef {
        Arc::new(StringArray::from_iter_values(rows.iter().map(value)))
    };
    let price = rows
        .iter()
        .map(|(_, order)| order.level().map(|price| price.0));
    batch(vec![
        (CASE_COLUMN, int(|(case, _)| *case)),
        ("id", id(|(_, order)| Some(order.order.id.0))),
        ("side", text(|(_, order)| order.order.side.to_string())),
        ("kind", text(|(_, order)| order.order.kind.to_string())),
        (
            "price",
            Arc::new(Int64Array::from(price.collect::<Vec<_>>())),
        ),
        ("lots", int(|(_, order)| order.order.lots.0)),
        ("role", text(|(_, order)| order.order.role.to_string())),
        ("placed_at", int(|(_, order)| order.order.placed_at.0)),
        ("activation", int(|(_, order)| order.order.activation.0)),
        ("oco", id(|(_, order)| order.order.oco.map(|group| group.0))),
        (
            "bracket_of",
            id(|(_, order)| order.link.leg_of().map(|entry| entry.0)),
        ),
        ("state", text(|(_, order)| order.state().to_string())),
    ])
}

/// Each run's event log, in its order.
pub fn log_table(runs: &[(i64, RunOutputs)]) -> Result<RecordBatch, ArrowError> {
    let rows: Vec<LogRow<'_>> = runs
        .iter()
        .flat_map(|(case, run)| run.log.iter().map(move |entry| (*case, entry)))
        .collect();
    let int = |value: fn(&LogRow<'_>) -> i64| -> ArrayRef {
        Arc::new(Int64Array::from_iter_values(rows.iter().map(value)))
    };
    let text = |value: fn(&LogRow<'_>) -> String| -> ArrayRef {
        Arc::new(StringArray::from_iter_values(rows.iter().map(value)))
    };
    let order = rows
        .iter()
        .map(|(_, entry)| entry.order.map(|order| order.0));
    let rule = rows.iter().map(|(_, entry)| entry.rule);
    batch(vec![
        (CASE_COLUMN, int(|(case, _)| *case)),
        ("ts", int(|(_, entry)| entry.ts.0)),
        ("kind", text(|(_, entry)| entry.kind.to_string())),
        (
            "order",
            Arc::new(UInt64Array::from(order.collect::<Vec<_>>())),
        ),
        (
            "rule",
            Arc::new(StringArray::from(rule.collect::<Vec<_>>())),
        ),
        ("text", text(|(_, entry)| entry.text.clone())),
    ])
}

/// A table of `columns`, each nullable, as `fefat-cli run` has always written them.
pub fn batch(columns: Vec<(&str, ArrayRef)>) -> Result<RecordBatch, ArrowError> {
    let fields: Vec<Field> = columns
        .iter()
        .map(|(name, column)| Field::new(*name, column.data_type().clone(), true))
        .collect();
    let arrays = columns.into_iter().map(|(_, column)| column).collect();
    RecordBatch::try_new(Arc::new(Schema::new(fields)), arrays)
}
