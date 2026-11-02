# The tick engine on Interactive Brokers' prints

Written by `just tick-check` on 2026-11-02 (step 2.16, `02-engine-and-data.md` §8 items 2 and 4, D-67): the three strategies of step 2.14 on MNQZ2026's sessions from 2026-09-21 to 2026-09-23 in the store's `ibkr` datasets, Interactive Brokers' Time and Sales and its own 1-minute bars, run through the Rust engine at fidelity `trades` and at one minute under step 2.14's compatibility profile, and through the Python reference engine on the same prints and bars. The bars rebuilt from the prints are held to the provider's own and counted against `databento`'s; every fill of the reference engine is the Rust engine's; every fill that differs between the run on prints and its 1-minute rerun has a class; and each run's fills hold on a second run and on its first sessions alone. The report holds counts, rates, timestamps, hashes, and tick differences: no price (D-21).

## Versions and data

- FEFAT: engine 8, fill model 1, artifact schema 2 (crate 0.0.1, SDK 0.0.1).
- Data: `ibkr/ohlcv-1m/root=MNQ`, the store snapshot of the request 2026-09-18 to 2026-09-23 the runs pinned (ADR-0019): `16a8b5807aa251d2487bc918d7ccbdc479d7f5bff89d4f92137e488ff8233e43`.
- Data: `ibkr/trades/root=MNQ`, the store snapshot of the request 2026-09-18 to 2026-09-23 the runs pinned (ADR-0019): `86908b75705df1ecaf11b58d3c4ad7db910f4b5694319a5be294f5e313e1aaf7`.
- Sessions:
  - 2026-09-21: 976,389 prints, filled on trade prints.
  - 2026-09-22: 999,888 prints, filled on trade prints.
  - 2026-09-23: 1,069,604 prints, filled on 1-minute bars: the engine cache leaves its prints out, since its records in the 1m bar opening at 2026-09-23T20:59:00Z add up to 464 lots, not the bar's 463.
- Profile: latency 0 ms, slippage 0 ticks on market and 0 on stop orders, limit fill touch, fee table retail-default; the run on prints at fidelity `trades`, each trade date on its finest cached level (D-58), and the run on bars at `1m`.
- The reference engine replayed a strategy's sessions of prints in about 7.7 s on this PC.

## The strategies

- `market`: long when the 5-minute close is above the previous close, short when below; the entry is a market order; one lot; a stop 40 ticks and a target 40 ticks from the signal bar's close, one OCO group; entries from 08:35 to 14:30 America/Chicago, flat-by 15:00.
- `limit`: long when the 5-minute close is above the previous close, short when below; the entry is a limit 2 ticks from the mark at the decision (F-ENT-02), cancelled at the next decision if unfilled (1 bar to live); one lot; a stop 40 ticks and a target 40 ticks from the signal bar's close, one OCO group; entries from 08:35 to 14:30 America/Chicago, flat-by 15:00.
- `stop`: long when the 5-minute close is above the previous close, short when below; the entry is a stop 2 ticks from the mark at the decision (F-ENT-02), cancelled at the next decision if unfilled (1 bar to live); one lot; a stop 40 ticks and a target 40 ticks from the signal bar's close, one OCO group; entries from 08:35 to 14:30 America/Chicago, flat-by 15:00.

## Bars

`fefat data verify-bars MNQ <date>` rebuilds each session's 1-minute bars from its prints and compares them with `ibkr`'s own. `databento`'s bars of the same minutes are counted against `ibkr`'s: IBKR filters block and spread trades and stamps prints to the second (D-67).

| Session | Rebuilt bars compared | Differences | Columns |
| --- | ---: | ---: | --- |
| 2026-09-21 | 1,379 | 0 | none |
| 2026-09-22 | 1,380 | 0 | none |
| 2026-09-23 | 1,380 | 3 | close, trade_count, volume at 20:59Z |

