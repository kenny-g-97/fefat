//! The Arrow IPC files a batch writes, each row tagged with its case's place in `run.json`: the
//! fills, each with the contract it is of, the orders in their last state, the event log, each
//! case's ledger at its end, and its cost lines, in Arrow IPC's file format, uncompressed, which
//! Polars' `read_ipc` reads.

use std::fs::File;
use std::io::BufWriter;
use std::path::Path;
use std::sync::Arc;

use arrow_array::{ArrayRef, BooleanArray, Int64Array, RecordBatch, StringArray, UInt64Array};
use arrow_ipc::writer::FileWriter;
use arrow_schema::{ArrowError, Field, Schema};
use fefat_core::costs::{CostLine, CostReason};
use fefat_engine::book::WorkingOrder;
use fefat_engine::event_log::LogEntry;
use fefat_engine::tick_run::{BookedFill, RunOutputs};

use super::{BatchError, arrow_error};

type FillRow<'run> = (i64, &'run BookedFill);
type OrderRow<'run> = (i64, &'run WorkingOrder);
type LogRow<'run> = (i64, &'run LogEntry);
type CostRow<'run> = (i64, &'run CostLine);

/// Writes `fills.arrow`, `orders.arrow`, `log.arrow`, `ledger.arrow`, and `costs.arrow` into
/// `output`.
pub(super) fn write_outputs(output: &Path, runs: &[(i64, RunOutputs)]) -> Result<(), BatchError> {
    let written = [
        ("fills.arrow", fills_batch(runs)),
        ("orders.arrow", orders_batch(runs)),
        ("log.arrow", log_batch(runs)),
        ("ledger.arrow", ledger_batch(runs)),
        ("costs.arrow", costs_batch(runs)),
    ];
    for (name, batch) in written {
        let path = output.join(name);
        write_ipc(&path, &batch.map_err(arrow_error(&path))?)?;
    }
    Ok(())
}

fn fills_batch(runs: &[(i64, RunOutputs)]) -> Result<RecordBatch, ArrowError> {
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
        ("case", int(|(case, _)| *case)),
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
    ])
}

/// Each case's cost lines, in the order they were paid: when, why, `fee` of an order or
/// `funding` at a rate in 1e-9 units, and the amount the trader paid in micro-units.
fn costs_batch(runs: &[(i64, RunOutputs)]) -> Result<RecordBatch, ArrowError> {
    let rows: Vec<CostRow<'_>> = runs
        .iter()
        .flat_map(|(case, run)| run.costs.iter().map(move |line| (*case, line)))
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
        ("case", int(|(case, _)| *case)),
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

fn orders_batch(runs: &[(i64, RunOutputs)]) -> Result<RecordBatch, ArrowError> {
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
        ("case", int(|(case, _)| *case)),
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

fn log_batch(runs: &[(i64, RunOutputs)]) -> Result<RecordBatch, ArrowError> {
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
        ("case", int(|(case, _)| *case)),
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

/// Each case's ledger at its end, the lots it holds, positive long, and its cash in micro-units,
/// and the fills it flagged ambiguous, which the run counts (F-BAR-05).
fn ledger_batch(runs: &[(i64, RunOutputs)]) -> Result<RecordBatch, ArrowError> {
    let int = |value: fn(&(i64, RunOutputs)) -> i64| -> ArrayRef {
        Arc::new(Int64Array::from_iter_values(runs.iter().map(value)))
    };
    batch(vec![
        ("case", int(|(case, _)| *case)),
        (
            "position",
            int(|(_, run)| run.ledger.position().signed_lots().0),
        ),
        ("cash", int(|(_, run)| run.ledger.cash().0)),
        (
            "ambiguous_fills",
            int(|(_, run)| run.ambiguous_fills() as i64),
        ),
    ])
}

fn batch(columns: Vec<(&str, ArrayRef)>) -> Result<RecordBatch, ArrowError> {
    let fields: Vec<Field> = columns
        .iter()
        .map(|(name, column)| Field::new(*name, column.data_type().clone(), true))
        .collect();
    let arrays = columns.into_iter().map(|(_, column)| column).collect();
    RecordBatch::try_new(Arc::new(Schema::new(fields)), arrays)
}

fn write_ipc(path: &Path, batch: &RecordBatch) -> Result<(), BatchError> {
    let io_error = |source| BatchError::Io {
        action: "write",
        path: path.to_path_buf(),
        source,
    };
    let file = File::create(path).map_err(io_error)?;
    let mut writer =
        FileWriter::try_new(BufWriter::new(file), &batch.schema()).map_err(arrow_error(path))?;
    writer.write(batch).map_err(arrow_error(path))?;
    writer.finish().map_err(arrow_error(path))?;
    let buffered = writer.into_inner().map_err(arrow_error(path))?;
    buffered
        .into_inner()
        .map(drop)
        .map_err(|error| io_error(error.into_error()))
}
