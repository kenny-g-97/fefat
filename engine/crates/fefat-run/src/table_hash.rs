//! The hash of an Arrow table (step 2.10): BLAKE3 over a domain tag, the count of its columns and
//! of its rows, then each column in order, its name, its type, and each row's validity and value
//! as little-endian bytes, every name, type, and text framed by its length. A table hashes alike
//! however its rows are split into batches, and on every system, so that the signal frame's hash,
//! a part of the run key (`02` §4), and the artifact hashes of the backtest golden can be compared
//! between Windows and Linux. Text hashes alike whether Arrow holds it as `Utf8`, `LargeUtf8`, or
//! `Utf8View`, any of which Polars may export; times of day, instants, and durations, such as a
//! feature's local time, hash as counts of their unit, their type's unit and zone among the type.

use arrow_array::cast::AsArray;
use arrow_array::types::{
    Date32Type, Date64Type, DurationMicrosecondType, DurationMillisecondType,
    DurationNanosecondType, DurationSecondType, Float32Type, Float64Type, Int8Type, Int16Type,
    Int32Type, Int64Type, Time32MillisecondType, Time32SecondType, Time64MicrosecondType,
    Time64NanosecondType, TimestampMicrosecondType, TimestampMillisecondType,
    TimestampNanosecondType, TimestampSecondType, UInt8Type, UInt16Type, UInt32Type, UInt64Type,
};
use arrow_array::{Array, ArrayRef, ArrowPrimitiveType, PrimitiveArray, RecordBatch};
use arrow_schema::{DataType, Schema, TimeUnit};
use thiserror::Error;

const DOMAIN: &[u8] = b"fefat table hash 1\n";

/// A table that cannot be hashed.
#[derive(Debug, Clone, PartialEq, Eq, Error)]
pub enum TableHashError {
    /// A batch whose columns are not the table's.
    #[error("Expected batches with the columns {expected}, got {actual}")]
    Columns {
        /// The table's columns.
        expected: String,
        /// The batch's.
        actual: String,
    },
    /// A column of a type the hash does not read.
    #[error(
        "Expected a column of booleans, integers, floats, dates, or text, got {data_type} in \
         column {column}"
    )]
    Unsupported {
        /// The column's name.
        column: String,
        /// Its Arrow type.
        data_type: String,
    },
}

/// The hash of the table of `schema` whose rows `batches` hold, as 64 lower-case hexadecimal
/// digits.
pub fn table_hash(schema: &Schema, batches: &[RecordBatch]) -> Result<String, TableHashError> {
    let fields = schema.fields();
    for batch in batches {
        require_columns(schema, batch)?;
    }
    let rows: usize = batches.iter().map(RecordBatch::num_rows).sum();
    let mut hasher = blake3::Hasher::new();
    hasher.update(DOMAIN);
    hasher.update(&(fields.len() as u64).to_le_bytes());
    hasher.update(&(rows as u64).to_le_bytes());
    for (index, field) in fields.iter().enumerate() {
        let word = type_word(field.name(), field.data_type())?;
        framed(&mut hasher, field.name().as_bytes());
        framed(&mut hasher, word.as_bytes());
        for column in batches
            .iter()
            .filter_map(|batch| batch.columns().get(index))
        {
            hash_column(&mut hasher, column, field.name())?;
        }
    }
    Ok(hasher.finalize().to_hex().to_string())
}

/// Refuses a batch whose columns differ from the table's in name or type.
fn require_columns(schema: &Schema, batch: &RecordBatch) -> Result<(), TableHashError> {
    let listed = |fields: &arrow_schema::Fields| {
        let columns = fields
            .iter()
            .map(|field| format!("{} {}", field.name(), field.data_type()));
        columns.collect::<Vec<_>>().join(", ")
    };
    let batch_schema = batch.schema();
    let same = schema.fields().len() == batch_schema.fields().len()
        && schema
            .fields()
            .iter()
            .zip(batch_schema.fields())
            .all(|(one, other)| one.name() == other.name() && one.data_type() == other.data_type());
    if same {
        return Ok(());
    }
    Err(TableHashError::Columns {
        expected: listed(schema.fields()),
        actual: listed(batch_schema.fields()),
    })
}

