//! What the writer and the reader refuse, each with what they expected, what they got, and where.

use std::fs;

use fefat_core::fidelity::{Fidelity, Timeframe};
use fefat_core::instrument::Contract;
use fefat_core::market_data::conformance::{SAMPLE_CONTRACT, sample_tape};

use super::{TemporaryFolder, moved, sources, write_month};
use crate::{CacheMonthIndex, CacheMonthWriter, INDEX_FILE_NAME, MappedContract, Month};

fn march() -> Month {
    "2026-03".parse().unwrap()
}

fn writer(folder: &TemporaryFolder) -> CacheMonthWriter {
    let contract_folder = folder.path().join(SAMPLE_CONTRACT);
    let contract = Contract(SAMPLE_CONTRACT.into());
    CacheMonthWriter::create(&contract_folder, contract, march(), sources()).unwrap()
}

#[test]
fn a_trade_date_of_another_month_is_refused() {
    let folder = TemporaryFolder::new();
    let april = moved(&sample_tape()[0], 28);

    let refused = writer(&folder).write_trade_date(april).unwrap_err();

    assert_eq!(
        refused.to_string(),
        "Expected a trade date of 2026-03, got 2026-04-02 in the cache of ESH2026 for 2026-03"
    );
}

#[test]
fn a_trade_date_out_of_order_or_written_twice_is_refused() {
    let folder = TemporaryFolder::new();
    let mut writer = writer(&folder);
    let [first, second] = <[_; 2]>::try_from(sample_tape()).unwrap();
    writer.write_trade_date(second.clone()).unwrap();

    let earlier = writer.write_trade_date(first).unwrap_err();
    let again = writer.write_trade_date(second).unwrap_err();

    let expected = "Expected a trade date after 2026-03-06, got";
    assert!(
        earlier
            .to_string()
            .starts_with(&format!("{expected} 2026-03-05"))
    );
    assert!(
        again
            .to_string()
            .starts_with(&format!("{expected} 2026-03-06"))
    );
}

#[test]
fn a_month_already_cached_is_refused_and_left_as_it_was() {
    let folder = TemporaryFolder::new();
    let index = write_month(folder.path(), SAMPLE_CONTRACT, sample_tape()).unwrap();
    let contract_folder = folder.path().join(SAMPLE_CONTRACT);

    let contract = Contract(SAMPLE_CONTRACT.into());
    let refused = CacheMonthWriter::create(&contract_folder, contract, march(), sources());

    let message = refused.err().unwrap().to_string();
    assert!(
        message.starts_with("Expected no such folder, got "),
        "{message}"
    );
    assert!(
        message.ends_with("2026-03 already there in a new cache month"),
        "{message}"
    );
    let month_folder = contract_folder.join("2026-03");
    assert_eq!(CacheMonthIndex::read(&month_folder).unwrap(), Some(index));
}

#[test]
fn an_abandoned_month_leaves_no_folder_behind() {
    let folder = TemporaryFolder::new();
    let mut writer = writer(&folder);
    writer.write_trade_date(sample_tape().remove(0)).unwrap();

    writer.abandon().unwrap();

    let contract_folder = folder.path().join(SAMPLE_CONTRACT);
    assert_eq!(fs::read_dir(contract_folder).unwrap().count(), 0);
}

#[test]
fn a_month_without_trade_dates_is_refused() {
    let folder = TemporaryFolder::new();

    let refused = writer(&folder).finish().unwrap_err();

    assert_eq!(
        refused.to_string(),
        "Expected a trade date or more, got none in the cache of ESH2026 for 2026-03"
    );
}

#[test]
fn a_month_being_built_is_passed_over_and_anything_else_is_refused() {
    let folder = TemporaryFolder::new();
    write_month(folder.path(), SAMPLE_CONTRACT, sample_tape()).unwrap();
    let contract_folder = folder.path().join(SAMPLE_CONTRACT);
    fs::create_dir(contract_folder.join("2026-04.partial")).unwrap();

    let opened = MappedContract::open(&contract_folder).unwrap();
    fs::write(contract_folder.join("notes.txt"), "a note").unwrap();
    let refused = MappedContract::open(&contract_folder).unwrap_err();

    assert_eq!(
        format!("{opened:?}").split(',').next(),
        Some("MappedContract { contract: \"ESH2026\"")
    );
    assert_eq!(
        refused.to_string(),
        "Expected a month written YYYY-MM, such as 2026-03, got \"notes.txt\" in the name of a \
         cache month"
    );
}

