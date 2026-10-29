# Fill scenarios

Each YAML file here is one scenario: a short tape of trades, TBBO records, or bars, the orders placed on it, and the fills that the [fill specification](../../docs/spec/fill-semantics.md) gives, with the arithmetic in a comment so you can check every number with a calculator. Together they are the specification in examples. The Python reference engine (step 2.2) and the Rust engine (from step 2.6) must produce exactly these fills, and a test is never fixed by editing an expected value: if an expected value looks wrong to you, say which rule you believe applies, and the specification changes first, then the scenario.

`fefat.reference.scenarios` reads them (`load_scenario`, `load_scenarios`). `python/tests/test_reference_scenarios.py` checks that every scenario validates, cites only rules the specification defines, and shows its arithmetic, and that together they cite every rule. The scenario runner of step 2.2 checks each fill's price, time, rule, flags, and fee, and that its fidelity tag is the scenario's fidelity (F-TAG-01), as well as the marks and the funding payments; `python/tests/test_reference_engine_scenarios.py` runs it. From the repository folder, `uv run python -m fefat.reference.scenario_runner` prints how many scenarios pass and how they cover the rules, and `--log S-fill-012` prints one scenario as written beside the reference engine's event log, to follow a fill from its tape to the log.

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
| `settings` | Optional run settings: `latency_ms` (100), `slippage_ticks: {market, stop}` (none on `tbbo`, one on every other fidelity), `limit_fill` (`through`, or `touch`), and `roll_handling` (`transfer`, or `flatten`, F-ROL-04). Left out, the specification's defaults apply. |
| `fees` | Optional: one fee in force on every date, `{kind: futures, per_contract_side}` or `{kind: crypto, maker_bps, taker_bps}`, as in `fefat.market.fees`; or a dated fee table, `{kind, schedules: [{effective_from, per_contract_side}]}` or with `maker_bps` and `taker_bps`, each schedule in force from its date until the next, the first also before its date, with a warning (F-FEE-01). With fees, every expected fill states its `fee`. |
| `position` | Optional position held when the tape starts: `{side: long or short, quantity, price}`. |
| `rolls` | Optional rolls of a future's front, as the roll calendar gives them: `{trade_date, session_open, rolled_from, contract, gap, reason}`, in the order of their opens, each rolling from the one before's `contract`; `gap` is a price difference, the new contract's close less the old one's, and `reason` is `volume`, `open-interest`, `calendar`, or `expiry` (§29). The tape then holds each session's records of that session's front. |
| `tape` | The records, in the order the engine reads them. Trades: `{ts, price, size}`, with `ts` the receive time and an optional `ts_event`, the exchange's time, which the engine never reads. TBBO: the same with `bid, ask, bid_size, ask_size`, the quote just before the trade. Bars: `{ts_open, ts_close, open, high, low, close, volume}`, stored bars only, so a minute without trades has none. Sizes and volumes count the dataset's size unit. |
| `funding` | Optional funding rates of a perpetual: `{ts, rate}`, where `"0.0001"` is 0.01 %. |
| `orders` | `{id, placed_at, side: buy or sell, kind: market, stop, or limit, price, quantity}`, with `price` for stops and limits only, and optionally `oco: <group>` and `bracket: {stop: {id, price}, target: {id, price}}`. `placed_at` is the decision instant: the order becomes active the latency later. |
| `expected` | `fills: [{order, ts, price, rule, flags, fee, quantity, role, contract}]`, where `rule` is the rule that priced the fill and `flags` may list `ambiguous` or `size_exceeded`; `fills: []` expects none. `quantity`, in the instrument's units as an order's, is stated on every fill or on none: a template's targets and sizes decide it. `role`, the order's role as its fill records it (F-TAG-01), `entry`, `stop`, `target_1` to `target_3`, a template's exit reason such as `no_weekend`, or a roll's leg's such as `roll_volume`, is stated on every fill or on none. `contract`, the contract the fill is of (F-ROL-01), is stated on every fill or on none, one of the rolls' contracts. Optionally `marks: [{ts, price}]`, the mark once every event at `ts` is done, and `funding: [{ts, amount}]`, an amount being the change to the trader's cash. |
| `rules` | Every rule the scenario exercises; each fill's `rule` is one of them. |

