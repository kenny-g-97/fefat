# Fill scenarios

Each YAML file here is one scenario: a short tape of trades, TBBO records, or bars, the orders placed on it, and the fills that the [fill specification](../../docs/spec/fill-semantics.md) gives, with the arithmetic in a comment so you can check every number with a calculator. Together they are the specification in examples. The Python reference engine (step 2.2) and the Rust engine (from step 2.6) must produce exactly these fills, and a test is never fixed by editing an expected value: if an expected value looks wrong to you, say which rule you believe applies, and the specification changes first, then the scenario.

`fefat.reference.scenarios` reads them (`load_scenario`, `load_scenarios`). `python/tests/test_reference_scenarios.py` checks that every scenario validates, cites only rules the specification defines, and shows its arithmetic, and that together they cite every rule. The scenario runner of step 2.2 checks each fill's price, time, rule, flags, and fee, and that its fidelity tag is the scenario's fidelity (F-TAG-01).

## A scenario

S-fill-012, the gap through a stop:

```yaml
id: S-fill-012                      # the file's name; stable, never reused
title: A sell stop gapped through on trades fills at the first trade past it
fidelity: trades                    # tbbo, trades, 1s, 1m, or a coarser 5m or 1d
instrument: ES                      # a root of the instrument table, or one given inline
position: {side: long, quantity: 1, price: "5000.00"}   # held when the tape starts
orders:
  - {id: 1, placed_at: "2026-03-06T14:30:00.000Z", side: sell, kind: stop, price: "4995.00", quantity: 1}
tape:
  - {ts: "2026-03-06T14:30:00.200Z", price: "4996.00", size: 2}
  - {ts: "2026-03-06T14:30:00.450Z", price: "4995.50", size: 1}
  - {ts: "2026-03-06T14:30:01.250Z", price: "4990.25", size: 6}
  - {ts: "2026-03-06T14:30:01.400Z", price: "4990.75", size: 3}
expected:
  fills:
    - {order: 1, ts: "2026-03-06T14:30:01.250Z", price: "4990.25", rule: F-STP-03}
rules: [F-SLP-01, F-STP-01, F-STP-03]

# Arithmetic (ES, tick 0.25; one tick of slippage on trades: F-SLP-01). ...
# fill = lower of (4995.00 - 1 × 0.25, 4990.25) = lower of (4994.75, 4990.25) = 4990.25 (F-STP-03).
```

## Fields

| Field | What it holds |
| --- | --- |
| `id` | `S-<area>-NNN`, the file's name without `.yaml`. Ids are stable: later steps and reviews refer to them, and an id is never reused. |
| `title` | One line saying what the scenario shows. |
| `fidelity` | The data the tape holds: `tbbo`, `trades`, or a bar timeframe, `1s`, `1m`, or an import's coarser `5m` or `1d`. |
| `instrument` | A root of the instrument table (`ES`, `MES`, `BTCUSDT-PERP`, and so on), whose tick size, point value, lot step, and session calendar apply; or `{tick_size, point_value, lot_step}` for a product the table lacks, which trades around the clock. |
| `settings` | Optional run settings: `latency_ms` (100), `slippage_ticks: {market, stop}` (none on `tbbo`, one on every other fidelity), and `limit_fill` (`through`, or `touch`). Left out, the specification's defaults apply. |
| `fees` | Optional: `{kind: futures, per_contract_side}` or `{kind: crypto, maker_bps, taker_bps}`, as in `fefat.market.fees`: the fee of the schedule in force, which a run takes from its dated fee table (F-FEE-01). With fees, every expected fill states its `fee`. |
| `position` | Optional position held when the tape starts: `{side: long or short, quantity, price}`. |
| `tape` | The records, in the order the engine reads them. Trades: `{ts, price, size}`, with `ts` the receive time and an optional `ts_event`, the exchange's time, which the engine never reads. TBBO: the same with `bid, ask, bid_size, ask_size`, the quote just before the trade. Bars: `{ts_open, ts_close, open, high, low, close, volume}`, stored bars only, so a minute without trades has none. Sizes and volumes count the dataset's size unit. |
| `funding` | Optional funding rates of a perpetual: `{ts, rate}`, where `"0.0001"` is 0.01 %. |
| `orders` | `{id, placed_at, side: buy or sell, kind: market, stop, or limit, price, quantity}`, with `price` for stops and limits only, and optionally `oco: <group>` and `bracket: {stop: {id, price}, target: {id, price}}`. `placed_at` is the decision instant: the order becomes active the latency later. |
| `expected` | `fills: [{order, ts, price, rule, flags, fee}]`, where `rule` is the rule that priced the fill and `flags` may list `ambiguous` or `size_exceeded`; `fills: []` expects none. Optionally `marks: [{ts, price}]`, the mark once every event at `ts` is done, and `funding: [{ts, amount}]`, an amount being the change to the trader's cash. |
| `rules` | Every rule the scenario exercises; each fill's `rule` is one of them. |

