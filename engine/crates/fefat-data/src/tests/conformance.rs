//! Step 2.5's Done means 4: the mapped cache of the sample tape passes the conformance checks of
//! step 2.4 unchanged, serves its columns from the mapped files, and says which levels each
//! trade date holds.

use fefat_core::fidelity::{Fidelity, Timeframe};
use fefat_core::instants::TradeDate;
use fefat_core::market_data::conformance::{
    FIRST_DAY, SAMPLE_CONTRACT, SECOND_DAY, check_offsets, check_sample_tape, sample_tape,
};
use fefat_core::market_data::{MarketDataError, MarketDataReader};

use super::{TemporaryFolder, cached, moved, write_month};
use crate::MappedContract;

#[test]
fn the_mapped_cache_of_the_sample_tape_passes_the_conformance_checks() {
    let folder = TemporaryFolder::new();

    let reader = cached(folder.path(), SAMPLE_CONTRACT, sample_tape()).unwrap();

    assert_eq!(check_sample_tape(&reader), Ok(()));
    assert_eq!(check_offsets(&reader), Ok(()));
}

#[test]
fn the_index_lists_each_trade_date_with_its_levels_and_the_files_of_the_month() {
    let folder = TemporaryFolder::new();

    let index = write_month(folder.path(), SAMPLE_CONTRACT, sample_tape()).unwrap();

    let listed: Vec<(&str, Vec<&str>)> = index
        .trade_dates
        .iter()
        .map(|day| {
            let levels = day.levels.iter().map(String::as_str).collect();
            (day.trade_date.as_str(), levels)
        })
        .collect();
    assert_eq!(
        listed,
        [
            ("2026-03-05", vec!["tbbo", "trades", "1s", "1m"]),
            ("2026-03-06", vec!["5m"])
        ]
    );
    let files: Vec<&str> = index.files.keys().map(String::as_str).collect();
    assert_eq!(
        files,
        [
            "1m-to-1s.arrow",
            "1m-to-tbbo.arrow",
            "1m-to-trades.arrow",
            "1m.arrow",
            "1s-to-tbbo.arrow",
            "1s-to-trades.arrow",
            "1s.arrow",
            "5m.arrow",
            "tbbo.arrow",
            "trades.arrow"
        ]
    );
    assert_eq!(index.files["trades.arrow"].rows, 6);
    assert_eq!(index.files["1m-to-trades.arrow"].rows, 3);
    assert_eq!(
        (index.contract.as_str(), index.month.as_str()),
        (SAMPLE_CONTRACT, "2026-03")
    );
    assert!(
        index
            .trade_dates
            .iter()
            .all(|day| day.cut.is_empty() && day.left_out.is_empty())
    );
}

#[test]
fn a_trade_date_without_ticks_lists_the_levels_it_holds_and_refuses_its_ticks() {
    let folder = TemporaryFolder::new();
    let mut without_ticks = moved(&sample_tape()[0], 4);
    without_ticks.tbbo.clear();
    without_ticks.trades.clear();
    let mut days = sample_tape();
    days.push(without_ticks);
    let monday = TradeDate(FIRST_DAY.0 + 4);

    let index = write_month(folder.path(), SAMPLE_CONTRACT, days).unwrap();
    let reader = MappedContract::open(&folder.path().join(SAMPLE_CONTRACT)).unwrap();

    let seconds_and_minutes = [
        Fidelity::Bars(Timeframe::ONE_SECOND),
        Fidelity::Bars(Timeframe::ONE_MINUTE),
    ];
    assert_eq!(reader.levels(monday).unwrap(), seconds_and_minutes);
    assert_eq!(index.trade_dates[2].levels, ["1s", "1m"]);
    assert!(matches!(
        reader.trades(monday),
        Err(MarketDataError::LevelMissing {
            level: Fidelity::Trades,
            ..
        })
    ));
    let descent = reader.offsets(monday, Timeframe::ONE_MINUTE, Fidelity::Trades);
    assert_eq!(
        descent.unwrap_err().to_string(),
        "Expected trades data of ESH2026 on 2026-03-09, which holds 1s, 1m"
    );
    assert_eq!(reader.trades(FIRST_DAY).unwrap().ts_recv.len(), 6);
    assert_eq!(check_offsets(&reader), Ok(()));
}

#[test]
fn the_reader_serves_its_columns_from_the_mapped_files() {
    let folder = TemporaryFolder::new();

    let reader = cached(folder.path(), SAMPLE_CONTRACT, sample_tape()).unwrap();

    let trades = reader.trades(FIRST_DAY).unwrap();
    let tbbo = reader.tbbo(FIRST_DAY).unwrap();
    let minutes = reader.bars(FIRST_DAY, Timeframe::ONE_MINUTE).unwrap();
    let five_minutes = reader.bars(SECOND_DAY, Timeframe::FIVE_MINUTES).unwrap();
    let descent = reader.offsets(FIRST_DAY, Timeframe::ONE_MINUTE, Fidelity::Trades);
    let addresses = [
        trades.ts_recv.as_ptr().addr(),
        trades.size.as_ptr().addr(),
        tbbo.ask_size.as_ptr().addr(),
        minutes.close.as_ptr().addr(),
        five_minutes.volume.as_ptr().addr(),
        descent.unwrap().as_ptr().addr(),
    ];
    assert!(
        addresses.iter().all(|address| reader.maps_hold(*address)),
        "{addresses:?}"
    );
}

#[test]
fn a_contract_of_two_months_reads_as_one_in_date_order() {
    let folder = TemporaryFolder::new();
    let april = moved(&sample_tape()[0], 28);
    write_month(folder.path(), SAMPLE_CONTRACT, sample_tape()).unwrap();
    write_month(folder.path(), SAMPLE_CONTRACT, vec![april]).unwrap();

    let reader = MappedContract::open(&folder.path().join(SAMPLE_CONTRACT)).unwrap();

    let april_2 = TradeDate(FIRST_DAY.0 + 28);
    assert_eq!(reader.trade_dates(), [FIRST_DAY, SECOND_DAY, april_2]);
    assert_eq!(april_2.to_string(), "2026-04-02");
    assert_eq!(check_offsets(&reader), Ok(()));
    assert!(matches!(
        reader.levels(TradeDate(FIRST_DAY.0 + 1_000)),
        Err(MarketDataError::UnknownTradeDate { first, last, .. }) if first == FIRST_DAY && last == april_2
    ));
}
