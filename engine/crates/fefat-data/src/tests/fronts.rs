//! Step 2.10 (BACKLOG's cache reader across rolls): a run's trade dates served from its fronts'
//! caches, each from the cache of the front that trades it, the window's first from the first
//! front and each roll's from its new front, and the windows and fronts refused.

use fefat_core::fidelity::Timeframe;
use fefat_core::instants::TradeDate;
use fefat_core::instrument::Contract;
use fefat_core::market_data::conformance::{
    FIRST_DAY, SAMPLE_CONTRACT, SECOND_DAY, check_offsets, sample_tape,
};
use fefat_core::market_data::{MarketDataError, MarketDataReader, TapeDay};
use fefat_core::units::Price;

use super::{TemporaryFolder, cached, moved, write_month};
use crate::{CacheError, CacheMonthIndex, FrontSequence, MappedContract, Month};

const NEW_FRONT: &str = "ESM2026";
/// 20.00 in 1e-9 units, by which the new front trades above the old.
const GAP: i64 = 20_000_000_000;

/// `day` with every price `GAP` higher, as the next contract trades.
fn higher(day: &TapeDay) -> TapeDay {
    let up = |price: &mut Price| price.0 += GAP;
    let mut moved = day.clone();
    moved.trades.iter_mut().for_each(|row| up(&mut row.price));
    for row in &mut moved.tbbo {
        for price in [&mut row.price, &mut row.bid, &mut row.ask] {
            up(price);
        }
    }
    for bar in moved.bars.values_mut().flatten() {
        for price in [&mut bar.open, &mut bar.high, &mut bar.low, &mut bar.close] {
            up(price);
        }
    }
    moved
}

/// The sample tape's caches of the old front and of the new one, its prices `GAP` higher.
fn old_and_new(folder: &TemporaryFolder) -> (MappedContract, MappedContract) {
    let old = cached(folder.path(), SAMPLE_CONTRACT, sample_tape()).unwrap();
    let days = sample_tape().iter().map(higher).collect();
    let new = cached(folder.path(), NEW_FRONT, days).unwrap();
    (old, new)
}

fn roll_on(trade_date: TradeDate) -> [(TradeDate, Contract); 1] {
    [(trade_date, Contract(NEW_FRONT.to_owned()))]
}

#[test]
fn each_trade_date_comes_from_the_cache_of_its_front() {
    let folder = TemporaryFolder::new();
    let (old, new) = old_and_new(&folder);

    let fronts = FrontSequence::new(&[&old, &new], &roll_on(SECOND_DAY), FIRST_DAY, SECOND_DAY);

    let fronts = fronts.unwrap();
    assert_eq!(fronts.contract().0, SAMPLE_CONTRACT);
    assert_eq!(fronts.trade_dates(), [FIRST_DAY, SECOND_DAY]);
    let traded = fronts.trades(FIRST_DAY).unwrap().price;
    assert_eq!(traded, old.trades(FIRST_DAY).unwrap().price);
    let five = Timeframe::FIVE_MINUTES;
    let closes = fronts.bars(SECOND_DAY, five).unwrap().close;
    assert_eq!(closes, new.bars(SECOND_DAY, five).unwrap().close);
    assert_ne!(closes, old.bars(SECOND_DAY, five).unwrap().close);
    assert_eq!(check_offsets(&fronts), Ok(()));
}

#[test]
fn a_window_reads_only_its_own_trade_dates() {
    let folder = TemporaryFolder::new();
    let (old, _) = old_and_new(&folder);

    let fronts = FrontSequence::new(&[&old], &[], SECOND_DAY, SECOND_DAY).unwrap();

    assert_eq!(fronts.trade_dates(), [SECOND_DAY]);
    assert!(matches!(
        fronts.levels(FIRST_DAY),
        Err(MarketDataError::UnknownTradeDate { trade_date, .. }) if trade_date == FIRST_DAY
    ));
}

#[test]
fn a_front_of_another_contract_than_its_roll_names_is_refused() {
    let folder = TemporaryFolder::new();
    let (old, _) = old_and_new(&folder);

    let refused = FrontSequence::new(&[&old, &old], &roll_on(SECOND_DAY), FIRST_DAY, SECOND_DAY);

    let refused = refused.unwrap_err().to_string();
    assert!(
        refused.contains("Expected the cache of ESM2026 from 2026-03-06, got ESH2026"),
        "{refused}"
    );
}

#[test]
fn rolls_out_of_the_window_or_without_their_fronts_are_refused() {
    let folder = TemporaryFolder::new();
    let (old, new) = old_and_new(&folder);
    let (first, second) = (FIRST_DAY, SECOND_DAY);

    let at_the_first = FrontSequence::new(&[&old, &new], &roll_on(first), first, second);
    let one_front_short = FrontSequence::new(&[&old], &roll_on(second), first, second);

    for refused in [at_the_first, one_front_short] {
        assert!(
            matches!(refused, Err(CacheError::Refused { .. })),
            "{refused:?}"
        );
    }
}

#[test]
fn a_window_without_a_cached_trade_date_is_refused() {
    let folder = TemporaryFolder::new();
    let (old, _) = old_and_new(&folder);
    let later = TradeDate(SECOND_DAY.0 + 7);

    let refused = FrontSequence::new(&[&old], &[], later, later)
        .unwrap_err()
        .to_string();

    assert!(
        refused.contains("in the fronts' caches, got none"),
        "{refused}"
    );
}

#[test]
fn the_fronts_can_be_shared_by_the_threads_of_a_batch() {
    fn shared<Reader: MarketDataReader + Send + Sync>(_: &Reader) {}
    let folder = TemporaryFolder::new();
    let (old, new) = old_and_new(&folder);

    let fronts = FrontSequence::new(&[&old, &new], &roll_on(SECOND_DAY), FIRST_DAY, SECOND_DAY);

    shared(&fronts.unwrap());
}

#[test]
fn a_run_maps_the_months_it_reads_and_not_a_month_of_another_layout() {
    // Step 2.10: a contract's folder keeps months built before, maybe at an older layout, which a
    // run of other months must not need to read.
    let folder = TemporaryFolder::new();
    write_month(folder.path(), SAMPLE_CONTRACT, sample_tape()).unwrap();
    write_month(folder.path(), SAMPLE_CONTRACT, vec![moved(&sample_tape()[0], 28)]).unwrap();
    let contract_folder = folder.path().join(SAMPLE_CONTRACT);
    let april_folder = contract_folder.join("2026-04");
    let april = CacheMonthIndex::read(&april_folder).unwrap().unwrap();
    CacheMonthIndex {
        layout_version: 1,
        ..april
    }
    .write(&april_folder)
    .unwrap();
    let march = Month::of(FIRST_DAY);

    let whole = MappedContract::open(&contract_folder);
    let only_march = MappedContract::open_between(&contract_folder, march, march).unwrap();

    assert!(whole.unwrap_err().to_string().contains("layout"));
    assert_eq!(only_march.trade_dates(), [FIRST_DAY, SECOND_DAY]);
}
