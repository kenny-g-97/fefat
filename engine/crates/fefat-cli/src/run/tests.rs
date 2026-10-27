//! A batch of four cases through `run_batch`: S-fill-012 from the batch's trades file and again
//! from an engine cache of the same records, S-fill-036 from its TBBO file, and S-template-002
//! from its signal rows, each case's fills, orders, and log tagged with its place in `run.json`.

use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process;
use std::sync::Arc;

use arrow_array::cast::AsArray;
use arrow_array::types::{Int64Type, UInt64Type};
use arrow_array::{Array, ArrayRef, BooleanArray, Float64Array, Int64Array, RecordBatch};
use arrow_ipc::reader::FileReader;
use arrow_ipc::writer::FileWriter;
use arrow_schema::{Field, Schema};
use fefat_core::instants::{TradeDate, Ts};
use fefat_core::instrument::Contract;
use fefat_core::market_data::{TapeDay, TradeRow};
use fefat_core::units::{Price, Qty};
use fefat_data::{CacheMonthWriter, Month, SourceFile};
use serde_json::json;

use super::run_batch;

/// 2026-03-06T14:30:00Z.
const HALF_PAST_TWO: i64 = 1_772_807_400 * 1_000_000_000;
const TRADE_DATE: i64 = 20_518;
/// S-fill-012's trades: (milliseconds after 14:30, price in hundredths, size).
const GAP_THROUGH_A_STOP: [(i64, i64, i64); 4] = [
    (200, 499_600, 2),
    (450, 499_550, 1),
    (1_250, 499_025, 6),
    (1_400, 499_075, 3),
];

/// A TBBO record: milliseconds after 14:30, price, size, bid, and ask in hundredths, bid and
/// ask sizes.
type QuotedTrade = (i64, i64, i64, i64, i64, i64, i64);

/// A folder of its own under the system's temporary folder, removed when dropped.
struct TemporaryFolder(PathBuf);

impl TemporaryFolder {
    fn new(name: &str) -> Self {
        let path = env::temp_dir().join(format!("fefat-cli-{name}-{}", process::id()));
        let _ = fs::remove_dir_all(&path);
        fs::create_dir_all(&path).unwrap();
        Self(path)
    }
}