/// The word a column's type is hashed as: text alike in each of Arrow's three layouts, and a
/// time, an instant, or a duration as Arrow writes its type, its unit and zone with it.
pub(crate) fn type_word(column: &str, data_type: &DataType) -> Result<String, TableHashError> {
    let word = match data_type {
        DataType::Boolean => "boolean",
        DataType::Int8 => "int8",
        DataType::Int16 => "int16",
        DataType::Int32 => "int32",
        DataType::Int64 => "int64",
        DataType::UInt8 => "uint8",
        DataType::UInt16 => "uint16",
        DataType::UInt32 => "uint32",
        DataType::UInt64 => "uint64",
        DataType::Float32 => "float32",
        DataType::Float64 => "float64",
        DataType::Date32 => "date32",
        DataType::Date64 => "date64",
        DataType::Utf8 | DataType::LargeUtf8 | DataType::Utf8View => "utf8",
        DataType::Time32(unit) => return Ok(format!("time32[{}]", unit_word(*unit))),
        DataType::Time64(unit) => return Ok(format!("time64[{}]", unit_word(*unit))),
        DataType::Duration(unit) => return Ok(format!("duration[{}]", unit_word(*unit))),
        DataType::Timestamp(unit, None) => return Ok(format!("timestamp[{}]", unit_word(*unit))),
        DataType::Timestamp(unit, Some(zone)) => {
            return Ok(format!("timestamp[{}, {zone}]", unit_word(*unit)));
        }
        other => return Err(unsupported(column, other)),
    };
    Ok(word.to_owned())
}

/// A unit of time as the hash writes it, its own word rather than Arrow's display of it, which
/// may change between Arrow's versions and change every key with it.
const fn unit_word(unit: TimeUnit) -> &'static str {
    match unit {
        TimeUnit::Second => "s",
        TimeUnit::Millisecond => "ms",
        TimeUnit::Microsecond => "us",
        TimeUnit::Nanosecond => "ns",
    }
}

fn unsupported(column: &str, data_type: &DataType) -> TableHashError {
    TableHashError::Unsupported {
        column: column.to_owned(),
        data_type: data_type.to_string(),
    }
}

/// Each row of `column`: a validity byte, then, where valid, its value.
fn hash_column(
    hasher: &mut blake3::Hasher,
    column: &ArrayRef,
    name: &str,
) -> Result<(), TableHashError> {
    let wrong = || unsupported(name, column.data_type());
    match column.data_type() {
        DataType::Boolean => {
            let flags = column.as_boolean_opt().ok_or_else(wrong)?;
            for row in 0..flags.len() {
                let value = flags.is_valid(row).then(|| [u8::from(flags.value(row))]);
                valued(hasher, value.as_ref().map(<[u8; 1]>::as_slice));
            }
            Ok(())
        }
        DataType::Int8 => primitive::<Int8Type, 1>(hasher, column, i8::to_le_bytes, wrong),
        DataType::Int16 => primitive::<Int16Type, 2>(hasher, column, i16::to_le_bytes, wrong),
        DataType::Int32 => primitive::<Int32Type, 4>(hasher, column, i32::to_le_bytes, wrong),
        DataType::Int64 => primitive::<Int64Type, 8>(hasher, column, i64::to_le_bytes, wrong),
        DataType::UInt8 => primitive::<UInt8Type, 1>(hasher, column, u8::to_le_bytes, wrong),
        DataType::UInt16 => primitive::<UInt16Type, 2>(hasher, column, u16::to_le_bytes, wrong),
        DataType::UInt32 => primitive::<UInt32Type, 4>(hasher, column, u32::to_le_bytes, wrong),
        DataType::UInt64 => primitive::<UInt64Type, 8>(hasher, column, u64::to_le_bytes, wrong),
        DataType::Float32 => primitive::<Float32Type, 4>(hasher, column, f32::to_le_bytes, wrong),
        DataType::Float64 => primitive::<Float64Type, 8>(hasher, column, f64::to_le_bytes, wrong),
        DataType::Date32 => primitive::<Date32Type, 4>(hasher, column, i32::to_le_bytes, wrong),
        DataType::Utf8 => texts(hasher, column.as_string_opt::<i32>().ok_or_else(wrong)?),
        DataType::LargeUtf8 => texts(hasher, column.as_string_opt::<i64>().ok_or_else(wrong)?),
        DataType::Utf8View => {
            let views = column.as_string_view_opt().ok_or_else(wrong)?;
            for row in 0..views.len() {
                let value = views.is_valid(row).then(|| views.value(row));
                framed_value(hasher, value);
            }
            Ok(())
        }
        _ => temporal(hasher, column, wrong),
    }
}