| Session | Minutes in both | `ibkr`'s alone | `databento`'s alone | Volume differs | A price differs | `ibkr`'s volume of `databento`'s |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2026-09-21 | 1,379 | 0 | 1 | 13 | 9 | 99.50% |
| 2026-09-22 | 1,380 | 0 | 0 | 29 | 24 | 100.00% |
| 2026-09-23 | 1,040 | 0 | 0 | 8 | 3 | 100.00% |

- `databento`'s bars of 2026-09-23 end at 15:20Z, so the later minutes of that session are not compared.

## Reference engine against the Rust engine

The reference engine (`fefat.reference`, D-10) replays each strategy from flat on the sessions on prints, deciding on the run's own signal rows under its fee table, and its fills are held to the Rust engine's field by field: order, instant, price, rule, flags, liquidity, slippage, lots, side, role, fidelity, cash, fee, and contract, in the integer units of ADR-0019.

| Strategy | Sessions | Prints | Decisions | Rust fills | Reference fills | Identical |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| market | 2026-09-21 to 2026-09-22 | 1,976,277 | 552 | 242 | 242 | 242 |
| limit | 2026-09-21 to 2026-09-22 | 1,976,277 | 552 | 238 | 238 | 238 |
| stop | 2026-09-21 to 2026-09-22 | 1,976,277 | 552 | 234 | 234 | 234 |

- The runs on 1-minute bars too: the reference engine replays them on every session's bars, 2026-09-21 to 2026-09-23, and their fills are identical, market 372 of 372, limit 352 of 352, stop 362 of 362.
- On 2026-09-23, of which the engine cache holds no prints, the runs on prints fill on the bars (D-58), and their fills are the runs on bars' fills of it, order ids apart, which number each run's own orders: market 130, limit 128, stop 126.

## Ticks against minutes

The fidelity check at one minute (`fidelity_check`, step 2.12) reruns the sessions on prints from flat on their 1-minute bars under the run's own settings; the run on bars here is that rerun, pair for pair and tick for tick, which the command holds to each other. Trades are matched by the decision that entered them and their side; a fill on prints and a fill on a bar are alike at one price inside the bar's minute.

- `market`: the fidelity check of 2026-09-21 to 2026-09-22 reran 121 trades against the prints' 121: 121 matched pairs, 107 with a fill price moved, 0 of the prints' trades and 0 of its own without a pair.
- `limit`: the fidelity check of 2026-09-21 to 2026-09-22 reran 112 trades against the prints' 119: 110 matched pairs, 99 with a fill price moved, 9 of the prints' trades and 2 of its own without a pair.
- `stop`: the fidelity check of 2026-09-21 to 2026-09-22 reran 118 trades against the prints' 117: 115 matched pairs, 105 with a fill price moved, 2 of the prints' trades and 3 of its own without a pair.

### Trades

| Strategy | Ticks | Minutes | Matched | Exact | Exact of matched | Exits alike of matched | bar_boundary | bar_path | entry_bar_path | stop_through | cascade | unknown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| market | 121 | 121 | 121 | 14 | 11.6% | 97.5% | 107 | 0 | 0 | 0 | 0 | 0 |
| limit | 119 | 112 | 110 | 10 | 9.1% | 90.0% | 110 | 0 | 1 | 0 | 0 | 0 |
| stop | 117 | 118 | 115 | 10 | 8.7% | 94.8% | 109 | 0 | 0 | 1 | 0 | 0 |

### Fills

| Strategy | Fills compared | Equal | Equal of compared | bar_boundary | bar_path | entry_bar_path | stop_through | cascade | unknown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| market | 242 | 132 | 54.5% | 107 | 2 | 0 | 1 | 0 | 0 |
| limit | 220 | 110 | 50.0% | 124 | 1 | 6 | 1 | 0 | 0 |
| stop | 230 | 119 | 51.7% | 117 | 1 | 1 | 2 | 0 | 0 |

Each trade counts once, by its first class; each fill that differs counts once, a pair's entry or exit, and a trade of one run alone with both its fills.