impl Drop for TemporaryFolder {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn at(milliseconds: i64) -> i64 {
    HALF_PAST_TWO + milliseconds * 1_000_000
}

fn price(hundredths: i64) -> i64 {
    hundredths * 10_000_000
}

fn int64(values: Vec<i64>) -> ArrayRef {
    Arc::new(Int64Array::from(values))
}

fn write_table(path: &Path, columns: Vec<(&str, ArrayRef)>) {
    let fields: Vec<Field> = columns
        .iter()
        .map(|(name, column)| Field::new(*name, column.data_type().clone(), true))
        .collect();
    let schema = Arc::new(Schema::new(fields));
    let arrays = columns.into_iter().map(|(_, column)| column).collect();
    let batch = RecordBatch::try_new(Arc::clone(&schema), arrays).unwrap();
    let mut writer = FileWriter::try_new(fs::File::create(path).unwrap(), &schema).unwrap();
    writer.write(&batch).unwrap();
    writer.finish().unwrap();
}

fn read_table(path: &Path) -> RecordBatch {
    let reader = FileReader::try_new(fs::File::open(path).unwrap(), None).unwrap();
    let mut batches: Vec<RecordBatch> = reader.collect::<Result<_, _>>().unwrap();
    assert_eq!(batches.len(), 1, "one batch in {}", path.display());
    batches.remove(0)
}

fn trades_file(input: &Path) {
    let template = [
        (300_200, 500_000, 3),
        (301_000, 500_150, 1),
        (302_000, 500_300, 4),
        (302_500, 500_350, 2),
    ];
    let rows: Vec<(i64, (i64, i64, i64))> = GAP_THROUGH_A_STOP
        .iter()
        .map(|&record| (0, record))
        .chain(template.iter().map(|&record| (3, record)))
        .collect();
    write_table(
        &input.join("trades.arrow"),
        vec![
            ("case", int64(rows.iter().map(|(case, _)| *case).collect())),
            ("trade_date", int64(vec![TRADE_DATE; rows.len()])),
            (
                "ts_recv",
                int64(rows.iter().map(|(_, (ms, _, _))| at(*ms)).collect()),
            ),
            (
                "price",
                int64(
                    rows.iter()
                        .map(|(_, (_, cents, _))| price(*cents))
                        .collect(),
                ),
            ),
            (
                "size",
                int64(rows.iter().map(|(_, (_, _, size))| *size).collect()),
            ),
        ],
    );
}

fn tbbo_file(input: &Path) {
    let records: [QuotedTrade; 2] = [
        (200, 499_500, 2, 499_500, 499_525, 6, 4),
        (300, 500_525, 1, 500_500, 500_525, 3, 5),
    ];
    let column = |value: fn(&QuotedTrade) -> i64| int64(records.iter().map(value).collect());
    write_table(
        &input.join("tbbo.arrow"),
        vec![
            ("case", int64(vec![2; 2])),
            ("trade_date", int64(vec![TRADE_DATE; 2])),
            ("ts_recv", column(|record| at(record.0))),
            ("price", column(|record| price(record.1))),
            ("size", column(|record| record.2)),
            ("bid", column(|record| price(record.3))),
            ("ask", column(|record| price(record.4))),
            ("bid_size", column(|record| record.5)),
            ("ask_size", column(|record| record.6)),
        ],
    );
}

fn signals_file(input: &Path) {
    let flag = |value: bool| -> ArrayRef { Arc::new(BooleanArray::from(vec![value])) };
    write_table(
        &input.join("signals.arrow"),
        vec![
            ("case", int64(vec![3])),
            ("ts_close", int64(vec![at(300_000)])),
            ("long_entry", flag(false)),
            ("short_entry", flag(true)),
            ("long_exit", flag(false)),
            ("short_exit", flag(false)),
            ("stop_price", int64(vec![price(500_300)])),
            ("target_price", int64(vec![price(499_000)])),
            ("size_mult", Arc::new(Float64Array::from(vec![2.0]))),
        ],
    );
}

/// S-fill-012's records written as an engine cache, its contract folder returned.
fn cache_of_the_gap(folder: &Path) -> PathBuf {
    let contract_folder = folder.join("ESH2026");
    let day = TapeDay {
        trade_date: TradeDate(20_518),
        tbbo: Vec::new(),
        trades: GAP_THROUGH_A_STOP
            .iter()
            .map(|&(ms, cents, size)| TradeRow {
                ts_recv: Ts(at(ms)),
                price: Price(price(cents)),
                size: Qty(size),
            })
            .collect(),
        bars: Default::default(),
    };
    let sources = vec![SourceFile {
        path: "synthetic/trades/root=ES/contract=ESH2026/date=2026-03-06/part.parquet".into(),
        sha256: "0".repeat(64),
    }];
    let contract = Contract("ESH2026".to_owned());
    let month = Month::of(day.trade_date);
    let mut writer = CacheMonthWriter::create(&contract_folder, contract, month, sources).unwrap();
    writer.write_trade_date(day).unwrap();
    writer.finish().unwrap();
    contract_folder
}

/// A case of ES at `fidelity`, replayed in full, holding a long of one lot when `decisions` are
/// orders; a case on its tape reads the file of its fidelity.
fn case(
    id: &str,
    fidelity: &str,
    mut market_data: serde_json::Value,
    decisions: serde_json::Value,
) -> serde_json::Value {
    let long = json!({"side": "long", "lots": 1, "price": price(500_000)});
    let position = if decisions["kind"] == "orders" {
        long
    } else {
        serde_json::Value::Null
    };
    if market_data["kind"] == "tape" {
        market_data["levels"] = json!([fidelity]);
    }
    let ticks = u32::from(fidelity != "tbbo");
    json!({
        "id": id,
        "fidelity": fidelity,
        "replay": "full",
        "contract": "ESH2026",
        "instrument": {"tick_size": 250_000_000, "money_per_point": 50_000_000, "lot_step": 1_000_000_000},
        "settings": {
            "latency_ms": 100,
            "slippage_ticks": {"market": ticks, "stop": ticks},
            "limit_fill": "through"
        },
        "hours": {"kind": "always"},
        "capital": 50_000_000_000_i64,
        "position": position,
        "market_data": market_data,
        "decisions": decisions,
    })
}

fn run_manifest(cache: &Path) -> serde_json::Value {
    let sell_stop = json!({"kind": "orders", "orders": [
        {"id": 1, "placed_at": at(0), "side": "sell", "kind": "stop", "price": price(499_500), "lots": 1}
    ]});
    let stop_and_target = json!({"kind": "orders", "orders": [
        {"id": 1, "placed_at": at(0), "side": "sell", "kind": "stop", "price": price(499_500), "lots": 1, "oco": 1},
        {"id": 2, "placed_at": at(0), "side": "sell", "kind": "limit", "price": price(500_500), "lots": 1, "oco": 1}
    ]});
    let template = json!({"kind": "template", "strategy": {
        "spec_version": 1, "instrument": "ES", "timeframe": "5m",
        "execution": {
            "entry": {"kind": "market"},
            "stop": {"kind": "column"},
            "targets": [{"price": {"kind": "column"}}],
            "sizing": {"kind": "fixed", "units": 1}
        }
    }});
    json!({"cases": [
        case("S-fill-012", "trades", json!({"kind": "tape"}), sell_stop.clone()),
        case("S-fill-012 cached", "trades", json!({"kind": "cache", "folder": cache}), sell_stop),
        case("S-fill-036", "tbbo", json!({"kind": "tape"}), stop_and_target),
        case("S-template-002", "trades", json!({"kind": "tape"}), template),
    ]})
}

#[test]
fn a_case_on_bars_reads_its_bar_file_and_counts_its_ambiguous_fills() {
    // S-fill-022: a long's stop and target inside one 1-minute bar resolve to the stop.
    let folder = TemporaryFolder::new("bars");
    let (input, output) = (folder.0.join("input"), folder.0.join("output"));
    fs::create_dir_all(&input).unwrap();
    let bars: [(i64, [i64; 4], i64); 2] = [
        (0, [500_025, 500_300, 499_850, 500_175], 210),
        (60_000, [500_150, 501_125, 499_375, 500_600], 640),
    ];
    let column = |value: fn(&(i64, [i64; 4], i64)) -> i64| int64(bars.iter().map(value).collect());
    write_table(
        &input.join("1m.arrow"),
        vec![
            ("case", int64(vec![0; 2])),
            ("trade_date", int64(vec![TRADE_DATE; 2])),
            ("ts_open", column(|bar| at(bar.0))),
            ("ts_close", column(|bar| at(bar.0 + 60_000))),
            ("open", column(|bar| price(bar.1[0]))),
            ("high", column(|bar| price(bar.1[1]))),
            ("low", column(|bar| price(bar.1[2]))),
            ("close", column(|bar| price(bar.1[3]))),
            ("volume", column(|bar| bar.2)),
        ],
    );
    let exits = json!({"kind": "orders", "orders": [
        {"id": 1, "placed_at": at(0), "side": "sell", "kind": "stop", "price": price(499_500), "lots": 1, "oco": 1},
        {"id": 2, "placed_at": at(0), "side": "sell", "kind": "limit", "price": price(501_000), "lots": 1, "oco": 1}
    ]});
    let mut skipping = case("S-fill-022", "1m", json!({"kind": "tape"}), exits);
    skipping["replay"] = json!("skipping");
    fs::write(
        input.join("run.json"),
        json!({"cases": [skipping]}).to_string(),
    )
    .unwrap();

    let summary = run_batch(&input, &output).unwrap();

    assert_eq!(
        (summary.cases, summary.fills, summary.ambiguous_fills),
        (1, 1, 1)
    );
    let fills = read_table(&output.join("fills.arrow"));
    let text = |name: &str| {
        fills
            .column_by_name(name)
            .unwrap()
            .as_string::<i32>()
            .value(0)
            .to_owned()
    };
    let flagged = fills
        .column_by_name("ambiguous")
        .unwrap()
        .as_boolean()
        .value(0);
    assert_eq!(
        (text("rule"), text("fidelity"), flagged),
        ("F-STP-04".to_owned(), "1m".to_owned(), true)
    );
    let ledger = read_table(&output.join("ledger.arrow"));
    let counted = ledger.column_by_name("ambiguous_fills").unwrap();
    assert_eq!(counted.as_primitive::<Int64Type>().value(0), 1);
}

#[test]
fn a_batch_runs_each_case_from_its_files_or_its_cache_and_tags_its_outputs() {
    let folder = TemporaryFolder::new("run");
    let (input, output) = (folder.0.join("input"), folder.0.join("output"));
    fs::create_dir_all(&input).unwrap();
    let cache = cache_of_the_gap(&folder.0.join("cache"));
    fs::write(input.join("run.json"), run_manifest(&cache).to_string()).unwrap();
    trades_file(&input);
    tbbo_file(&input);
    signals_file(&input);

    let summary = run_batch(&input, &output).unwrap();

    assert_eq!((summary.cases, summary.fills), (4, 5));
    let fills = read_table(&output.join("fills.arrow"));
    let column = |name: &str| fills.column_by_name(name).unwrap().clone();
    let cases = column("case");
    let orders = column("order");
    let prices = column("price");
    let rules = column("rule");
    let read: Vec<(i64, u64, i64, &str)> = (0..fills.num_rows())
        .map(|row| {
            (
                cases.as_primitive::<Int64Type>().value(row),
                orders.as_primitive::<UInt64Type>().value(row),
                prices.as_primitive::<Int64Type>().value(row) / 10_000_000,
                rules.as_string::<i32>().value(row),
            )
        })
        .collect();
    assert_eq!(
        read,
        [
            (0, 1, 499_025, "F-STP-03"),
            (1, 1, 499_025, "F-STP-03"),
            (2, 1, 499_500, "F-STP-02"),
            (3, 1, 499_975, "F-MKT-02"),
            (3, 2, 500_325, "F-STP-03"),
        ]
    );
    let order_states = read_table(&output.join("orders.arrow"));
    let states = order_states
        .column_by_name("state")
        .unwrap()
        .as_string::<i32>()
        .clone();
    let ids = order_states
        .column_by_name("id")
        .unwrap()
        .as_primitive::<UInt64Type>()
        .clone();
    let of_case_two: Vec<(u64, &str)> = (0..order_states.num_rows())
        .filter(|&row| {
            order_states
                .column_by_name("case")
                .unwrap()
                .as_primitive::<Int64Type>()
                .value(row)
                == 2
        })
        .map(|row| (ids.value(row), states.value(row)))
        .collect();
    assert_eq!(of_case_two, [(1, "filled"), (2, "cancelled")]);
    let log = read_table(&output.join("log.arrow"));
    let rule_of_logs = log
        .column_by_name("rule")
        .unwrap()
        .as_string::<i32>()
        .clone();
    assert!(
        (0..log.num_rows())
            .any(|row| rule_of_logs.is_valid(row) && rule_of_logs.value(row) == "F-OCO-01")
    );
}

#[test]
fn a_case_without_records_is_refused_by_name() {
    let folder = TemporaryFolder::new("refused");
    let (input, output) = (folder.0.join("input"), folder.0.join("output"));
    fs::create_dir_all(&input).unwrap();
    let only = json!({"cases": [case("S-fill-012", "trades", json!({"kind": "tape"}), json!({"kind": "orders", "orders": []}))]});
    fs::write(input.join("run.json"), only.to_string()).unwrap();

    let refused = run_batch(&input, &output).unwrap_err().to_string();

    assert!(
        refused.starts_with("Expected case S-fill-012 to run, got: Expected a tape"),
        "{refused}"
    );
}

#[test]
fn a_stop_without_a_price_is_refused() {
    let folder = TemporaryFolder::new("unpriced");
    let (input, output) = (folder.0.join("input"), folder.0.join("output"));
    fs::create_dir_all(&input).unwrap();
    let unpriced = json!({"kind": "orders", "orders": [
        {"id": 1, "placed_at": at(0), "side": "sell", "kind": "stop", "lots": 1}
    ]});
    let manifest =
        json!({"cases": [case("S-fill-012", "trades", json!({"kind": "tape"}), unpriced)]});
    fs::write(input.join("run.json"), manifest.to_string()).unwrap();

    let refused = run_batch(&input, &output).unwrap_err().to_string();

    assert!(
        refused.starts_with("Expected case S-fill-012 to run, got: Expected a price"),
        "{refused}"
    );
}

#[test]
fn a_case_with_two_orders_under_one_id_is_refused() {
    let folder = TemporaryFolder::new("repeated");
    let (input, output) = (folder.0.join("input"), folder.0.join("output"));
    fs::create_dir_all(&input).unwrap();
    let twice = json!({"kind": "orders", "orders": [
        {"id": 1, "placed_at": at(0), "side": "sell", "kind": "stop", "price": price(499_500), "lots": 1},
        {"id": 2, "placed_at": at(0), "side": "buy", "kind": "market", "lots": 1,
         "bracket": {"stop": {"id": 3, "price": price(499_000)}, "target": {"id": 1, "price": price(501_000)}}}
    ]});
    let manifest = json!({"cases": [case("S-fill-012", "trades", json!({"kind": "tape"}), twice)]});
    fs::write(input.join("run.json"), manifest.to_string()).unwrap();
    trades_file(&input);

    let refused = run_batch(&input, &output).unwrap_err().to_string();

    assert!(
        refused.starts_with("Expected case S-fill-012 to run, got: Expected every order"),
        "{refused}"
    );
    assert!(refused.ends_with("got order 1 twice"), "{refused}");
}
