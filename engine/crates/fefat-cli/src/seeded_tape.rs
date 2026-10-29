//! A tape generated from a seed in integer arithmetic alone, so that Windows and Linux build the
//! same records (the amendments of steps 2.4 and 2.7): one trade date of ES-like trades, each a
//! tick from the one before or at its price, as TBBO records and as trades, with their 1-second
//! and 1-minute bars.

use std::collections::BTreeMap;

use fefat_core::fidelity::Timeframe;
use fefat_core::instants::{NANOSECONDS_PER_SECOND, TradeDate, Ts};
use fefat_core::market_data::{BarRow, TapeDay, TbboRow, TradeRow};
use fefat_core::units::{PRICE_UNITS, Price, Qty};

/// The contract the seeded tape is labelled with.
pub const SEEDED_CONTRACT: &str = "ESH2026";
/// 2026-03-05, the seeded tape's trade date.
pub const SEEDED_TRADE_DATE: TradeDate = TradeDate(20_517);
/// ES's tick, 0.25, in 1e-9 units.
pub const TICK: i64 = 250_000_000;

const TRADES: usize = 2_000;
/// 2026-03-05T14:30:00Z, when the seeded tape starts.
pub(crate) const FIRST_SECOND: i64 = 1_772_721_000 * NANOSECONDS_PER_SECOND;

/// SplitMix64 (Steele, Lea, and Flood, 2014): a small generator whose sequence the seed alone
/// decides, the same on every platform.
pub struct SplitMix64(u64);

impl SplitMix64 {
    /// The generator of `seed`.
    pub const fn new(seed: u64) -> Self {
        Self(seed)
    }

    fn next_u64(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut mixed = self.0;
        mixed = (mixed ^ (mixed >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        mixed = (mixed ^ (mixed >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        mixed ^ (mixed >> 31)
    }

    /// A whole number from 0 to `count - 1`; `count` is a constant above zero.
    pub fn below(&mut self, count: u32) -> i64 {
        i64::from(self.below_u32(count))
    }

    /// [`Self::below`] as the `u32` it draws.
    pub fn below_u32(&mut self, count: u32) -> u32 {
        (self.next_u64() >> 32) as u32 % count
    }
}

/// The seeded tape: 2,000 trades from 14:30 UTC, 1 to 900 ms apart, of 1 to 10 lots, walking
/// from 5000.00 a tick down, none, or a tick up at a time, each at the ask when a buyer took it
/// and at the bid when a seller did, with their 1-second and 1-minute bars.
pub fn seeded_tape(generator: &mut SplitMix64) -> Vec<TapeDay> {
    let mut trades = Vec::with_capacity(TRADES);
    let mut tbbo = Vec::with_capacity(TRADES);
    let (mut ts_recv, mut price) = (FIRST_SECOND, 5_000 * PRICE_UNITS);
    for _ in 0..TRADES {
        ts_recv += (1 + generator.below(900)) * 1_000_000;
        price += (generator.below(3) - 1) * TICK;
        let trade = TradeRow {
            ts_recv: Ts(ts_recv),
            price: Price(price),
            size: Qty(1 + generator.below(10)),
        };
        tbbo.push(quoted(trade, generator));
        trades.push(trade);
    }
    let bars = BTreeMap::from([
        (
            Timeframe::ONE_SECOND,
            bars_of(&trades, NANOSECONDS_PER_SECOND),
        ),
        (
            Timeframe::ONE_MINUTE,
            bars_of(&trades, 60 * NANOSECONDS_PER_SECOND),
        ),
    ]);
    vec![TapeDay {
        trade_date: SEEDED_TRADE_DATE,
        tbbo,
        trades,
        bars,
    }]
}

fn quoted(trade: TradeRow, generator: &mut SplitMix64) -> TbboRow {
    let bought = generator.below(2) == 1;
    let bid = if bought {
        trade.price.0 - TICK
    } else {
        trade.price.0
    };
    TbboRow {
        ts_recv: trade.ts_recv,
        price: trade.price,
        size: trade.size,
        bid: Price(bid),
        ask: Price(bid + TICK),
        bid_size: Qty(1 + generator.below(20)),
        ask_size: Qty(1 + generator.below(20)),
    }
}

/// The trades' bars of `length` nanoseconds, each opening on a multiple of its length, one for
/// every bucket that holds a trade.
fn bars_of(trades: &[TradeRow], length: i64) -> Vec<BarRow> {
    let mut bars: Vec<BarRow> = Vec::new();
    for trade in trades {
        let ts_open = Ts(trade.ts_recv.0 - trade.ts_recv.0.rem_euclid(length));
        match bars.last_mut() {
            Some(bar) if bar.ts_open == ts_open => {
                bar.high = bar.high.max(trade.price);
                bar.low = bar.low.min(trade.price);
                bar.close = trade.price;
                bar.volume = Qty(bar.volume.0 + trade.size.0);
            }
            _ => bars.push(BarRow {
                ts_open,
                ts_close: Ts(ts_open.0 + length),
                open: trade.price,
                high: trade.price,
                low: trade.price,
                close: trade.price,
                volume: trade.size,
            }),
        }
    }
    bars
}