## Writing numbers

- Prices are decimals in quotes, `"4990.25"`, read as integers in 1e-9 units (4,990,250,000,000), the units both engines count in. Unquoted, YAML would read them as binary fractions, so the loader refuses them.
- Instants are UTC times in quotes, with a `Z`, to the nanosecond at most: `"2026-03-06T14:30:00.100Z"`. Unquoted, YAML reads `14:30:00` as the number 52200.
- Money is a decimal in quotes in the instrument's currency, `"2.50"`, read in micro-units.
- Quantities count contracts for futures and the base asset for crypto: a whole number, or a decimal in quotes on the lot step, such as `"0.013"` BTC.
- Every price lies on the instrument's tick, and every quantity on its lot step.
- A key written twice in one mapping is refused, rather than YAML keeping the second silently, and so is a bar longer than its timeframe (a daily bar is a session, which a holiday can stretch).
- Expected fills must be possible: an order fills once at most, one order of an OCO group or a bracket at most, and a bracket's leg only after its entry.

## The arithmetic

Each file ends with a comment that works out every expected value from the tape and the rules, citing each rule where it applies, so a reader can recompute the fills by hand. Where another reading of the rules would give another fill, the comment says which and why. Times are UTC, and Chicago times are given where sessions matter.

## Changing a scenario

A new scenario takes the next free id, its file, and a row below. An edit of an existing scenario, or of the specification, asks you first: the file guard (`.claude/hooks/guard-file-paths.mjs`) asks before either changes, as it does for goldens.

## Template scenarios

A template scenario (step 2.3) runs an execution template instead of orders. In place of `orders` it gives `strategy`, a `StrategySpec` document (its schema is `python/fefat/src/fefat/strategy/strategy_spec.schema.json`, D-53), and `signals`, the rows of its signal frame, which the reference engine runs through its template (`fefat.reference.template`), by the rules of the specification's §20 to §28 (step 2.8). A template scenario starts flat.

| Field | What it holds |
| --- | --- |
| `strategy` | The specification, leaving out what it does not use: `{spec_version: 1, instrument, timeframe, execution: {entry, stop, targets, breakeven, trailing, time, limits, sizing}}`. Its `instrument` is the scenario's, and `timeframe` that of the signal bars. |
| `signals` | One row per signal close, in time order: `{ts_close, trade_date, contract}`, then `long_entry`, `short_entry`, `long_exit`, and `short_exit` where they are true, and where a row needs them `entry_price`, `stop_price`, `target_price`, and `trail_ref` (raw prices in quotes, as in a tape), `size_mult`, `wake` (false on a bar on which no entry is placed), `features`, the strategy's numbers by name, such as `{atr: 1300000000.0}`, an ATR of 1.3 points in the 1e-9 units of price that a feature worked out from the bars' prices has (F-RND-01), and `flags`, its boolean columns by name, such as `{news: true}`. A scenario's prices are its contract's raw prices, so the frame's `adj_offset` is 0. |