### How far apart

The differing fills of the matched pairs, the fill on prints less the fill on bars in ticks, by class, and how many ticks more the pairs made on prints than on bars, a lot each, long and short alike.

| Strategy | Class | Fills | Mean ticks apart | Largest |
| --- | --- | ---: | ---: | ---: |
| market | `bar_boundary` | 107 | 4.0 | 23 |
| market | `bar_path` | 2 | 80.0 | 80 |
| market | `stop_through` | 1 | 1.0 | 1 |
| limit | `bar_boundary` | 102 | 4.8 | 80 |
| limit | `bar_path` | 1 | 80.0 | 80 |
| limit | `entry_bar_path` | 6 | 40.0 | 80 |
| limit | `stop_through` | 1 | 1.0 | 1 |
| stop | `bar_boundary` | 107 | 4.6 | 64 |
| stop | `bar_path` | 1 | 80.0 | 80 |
| stop | `entry_bar_path` | 1 | 80.0 | 80 |
| stop | `stop_through` | 2 | 1.0 | 1 |

- `market`: over its 121 matched pairs the trades on prints made 163 ticks more than those on bars, 1.35 a trade.
- `limit`: over its 110 matched pairs the trades on prints made 392 ticks more than those on bars, 3.56 a trade.
- `stop`: over its 115 matched pairs the trades on prints made 176 ticks more than those on bars, 1.53 a trade.

### The decision second

541 of the 552 decisions on the sessions on prints have prints stamped at their own instant, 20,514 of the 1,976,277 prints. With those prints moved one nanosecond after their decision, the reference engine's trades on the prints are those on the bars but for the trades below, each classed by where the bar's path parts from the prints; every other difference of the runs on prints from those on bars is the decision second's, `bar_boundary`.

| Strategy | Trades apart | bar_path | entry_bar_path | stop_through | cascade | unknown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| market | 3 | 2 | 0 | 1 | 0 | 0 |
| limit | 9 | 1 | 7 | 1 | 0 | 0 |
| stop | 12 | 1 | 1 | 10 | 0 | 0 |

### Examples

- `market`, `bar_boundary`: the long decided at 2026-09-21T13:35:00Z, entry bar_boundary; exit stop against stop: match; ticks less minutes: entry -3 ticks.
- `limit`, `bar_boundary`: the long decided at 2026-09-21T13:35:00Z, entry bar_boundary; exit stop against stop: match; ticks less minutes: entry -1 ticks.
- `limit`, `entry_bar_path`: the long decided at 2026-09-21T16:20:00Z, entry match; exit target_1 against target_1: entry_bar_path.
- `stop`, `bar_boundary`: the long decided at 2026-09-21T13:35:00Z, entry bar_boundary; exit stop against stop: match; ticks less minutes: entry -1 ticks.
- `stop`, `stop_through`: the long decided at 2026-09-21T16:20:00Z, entry stop_through; exit target_1 against target_1: match; ticks less minutes: entry +1 ticks.

## Determinism

| Strategy | Run key | Key again | Fills | Second run | Saved | Through 2026-09-21 | Through 2026-09-22 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| market | `40adf5c11c28fc95` | equal | `1ef0e8fddd02fe3b` | equal | equal | equal | equal |
| limit | `25fd65d583cfb3ae` | equal | `590ce5e95e695a13` | equal | equal | equal | equal |
| stop | `de7962c4022749dd` | equal | `ecc24b318f6e7345` | equal | equal | equal | equal |