## Writing numbers

- Prices are decimals in quotes, `"4990.25"`, read as integers in 1e-9 units (4,990,250,000,000), the units both engines count in. Unquoted, YAML would read them as binary fractions, so the loader refuses them.
- Instants are UTC times in quotes, with a `Z`, to the nanosecond at most: `"2026-03-06T14:30:00.100Z"`. Unquoted, YAML reads `14:30:00` as the number 52200.
- Money is a decimal in quotes in the instrument's currency, `"2.50"`, read in micro-units.
- Quantities count contracts for futures and the base asset for crypto: a whole number, or a decimal in quotes on the lot step, such as `"0.013"` BTC.
- Every price lies on the instrument's tick, and every quantity on its lot step.

## The arithmetic

Each file ends with a comment that works out every expected value from the tape and the rules, citing each rule where it applies, so a reader can recompute the fills by hand. Where another reading of the rules would give another fill, the comment says which and why. Times are UTC, and Chicago times are given where sessions matter.

## Changing a scenario

A new scenario takes the next free id, its file, and a row below. An edit of an existing scenario, or of the specification, asks you first: the file guard (`.claude/hooks/guard-file-paths.mjs`) asks before either changes, as it does for goldens.

## The scenarios

| Id | Fidelity | What it shows |
| --- | --- | --- |
| [S-fill-001](S-fill-001.yaml) | tbbo | A buy market order on TBBO fills at the ask of the first record after its activation |
| [S-fill-002](S-fill-002.yaml) | tbbo | A sell market order on TBBO fills whole at the bid, flagged when larger than the bid's size |
| [S-fill-003](S-fill-003.yaml) | trades | A buy market order on trades fills at the first trade at or after its activation plus a tick |
| [S-fill-004](S-fill-004.yaml) | 1s | A buy market order on 1-second bars fills at the open of the first bar closing after its activation |
| [S-fill-005](S-fill-005.yaml) | 1m | A sell market order on 1-minute bars fills at the next bar's open minus a tick, at that bar's close |
| [S-fill-006](S-fill-006.yaml) | 5m | A buy market order on an import's 5-minute bars fills at the next bar's open plus a tick, tagged 5m |
| [S-fill-007](S-fill-007.yaml) | 1d | A buy market order on daily bars fills at the next session's open plus a tick, at that session's close |
| [S-fill-008](S-fill-008.yaml) | tbbo | A buy stop on TBBO triggers on a trade at its price and fills at the next record's ask |
| [S-fill-009](S-fill-009.yaml) | trades | A buy stop on trades fills a tick above its price, and trades received at one instant keep their order |
| [S-fill-010](S-fill-010.yaml) | 1s | A buy stop on 1-second bars triggers when a bar's high reaches its price and fills a tick above it |
| [S-fill-011](S-fill-011.yaml) | 1m | A buy stop on 1-minute bars fills at the open of a bar that opens past it |
| [S-fill-012](S-fill-012.yaml) | trades | A sell stop gapped through on trades fills at the first trade past it |
| [S-fill-013](S-fill-013.yaml) | 5m | A sell stop on an import's 5-minute bars fills a tick below its price, tagged 5m |
| [S-fill-014](S-fill-014.yaml) | tbbo | A buy stop placed below the market is accepted and fills at once, as a market order would |
| [S-fill-015](S-fill-015.yaml) | tbbo | A buy limit on TBBO fills at its price when a trade prints below it |
| [S-fill-016](S-fill-016.yaml) | tbbo | A buy limit on TBBO fills at its price when the ask comes down to it |
| [S-fill-017](S-fill-017.yaml) | trades | A buy limit on trades that the market touches without trading through does not fill |
| [S-fill-018](S-fill-018.yaml) | trades | With touch fills, a buy limit on trades fills on the first trade at its price |
| [S-fill-019](S-fill-019.yaml) | 1s | A sell limit on 1-second bars fills at its price once a bar's high goes above it |
| [S-fill-020](S-fill-020.yaml) | 1m | A buy limit on 1-minute bars fills at its price when a bar opens below it, not at the open |
| [S-fill-021](S-fill-021.yaml) | 1d | A sell limit on daily bars stays working over a weekend and fills at its price, tagged 1d |
| [S-fill-022](S-fill-022.yaml) | 1m | A long's stop and target inside one 1-minute bar resolve to the stop, flagged ambiguous |
| [S-fill-023](S-fill-023.yaml) | 1s | A short's stop and target inside one 1-second bar resolve to the stop, flagged ambiguous |
| [S-fill-024](S-fill-024.yaml) | 1m | A buy stop entry and its bracket stop both fill in one 1-minute bar, flagged ambiguous |
| [S-fill-025](S-fill-025.yaml) | trades | Of an OCO pair of entry stops on trades, the first to trigger fills and cancels the other |
| [S-fill-026](S-fill-026.yaml) | 1m | A market order active during a minute without trades fills on the next stored bar |
| [S-fill-027](S-fill-027.yaml) | trades | A market order active in the break fills on the next session's first trade, not on a print in the break |
| [S-fill-028](S-fill-028.yaml) | trades | A futures round trip pays the fee per contract per side on its entry and its exit |
| [S-fill-029](S-fill-029.yaml) | trades | A crypto short pays maker on its resting limit entry, receives funding, and pays taker on its market exit |
| [S-fill-030](S-fill-030.yaml) | 1m | An open position is marked at each bar's close, not at its fill price |
| [S-fill-031](S-fill-031.yaml) | 1s | With a 1-second latency on 1-second bars, an order active at a bar's close sees the next bar |
| [S-fill-032](S-fill-032.yaml) | 1m | A long opened on the bar that closes at a funding time pays that funding |
| [S-fill-033](S-fill-033.yaml) | 1m | Of an OCO pair of entry stops both inside one bar, the lower order id fills, flagged ambiguous |
| [S-fill-034](S-fill-034.yaml) | 1m | A bar that opens through a long's target fills the target at its open, though it reaches the stop later |
| [S-fill-035](S-fill-035.yaml) | trades | A bracket stop placed at the market fills as a market order on the next trade, not on its entry's own trade |
| [S-fill-036](S-fill-036.yaml) | tbbo | When one TBBO record would fill both a long's triggered stop and its target, the stop fills |
| [S-fill-037](S-fill-037.yaml) | trades | A trade the exchange stamped before an order's activation but received after it counts for that order |
| [S-fill-038](S-fill-038.yaml) | trades | A buy limit above a crypto market fills at its own price on the first trade, as a taker |
| [S-fill-039](S-fill-039.yaml) | trades | A buy limit larger than the trade that goes through it fills whole, flagged size_exceeded |