The orders a template places take the ids the engine gives them, from 1 in the order they are placed: an entry is order 1; when it fills, its exit plan's stop takes the next id and each of its targets the one after, a target of no lots taking none (F-PLN-01); and the order that closes the position at the market, at a signal exit or a time rule, takes the next one. With one target, the stop and the target are orders 2 and 3, and an exit order 4. A roll's legs take the next ids the engine gives when the roll comes (F-ROL-02), the close leg first; in an order scenario, the engine's ids start after the highest id the scenario names.

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
| [S-fill-040](S-fill-040.yaml) | 1m | A bracket stop placed through the market at its entry's bar open fills there, as a market order would |
| [S-fill-041](S-fill-041.yaml) | tbbo | On TBBO a bracket stop at its entry record's trade price is through the market and fills on the next record |
| [S-fill-042](S-fill-042.yaml) | 1m | A stop that reverses a long inside a 1-minute bar turns the path adverse for the new short |
| [S-fill-043](S-fill-043.yaml) | tbbo | A TBBO record that triggers a stop and trades through a limit of its OCO group fills the limit |
| [S-fill-044](S-fill-044.yaml) | tbbo | In a TBBO sweep a long's stop fills at the next print, below the bid it carries from before the sweep |
| [S-fill-045](S-fill-045.yaml) | tbbo | A TBBO market buy whose record trades above its ask fills at the trade |
| [S-fill-046](S-fill-046.yaml) | tbbo | A TBBO bid above its record's trade counts as the trade and does not fill a sell limit |
| [S-fill-047](S-fill-047.yaml) | tbbo | A TBBO stop triggered on one record fills on the next before a market order of its OCO group active there |
| [S-fill-048](S-fill-048.yaml) | tbbo | A TBBO market buy whose record trades above its ask is flagged against the trade's size |
| [S-fill-049](S-fill-049.yaml) | tbbo | A TBBO record that triggers a stop and bids at a limit of its OCO group fills the limit |
| [S-fill-050](S-fill-050.yaml) | 1m | An exit that leaves a long flat inside a 1-minute bar keeps the order of the bar's extremes |
| [S-fill-051](S-fill-051.yaml) | 1m | Of two stops of one OCO group through the market when they become active, the lower id fills at the next bar's open |
| [S-fill-052](S-fill-052.yaml) | 1m | A bar that opens past a stop and a limit of one OCO group fills the stop, though the limit has the lower id |
| [S-fill-053](S-fill-053.yaml) | 1m | Flat with a buy limit placed first, a 1-minute bar goes to its high first, as for a buy stop |
| [S-fill-054](S-fill-054.yaml) | trades | With no latency, a trade at the decision's instant sets the mark a stop is judged against but is not seen by it |
| [S-fill-055](S-fill-055.yaml) | 1m | A stop through the market when it becomes active fills at the next bar's open, though that bar opens back on its right side |
| [S-fill-056](S-fill-056.yaml) | 1m | With a 1-minute bar's extremes swapped, its entry is still followed by the move against it, so the bar is not ambiguous |
| [S-fill-057](S-fill-057.yaml) | 1m | An entry closed at the level of the 1-minute bar's path where it filled keeps the order of the bar's extremes |
| [S-fill-058](S-fill-058.yaml) | trades | A long held across a roll is transferred by two legs on two contracts, its bracket moved by the gap |
| [S-fill-059](S-fill-059.yaml) | 1m | On 1-minute bars a roll's legs fill at the open of the new front's first bar, before the bar is replayed |
| [S-fill-060](S-fill-060.yaml) | trades | With roll_handling flatten a roll closes the long by its close leg alone and cancels its bracket |
| [S-fill-061](S-fill-061.yaml) | trades | A buy limit resting across a roll moves by the gap and fills on the new front |
| [S-fill-062](S-fill-062.yaml) | trades | A dated fee table prices each fill by its trade date, the first schedule also before its date, with a warning |
| [S-fill-063](S-fill-063.yaml) | trades | A CL long is stopped below zero, as on 2020-04-20, its sell at a negative price paying cash out |
| [S-fill-064](S-fill-064.yaml) | 1d | Funding inside a daily bar is paid on the position as it stood before the bar, at the mark the bar before left |
| [S-fill-065](S-fill-065.yaml) | trades | With a negative funding rate a short pays, its amount rounded against the trader |
| [S-fill-066](S-fill-066.yaml) | tbbo | On TBBO a roll's legs fill at the new front's quote, read no better than its trade, flagged by the size it shows |
| [S-fill-067](S-fill-067.yaml) | trades | Two rolls in one run move the bracket by each gap in turn, each sending its legs on the next front |
| [S-fill-068](S-fill-068.yaml) | tbbo | With flatten, a stop triggered on TBBO before a roll does the close leg's work, and the roll cancels the rest of its plan |
| [S-template-001](S-template-001.yaml) | 1m | A template's long entry fills at the next bar's open and its bracket's target closes the trade |
| [S-template-002](S-template-002.yaml) | trades | A template's short takes its size from size_mult and its bracket from the stop_price and target_price columns |
| [S-template-003](S-template-003.yaml) | 1m | A template closes its position at its flat-by time and enters nothing after it that trade date |
| [S-template-004](S-template-004.yaml) | 1m | A template places nothing on a bar whose wake is false and closes its long on long_exit |
| [S-template-005](S-template-005.yaml) | tbbo | A template's signal exit waits while its TBBO stop, triggered before the close, fills on the next record |
| [S-template-006](S-template-006.yaml) | trades | A trade received at a signal close fills the long's stop before the decision, which finds the position flat |
| [S-template-007](S-template-007.yaml) | trades | A template's entry decided at a signal close fills on the next trade, though the records before the close need no replay |
| [S-template-008](S-template-008.yaml) | 1m | Two targets each close half of two lots, and the first one's fill reduces the stop to the lot left |
| [S-template-009](S-template-009.yaml) | 1m | After the first of two targets fills, the reduced stop closes the one lot left |
| [S-template-010](S-template-010.yaml) | 1m | Three targets share three lots one each, and a bar opening through two fills both by id |
| [S-template-011](S-template-011.yaml) | 1m | A target whose fraction of one lot rounds down to none is not placed, and the next takes the lot |
| [S-template-012](S-template-012.yaml) | 1m | A bar reaching the stop and a partial target sells all the lots at the stop, flagged ambiguous |
| [S-template-013](S-template-013.yaml) | 1m | A target of 1.5 times a 7-tick stop lies 11 ticks above the fill, its 10.5 ticks rounded up |
| [S-template-014](S-template-014.yaml) | 1m | From an ATR of 1.30, a stop of 1.5 ATR rounds down to 7 ticks and a target of 2 ATR up to 11 |
| [S-template-015](S-template-015.yaml) | 1m | A stop of 0.07 % of a 5000.25 fill lies 14 ticks below it, its 14.0007 ticks rounded down |
| [S-template-016](S-template-016.yaml) | 1m | A target of two R measures the initial risk from the fill to a stop at the stop_price column |
| [S-template-017](S-template-017.yaml) | trades | Breakeven moves a long's stop to its fill price once a trade reaches 4 ticks of profit |
| [S-template-018](S-template-018.yaml) | 1m | Breakeven after the first target moves the stop of the half left to the entry, where it exits |
| [S-template-019](S-template-019.yaml) | trades | Breakeven firing under a trailing stop that is already higher leaves the stop at the trailing level |
| [S-template-020](S-template-020.yaml) | trades | A breakeven offset of -2 ticks moves a long's stop to two ticks below its fill price |
| [S-template-021](S-template-021.yaml) | trades | Breakeven at half the initial risk of 7 ticks waits for 4 ticks of profit, its 3.5 rounded up |
| [S-template-022](S-template-022.yaml) | 1m | Breakeven fired at a 1-minute bar's high moves the stop, which the bar's fall to its close reaches |
| [S-template-023](S-template-023.yaml) | trades | A trailing stop on trades follows each new best price 4 ticks behind and closes the long |
| [S-template-024](S-template-024.yaml) | trades | A trailing stop with an activation 8 ticks out leaves the stop alone until a trade reaches it |
| [S-template-025](S-template-025.yaml) | trades | A trailing stop in steps of 2 ticks moves only by whole steps, and stays when one does not fit |
| [S-template-026](S-template-026.yaml) | trades | A trailing stop of one ATR takes the ATR of each decision's row, and tightens when it falls |
| [S-template-027](S-template-027.yaml) | trades | A trailing stop by the column raises the stop to each decision's trail_ref, never lowering it |
| [S-template-028](S-template-028.yaml) | trades | A trailing stop updated at bar closes waits for the decision, and stops a tick below the mark |
| [S-template-029](S-template-029.yaml) | trades | A trailing stop activated by the first target's fill trails the half left and closes it |
| [S-template-030](S-template-030.yaml) | 1m | A trailing stop that would rise at a 1-minute bar's high makes the bar's fill at the low ambiguous |
| [S-template-031](S-template-031.yaml) | trades | A minute of trades above a trailing stop but past its best price is replayed, not skipped |
| [S-template-032](S-template-032.yaml) | trades | A short's trailing stop on trades follows each new low 4 ticks above it and closes the short |
| [S-template-033](S-template-033.yaml) | 1m | A short's first target closes half, breakeven lowers the stop to the fill, and it closes the rest |
| [S-template-034](S-template-034.yaml) | 1m | Without a stop, the first target's fill leaves the second working for the lot left |
| [S-template-035](S-template-035.yaml) | trades | A position with max_bars 2 closes at the second decision after its entry's fill |
| [S-template-036](S-template-036.yaml) | trades | A position with max_minutes 2 closes at the first decision two minutes after its entry's fill |
| [S-template-037](S-template-037.yaml) | trades | Flat-by 15:05 Chicago closes at 21:05 UTC before the clock change and at 20:05 UTC after it |
| [S-template-038](S-template-038.yaml) | trades | On the early close after Thanksgiving, flat-by acts at the last signal close before the close |
| [S-template-039](S-template-039.yaml) | trades | With no_overnight a long closes at the last signal close before the session's close, and none enters at the close |
| [S-template-040](S-template-040.yaml) | trades | With no_overnight a long closes before the Presidents' Day halt, and the template enters again once trading resumes |
| [S-template-041](S-template-041.yaml) | trades | Before 2021-06-28 no_overnight holds a long through the daily 15:15 pause and closes it before the session's close |
| [S-template-042](S-template-042.yaml) | trades | With no_weekend a long held over Thursday's close closes before Friday's close |
| [S-template-043](S-template-043.yaml) | trades | With no_weekend a long closes on Thursday 2025-04-17, before the Good Friday close |
| [S-template-044](S-template-044.yaml) | trades | An entry window from 08:30 to 09:00 Chicago opens at 14:30 UTC before the clock change and at 13:30 UTC after it |
| [S-template-045](S-template-045.yaml) | trades | A Tuesday window from 23:30 past midnight to 00:30 takes Tuesday's early minutes and leaves Monday's late ones |
| [S-template-046](S-template-046.yaml) | trades | A limit entry at the row's entry_price fills once the trades go through it, and its plan follows the fill |
| [S-template-047](S-template-047.yaml) | trades | A limit entry with time_to_live_bars 2 is cancelled at the second decision after it, and the next entry signal places another |
| [S-template-048](S-template-048.yaml) | trades | A limit entry 4 ticks under the mark at the decision fills when the trades go through it, and its stop closes the long |
| [S-template-049](S-template-049.yaml) | trades | A short's stop entry at the row's entry_price fills when a trade reaches it, and its target closes the short |
| [S-template-050](S-template-050.yaml) | trades | A stop entry 4 ticks above the mark at the decision fills when a trade reaches it, and its target closes the long |
| [S-template-051](S-template-051.yaml) | trades | Both entry signals place a buy stop and a sell stop as one OCO group; the sell fills, the buy is cancelled |
| [S-template-052](S-template-052.yaml) | tbbo | A stop entry triggered on TBBO before flat-by fills after it, and the next decision closes the position |
| [S-template-053](S-template-053.yaml) | trades | With on_opposite_signal close a short_entry closes the long, and the next one, flat, enters short |
| [S-template-054](S-template-054.yaml) | trades | With on_opposite_signal reverse a short_entry closes the long and sells short on the same trade, the exit first |
| [S-template-055](S-template-055.yaml) | trades | An offset entry with no mark yet places nothing and the log says why; the next signal, marked, enters |
| [S-template-056](S-template-056.yaml) | trades | A row on which the blackout column is true places no entry, and one where it is null places it |
| [S-template-057](S-template-057.yaml) | trades | With max_trades_per_day 2 a third entry waits for the next trade date |
| [S-template-058](S-template-058.yaml) | trades | With max_losses_per_day 1 a losing trade stops the day's entries, and the next day enters again |
| [S-template-059](S-template-059.yaml) | trades | With daily_loss_stop 100 a loss of 162.50 stops the day's entries |
| [S-template-060](S-template-060.yaml) | trades | With profit_lock 100 a win of exactly 100 stops the day's entries |
| [S-template-061](S-template-061.yaml) | trades | After a losing trade, cooldown_after_loss of 2 bars skips the decision that counts it and the next |
| [S-template-062](S-template-062.yaml) | trades | After a losing trade closed at 14:30:30, cooldown_after_loss of 3 minutes skips the decisions before 14:33:30 |
| [S-template-063](S-template-063.yaml) | trades | A winning trade starts no cooldown, so the next decision enters at once |
| [S-template-064](S-template-064.yaml) | trades | With fresh_signal a long_entry still true after an exit does not enter again until it turns false and back |
| [S-template-065](S-template-065.yaml) | trades | A notional size of 600,000 USD buys the 2 lots of ES worth at most that at the mark |
| [S-template-066](S-template-066.yaml) | trades | A risk of 500 USD over a stop of 12 ticks, 150 USD a lot, buys 3 lots |
| [S-template-067](S-template-067.yaml) | trades | A risk of 1 % of equity buys 3 lots, and after a win of 10,500 USD the next entry buys 4 |
| [S-template-068](S-template-068.yaml) | trades | A risk of 1,000 USD over a stop at the row's stop_price 5 points under the mark buys 4 lots |
| [S-template-069](S-template-069.yaml) | trades | A size that rounds to no lots places no entry and the log says why; the next row's size enters |
| [S-template-070](S-template-070.yaml) | trades | A notional size of 1,000 USD buys 16 lots of 0.001 BTC at 60,000, in whole lot steps |
| [S-template-071](S-template-071.yaml) | trades | A notional size of 3 lots times a size_mult of 1.5 rounds down to 4 lots |
| [S-template-072](S-template-072.yaml) | trades | A trailing stop held a tick under the mark at a decision rises on later trades below its best price, which skipping must replay |
| [S-template-073](S-template-073.yaml) | trades | A breakeven held a tick under the trade that fires it rises to its level once the market allows |
| [S-template-074](S-template-074.yaml) | trades | A limit entry resting past a decision trails from its fill by the entry row's ATR, then by a later decision's |
| [S-template-075](S-template-075.yaml) | trades | Breakeven moves a stepped trailing stop off its steps, and the trailing stop steps on from where the stop stands |
| [S-template-076](S-template-076.yaml) | trades | A notional size rounds to whole lots before size_mult, so 16.67 lots times 2 make 32, not 33 |
| [S-template-077](S-template-077.yaml) | trades | A trade flat before costs loses its two fees, which meet daily_loss_stop and stop the day's entries |
| [S-template-078](S-template-078.yaml) | trades | Funding paid while a trade is open counts in its loss, which meets daily_loss_stop |
| [S-template-079](S-template-079.yaml) | trades | Across a roll a template's exit plan keeps its fill price in the new front's prices, so breakeven moves its stop where it would |
| [S-template-080](S-template-080.yaml) | trades | A signal exit on its way across a roll does the close leg's work on the old contract, and the roll sends no legs |