#[test]
fn a_month_without_its_index_or_of_another_layout_or_contract_is_refused() {
    let folder = TemporaryFolder::new();
    write_month(folder.path(), SAMPLE_CONTRACT, sample_tape()).unwrap();
    let contract_folder = folder.path().join(SAMPLE_CONTRACT);
    let month_folder = contract_folder.join("2026-03");
    let index = CacheMonthIndex::read(&month_folder).unwrap().unwrap();
    let refusal = || {
        MappedContract::open(&contract_folder)
            .unwrap_err()
            .to_string()
    };

    CacheMonthIndex {
        layout_version: 2,
        ..index.clone()
    }
    .write(&month_folder)
    .unwrap();
    let other_layout = refusal();
    CacheMonthIndex {
        contract: "ESM2026".into(),
        ..index.clone()
    }
    .write(&month_folder)
    .unwrap();
    let other_contract = refusal();
    fs::remove_file(month_folder.join(INDEX_FILE_NAME)).unwrap();
    let without_an_index = refusal();

    assert!(
        other_layout.starts_with("Expected layout version 1; rebuild the month, got version 2")
    );
    assert!(other_contract.starts_with("Expected the cache of ESH2026, got ESM2026"));
    assert!(without_an_index.starts_with("Expected the month's index.json, got none"));
}

#[test]
fn a_month_missing_a_file_or_a_batch_is_refused() {
    let folder = TemporaryFolder::new();
    write_month(folder.path(), SAMPLE_CONTRACT, sample_tape()).unwrap();
    let contract_folder = folder.path().join(SAMPLE_CONTRACT);
    let month_folder = contract_folder.join("2026-03");
    let mut index = CacheMonthIndex::read(&month_folder).unwrap().unwrap();
    let refusal = || {
        MappedContract::open(&contract_folder)
            .unwrap_err()
            .to_string()
    };

    let seconds = Fidelity::Bars(Timeframe::ONE_SECOND);
    index.trade_dates[1].levels = vec![seconds, Fidelity::Bars(Timeframe::FIVE_MINUTES)];
    index.write(&month_folder).unwrap();
    let without_a_batch = refusal();
    fs::remove_file(month_folder.join("trades.arrow")).unwrap();
    let without_a_file = refusal();

    assert!(
        without_a_batch.starts_with("Expected a batch of 2026-03-06 in 1s.arrow, got none"),
        "{without_a_batch}"
    );
    assert!(
        without_a_file.starts_with("Expected to open "),
        "{without_a_file}"
    );
    assert!(without_a_file.contains("trades.arrow"), "{without_a_file}");
}

#[test]
fn a_month_folder_that_names_no_month_is_refused() {
    for text in ["2026-3", "2026-13", "26-03", "2026-03-01", "march"] {
        let refused = text.parse::<Month>().unwrap_err().to_string();
        assert!(
            refused.starts_with("Expected a month written YYYY-MM"),
            "{text}: {refused}"
        );
    }
    assert_eq!(march().to_string(), "2026-03");
}

#[test]
fn a_month_refused_as_it_is_finished_leaves_no_partial_folder() {
    let folder = TemporaryFolder::new();
    let mut writer = writer(&folder);
    writer.write_trade_date(sample_tape().remove(0)).unwrap();
    let contract_folder = folder.path().join(SAMPLE_CONTRACT);
    fs::create_dir(contract_folder.join("2026-03")).unwrap();
    fs::write(contract_folder.join("2026-03").join("kept.txt"), "a note").unwrap();

    let refused = writer.finish().unwrap_err();

    assert!(
        refused.to_string().starts_with("Expected to rename "),
        "{refused}"
    );
    let names: Vec<_> = fs::read_dir(&contract_folder)
        .unwrap()
        .map(|entry| entry.unwrap().file_name())
        .collect();
    assert_eq!(names, ["2026-03"]);
}