- Each run's key (`02` §4) is worked out again from its inputs. Two fresh runs of the engine give fills of one hash (`fefat_engine.table_hash`), which is the saved run's. The runs on its first sessions alone, fresh from the engine as well, give the whole run's fills of those sessions.
- `market`: 242 of its 242 fills on prints fell in a second holding more than one print. Replayed with each second's prints in the reverse of their stored order, the reference engine makes 104 of its 121 trades otherwise and 104 of its own, so their order matters, and the Rust engine's fills are those of the stored order (F-CLK-03).
- `limit`: 238 of its 238 fills on prints fell in a second holding more than one print. Replayed with each second's prints in the reverse of their stored order, the reference engine makes 111 of its 119 trades otherwise and 107 of its own, so their order matters, and the Rust engine's fills are those of the stored order (F-CLK-03).
- `stop`: 234 of its 234 fills on prints fell in a second holding more than one print. Replayed with each second's prints in the reverse of their stored order, the reference engine makes 101 of its 117 trades otherwise and 101 of its own, so their order matters, and the Rust engine's fills are those of the stored order (F-CLK-03).

## Difference classes

### `bar_boundary`

IBKR stamps its prints to the second, so the prints of the second a 5-minute bar closes in carry the decision's own instant. On prints they are received at the decision, so they come before it (F-CLK-02): the mark at the decision is the last of them, and an order decided there never sees them, so a market order fills on the first print after that second (F-MKT-02). At one minute they open the bar that starts at the decision: the mark is the close of the bar before, and an order decided there sees that bar from its open (F-ACT-02), so a market order fills at its open, the first of them (F-MKT-03). The two runs therefore fill a market entry and a flat-by exit on different prints, place a limit or stop entry from different marks (F-ENT-02), and can reach a resting entry on those prints at the decision that places it on bars alone, or at the decision that cancels it on prints alone (F-ENT-03). A fill is of this class when the reference engine, replaying the prints with each print stamped at a decision's instant moved one nanosecond after it, where the bars put it, fills it otherwise than the prints: those prints alone moved it. A trade of one run alone is of this class too when the replay makes it where the prints do not, or does not make it where they do: the decision second made or prevented it, at once or through a position it left open on one run at a later decision.

### `bar_path`

A 1-minute bar the position was held through reached both legs of the bracket. The bar's path takes the adverse extreme first, so the run on bars filled the stop (F-BAR-02, F-BAR-04) and flagged the fill ambiguous (F-BAR-05), while the prints reached the target first in that minute.

### `entry_bar_path`

A limit or stop entry filled inside a 1-minute bar. After the fill the bar's path visits the extremes it has not reached yet, the adverse one first, then the close (F-BAR-03, F-BAR-04), while the prints after the fill went their own way: one run filled a leg in the entry's minute where the other carried the position out of it.

### `stop_through`

A stop, an entry or a leg, triggered by a print beyond its level that the print before had not reached. On prints it fills at that print, the worse of its level and the trigger (F-STP-03); on the bar's path it fills at its level (F-STP-04).

### `cascade`

A trade of one run alone that the restamped replay makes or misses as the prints do, made at a decision where, of the replay and the bars, the one without it still held a position after an earlier difference of the bar's path on the same trade date. A knock-on of the decision second is `bar_boundary` instead. Flat by 15:00 Chicago, the runs start each trade date together.

### Step 2.14's other classes

`leg_released_through` and `gap_limit_clamped` of step 2.14 name conventions of NautilusTrader and NinjaTrader 8: a leg released on its entry's tick and filled at that tick's price, and a limit filled at its price clamped into a bar that opened past it. Both runs here are FEFAT's, whose legs work from the record after the entry's fill and whose limits fill at their price (F-OCO-02, F-LMT-03), so neither class can arise.

### What the data cannot exercise

- **Aggressor sides and quotes.** IBKR's prints carry no aggressor side and no quotes, so the fills on prints follow FEFAT's rules for trades (F-MKT-02, F-STP-03, F-LMT-02); a run on TBBO is not checked here.
- **Rolls.** The runs read the contract unspliced (`RunConfig.contract`) and cross no roll.
- **Latency, slippage, and limits filled through their price.** The compatibility profile has no latency or slippage and fills a limit on a touch of its price (F-LMT-02); the defaults, 100 ms, one tick, and a limit filled by a print through its price (D-51, F-LMT-01), are not checked here.

Differences without a class, unknown: 0.
