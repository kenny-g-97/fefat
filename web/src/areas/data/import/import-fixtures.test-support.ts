import type {
  FileSeen,
  ImportProfile,
  ListedProfile,
  TablePreview,
} from "@/api/imports"

/** The NinjaTrader preset as the server lists it (`ninjatrader.yaml`). */
export const NINJATRADER: ImportProfile = {
  kind: "market_data",
  name: "ninjatrader",
  provider: "ninjatrader",
  description:
    "NinjaTrader 8 minute bars (Last): semicolons, no header, UTC, stamped at the close",
  layout: { delimiter: ";", header: false },
  columns: {
    timestamp: 0,
    date: null,
    time: null,
    bars: {
      open: 1,
      high: 2,
      low: 3,
      close: 4,
      volume: 5,
      trade_count: null,
      vwap: null,
    },
    ticks: null,
    instrument_id: null,
    symbol: null,
    record_type: null,
  },
  timestamp: { format: "%Y%m%d %H%M%S", time_zone: "UTC", stamp: "close" },
  price: { unit: "decimal", scale: "1" },
  volume_unit: { lot: "1", asset: "contract" },
  timeframe: "1m",
  series: "contract",
  contract_in_file_name:
    "^(?P<root>[A-Z0-9]{1,4}) (?P<month>[0-9]{2})-(?P<year>[0-9]{2})\\.Last\\.txt$",
  instrument: null,
  licence_scope: null,
}

/** The IBKR preset's shape, which leaves the time zone to the import. */
export const IBKR: ImportProfile = {
  ...NINJATRADER,
  name: "ibkr",
  provider: "ibkr",
  layout: { delimiter: ",", header: true },
  timestamp: { ...NINJATRADER.timestamp, time_zone: null },
}

export const LISTED: readonly ListedProfile[] = [
  { origin: "preset", profile: IBKR },
  { origin: "preset", profile: NINJATRADER },
  {
    origin: "saved",
    profile: { ...NINJATRADER, name: "my-ninjatrader", provider: "kibot" },
  },
]

/** A NinjaTrader export's table, its six columns unnamed. */
export const NINJATRADER_TABLE: TablePreview = {
  kind: "table",
  file_name: "XES 03-26.Last.txt",
  layout: { delimiter: ";", header: false },
  columns: [
    "column_1",
    "column_2",
    "column_3",
    "column_4",
    "column_5",
    "column_6",
  ],
  columns_total: 6,
  rows: [["20260202 000100", "100", "101", "99", "100.5", "12"]],
  rows_total: 1,
}

/** What a preview finds of a NinjaTrader export of `file_name`, with `verdict`. */
export function seenFile(
  file_name: string,
  verdict: FileSeen["verdict"],
  merge: FileSeen["merge"] = null
): FileSeen {
  return {
    kind: "file",
    verdict,
    file_name,
    profile: "ninjatrader",
    dataset: { provider: "ninjatrader", schema_name: "ohlcv-1m", root: "ES" },
    rows_read: 10,
    records: 10,
    contracts: ["ESH2026"],
    contracts_total: 1,
    first_trade_date: "2026-03-05",
    last_trade_date: "2026-03-05",
    bars_without_volume: 0,
    spread_rows: 0,
    problems: [],
    problems_total: 0,
    days_checked: 1,
    offsets: [],
    mismatches: [],
    mismatches_total: 0,
    warnings: [],
    first_records: { kind: "bars", rows: [] },
    merge,
    raw_path: null,
  }
}