/// A column of times, instants, or durations, each written as its count of its unit.
fn temporal(
    hasher: &mut blake3::Hasher,
    column: &ArrayRef,
    wrong: impl Fn() -> TableHashError,
) -> Result<(), TableHashError> {
    use TimeUnit::{Microsecond, Millisecond, Nanosecond, Second};
    let (four, eight) = (i32::to_le_bytes, i64::to_le_bytes);
    match column.data_type() {
        DataType::Date64 => primitive::<Date64Type, 8>(hasher, column, eight, wrong),
        DataType::Time32(Second) => primitive::<Time32SecondType, 4>(hasher, column, four, wrong),
        DataType::Time32(Millisecond) => {
            primitive::<Time32MillisecondType, 4>(hasher, column, four, wrong)
        }
        DataType::Time64(Microsecond) => {
            primitive::<Time64MicrosecondType, 8>(hasher, column, eight, wrong)
        }
        DataType::Time64(Nanosecond) => {
            primitive::<Time64NanosecondType, 8>(hasher, column, eight, wrong)
        }
        DataType::Timestamp(Second, _) => {
            primitive::<TimestampSecondType, 8>(hasher, column, eight, wrong)
        }
        DataType::Timestamp(Millisecond, _) => {
            primitive::<TimestampMillisecondType, 8>(hasher, column, eight, wrong)
        }
        DataType::Timestamp(Microsecond, _) => {
            primitive::<TimestampMicrosecondType, 8>(hasher, column, eight, wrong)
        }
        DataType::Timestamp(Nanosecond, _) => {
            primitive::<TimestampNanosecondType, 8>(hasher, column, eight, wrong)
        }
        DataType::Duration(Second) => {
            primitive::<DurationSecondType, 8>(hasher, column, eight, wrong)
        }
        DataType::Duration(Millisecond) => {
            primitive::<DurationMillisecondType, 8>(hasher, column, eight, wrong)
        }
        DataType::Duration(Microsecond) => {
            primitive::<DurationMicrosecondType, 8>(hasher, column, eight, wrong)
        }
        DataType::Duration(Nanosecond) => {
            primitive::<DurationNanosecondType, 8>(hasher, column, eight, wrong)
        }
        _ => Err(wrong()),
    }
}

/// A column of primitive values, each written as its `N` little-endian bytes.
fn primitive<T: ArrowPrimitiveType, const N: usize>(
    hasher: &mut blake3::Hasher,
    column: &ArrayRef,
    bytes: fn(T::Native) -> [u8; N],
    wrong: impl Fn() -> TableHashError,
) -> Result<(), TableHashError> {
    let values: &PrimitiveArray<T> = column.as_primitive_opt::<T>().ok_or_else(wrong)?;
    for row in 0..values.len() {
        let value = values.is_valid(row).then(|| bytes(values.value(row)));
        valued(hasher, value.as_ref().map(<[u8; N]>::as_slice));
    }
    Ok(())
}

fn texts<O: arrow_array::OffsetSizeTrait>(
    hasher: &mut blake3::Hasher,
    column: &arrow_array::GenericStringArray<O>,
) -> Result<(), TableHashError> {
    for row in 0..column.len() {
        let value = column.is_valid(row).then(|| column.value(row));
        framed_value(hasher, value);
    }
    Ok(())
}

/// A row's validity, then its value's bytes where it has one.
fn valued(hasher: &mut blake3::Hasher, value: Option<&[u8]>) {
    match value {
        Some(bytes) => {
            hasher.update(&[1]);
            hasher.update(bytes);
        }
        None => {
            hasher.update(&[0]);
        }
    }
}

/// A row's validity, then its text framed by its length where it has one.
fn framed_value(hasher: &mut blake3::Hasher, value: Option<&str>) {
    match value {
        Some(text) => {
            hasher.update(&[1]);
            framed(hasher, text.as_bytes());
        }
        None => {
            hasher.update(&[0]);
        }
    }
}

fn framed(hasher: &mut blake3::Hasher, part: &[u8]) {
    hasher.update(&(part.len() as u64).to_le_bytes());
    hasher.update(part);
}
