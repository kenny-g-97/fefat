//! The cache's files mapped into memory and read in place (`02` §1.6, D-56): the engine's only
//! `unsafe`, two blocks, one that maps a file and one that reads its `i64` columns as the
//! newtypes they hold.

#![allow(unsafe_code)]

use std::fs::File;
use std::mem::{align_of, size_of};
use std::path::Path;
use std::slice;
use std::sync::Arc;

use arrow_array::RecordBatch;
use arrow_buffer::Buffer;
use arrow_ipc::convert::fb_to_schema;
use arrow_ipc::reader::{FileDecoder, read_footer_length};
use arrow_ipc::{Block, root_as_footer};
use bytes::Bytes;
use fefat_core::instants::Ts;
use fefat_core::units::{Price, Qty};
use memmap2::Mmap;

use crate::error::{CacheError, arrow_error, io_error};

/// The bytes of an Arrow IPC file's trailer: the footer's length, then `ARROW1`.
const TRAILER_BYTES: usize = 10;

/// An Arrow IPC file of the cache, mapped into memory, with the batches read in place from it.
pub(crate) struct MappedFile {
    /// The mapped bytes, which every batch's columns point into.
    pub(crate) bytes: Buffer,
    /// The file's batches, in order.
    pub(crate) batches: Vec<RecordBatch>,
}

impl MappedFile {
    /// Maps the file and reads its batches without copying them: a column whose bytes are not
    /// aligned in the file is refused rather than copied.
    pub(crate) fn open(path: &Path) -> Result<Self, CacheError> {
        let file = File::open(path).map_err(io_error("open", path))?;
        // SAFETY: a cache file is written once, into a month folder named `<month>.partial` that
        // takes its month's name only after every file is closed (`CacheMonthWriter::finish`),
        // and no code writes it again: a rebuild removes the month folder and writes new files.
        // Windows refuses to delete or truncate a mapped file, and elsewhere removing a file
        // leaves its pages mapped, so only a file changed in place by hand while it is mapped
        // could change these bytes.
        let map = unsafe { Mmap::map(&file) }.map_err(io_error("map", path))?;
        let bytes = Buffer::from(Bytes::from_owner(map));
        let batches = decoded_batches(path, &bytes)?;
        Ok(Self { bytes, batches })
    }
}

fn decoded_batches(path: &Path, bytes: &Buffer) -> Result<Vec<RecordBatch>, CacheError> {
    let unreadable = |what: &str| {
        let context = path.display().to_string();
        CacheError::refused("an Arrow IPC file", what, context)
    };
    let trailer_start = bytes
        .len()
        .checked_sub(TRAILER_BYTES)
        .ok_or_else(|| unreadable("a file shorter than its trailer"))?;
    let trailer: [u8; TRAILER_BYTES] = bytes
        .get(trailer_start..)
        .and_then(|trailer| trailer.try_into().ok())
        .ok_or_else(|| unreadable("no trailer"))?;
    let footer_length = read_footer_length(trailer).map_err(arrow_error(path))?;
    let footer = trailer_start
        .checked_sub(footer_length)
        .and_then(|footer_start| bytes.get(footer_start..trailer_start))
        .ok_or_else(|| unreadable("a footer longer than the file"))?;
    let footer = root_as_footer(footer).map_err(|error| unreadable(&error.to_string()))?;
    if footer
        .dictionaries()
        .is_some_and(|blocks| !blocks.is_empty())
    {
        return Err(unreadable("dictionaries, which no cache file holds"));
    }
    let schema = footer
        .schema()
        .ok_or_else(|| unreadable("a footer without a schema"))?;
    let decoder = FileDecoder::new(Arc::new(fb_to_schema(schema)), footer.version())
        .with_require_alignment(true);
    let blocks = footer
        .recordBatches()
        .ok_or_else(|| unreadable("no batches"))?;
    blocks
        .iter()
        .map(|block| {
            let block_bytes =
                block_bytes(bytes, block).ok_or_else(|| unreadable("a block outside the file"))?;
            let batch = decoder.read_record_batch(block, &block_bytes);
            batch
                .map_err(arrow_error(path))?
                .ok_or_else(|| unreadable("a block without a batch"))
        })
        .collect()
}

/// The bytes of one block, its message and its body, as the decoder reads them: a slice of the
/// mapped file, never a copy.
fn block_bytes(bytes: &Buffer, block: &Block) -> Option<Buffer> {
    let start = usize::try_from(block.offset()).ok()?;
    let message = usize::try_from(block.metaDataLength()).ok()?;
    let body = usize::try_from(block.bodyLength()).ok()?;
    let length = message.checked_add(body)?;
    let inside = start.checked_add(length)? <= bytes.len();
    inside.then(|| bytes.slice_with_length(start, length))
}

/// A newtype of `fefat-core` that is `#[repr(transparent)]` over `i64` (D-55).
pub(crate) trait OverI64: Copy {}

impl OverI64 for Ts {}
impl OverI64 for Price {}
impl OverI64 for Qty {}

const _: () = assert!(size_of::<Ts>() == size_of::<i64>() && align_of::<Ts>() == align_of::<i64>());
const _: () =
    assert!(size_of::<Price>() == size_of::<i64>() && align_of::<Price>() == align_of::<i64>());
const _: () =
    assert!(size_of::<Qty>() == size_of::<i64>() && align_of::<Qty>() == align_of::<i64>());

/// A column of `i64` read as the newtype it holds, in place.
pub(crate) fn as_newtypes<T: OverI64>(values: &[i64]) -> &[T] {
    // SAFETY: `T` is `Ts`, `Price`, or `Qty`, the only implementations of the crate's private
    // trait, each `#[repr(transparent)]` over `i64` (D-55) and asserted above to share its size
    // and alignment, so the same bytes are a valid `[T]` of the same length, borrowed for no
    // longer than `values`.
    unsafe { slice::from_raw_parts(values.as_ptr().cast::<T>(), values.len()) }
}
