# FEFAT against NautilusTrader and NinjaTrader 8

Written by `just xcheck` on 2026-10-31 (step 2.14, `02-engine-and-data.md` §8 item 5, D-51, D-59): the same strategies on MESU2026 from 2026-08-03 to 2026-08-31, deciding on 5-minute closes and filling on 1-minute bars, FEFAT under the compatibility profile (touch fills, no slippage ticks, no latency, FEFAT's own bar path), and the market strategy on MNQU2026 against NinjaTrader 8. Trades are matched by the decision that entered them and their side. Each engine's trade is held to a replay of its own documented rules on the 1-minute bars (`fefat_xcheck.replay`), so a difference is explained only where both fills are what the rules give, and every explained difference falls into a class below. A market entry and a flat-by exit are compared by their prices, since their stamps are a convention of their own (`bar_boundary`); every other fill by its price and its bar. A pair is exact when both its fills match.

## Versions and data

- FEFAT: engine 8, fill model 1, artifact schema 2 (crate 0.0.1, SDK 0.0.1).
- NautilusTrader 1.231.0.
- Data: `databento/ohlcv-1m/root=MES`, contract MESU2026, trade dates 2026-08-03 to 2026-08-31; the store snapshot of the request 2026-07-31 to 2026-08-31 (ADR-0019), the one each run pinned: `76404e438da6c161b37d913aae048a74867f6270ef87c9bfdf080deeaa2f3c58`.
- The raw Databento batch file `glbx-mdp3-20100606-20260922.ohlcv-1m.dbn` (DBN 3, revised 2026-09-23): SHA-256 `86475f1c366dc93dc7988f6e8f8aa6fc788ba975a136cbc56f4474a54f74f44a`, the vendor's `86475f1c366dc93dc7988f6e8f8aa6fc788ba975a136cbc56f4474a54f74f44a`. The month cut NautilusTrader read, `MESU2026-2026-07-30-2026-08-31-86475f1c366d.dbn.zst` (2026-07-30 to 2026-09-01, the raw file's own metadata): SHA-256 `2da394910f9b47d1191a1add4ad27bd4b0fe07c7b3860b215998110b89f99562`.
- Profile: fidelity 1m, latency 0 ms, slippage 0 ticks on market and 0 on stop orders, limit fill touch; fee table retail-default (0.94 per contract per side on the window), not compared: fills do not depend on fees with fixed sizing, and the gross profit and loss is compared.

## The strategies

- `market`: long when the 5-minute close is above the previous close, short when below; the entry is a market order; one lot; a stop 12 ticks and a target 12 ticks from the signal bar's close, one OCO group; entries from 08:35 to 14:30 America/Chicago, flat-by 15:00, so the engines start each trade date flat together.
- `limit`: long when the 5-minute close is above the previous close, short when below; the entry is a limit 2 ticks from the close, cancelled at the next decision if unfilled (1 bar to live); one lot; a stop 12 ticks and a target 12 ticks from the signal bar's close, one OCO group; entries from 08:35 to 14:30 America/Chicago, flat-by 15:00, so the engines start each trade date flat together.
- `stop`: long when the 5-minute close is above the previous close, short when below; the entry is a stop 2 ticks from the close, cancelled at the next decision if unfilled (1 bar to live); one lot; a stop 12 ticks and a target 12 ticks from the signal bar's close, one OCO group; entries from 08:35 to 14:30 America/Chicago, flat-by 15:00, so the engines start each trade date flat together.

## NautilusTrader

- NautilusTrader 1.231.0.
- Venue GLBX: OMS NETTING, MARGIN account, `bar_execution` True, fill model `prob_fill_on_limit` 1.0 and `prob_slippage` 0.0, fee model PerContractFeeModel(0 USD), no latency model, `reject_stop_orders` False (a stop through the market fills at once, as F-STP-05 fills it), `bar_adaptive_high_low_ordering` off and on.
- Bars: the 1-minute bars of the cut as `MESU6.GLBX-5-MINUTE-LAST-INTERNAL@1-MINUTE-EXTERNAL`'s source, 31,740 loaded, with `time_bars_build_delay` 1 µs so that the 1-minute bar stamped at a 5-minute boundary joins the 5-minute bar closing there, and `time_bars_build_with_no_updates` False.
- Orders: each entry and its stop and target as one bracket list (OCO), the target not post-only, the flat-by a market order closing the position after every working order is cancelled; a resting entry is cancelled at the next decision.
- 1-minute bars identical: 28,980 of 28,980 FEFAT bars of the window equal NautilusTrader's by open, high, low, close, and volume (31,740 bars loaded by NautilusTrader over the cut's dates).
- 5-minute closes identical (market): 5,796 of 5,796 FEFAT decisions on a bar find NautilusTrader's decision at the same instant with the same close; 0 rows of FEFAT's grid are empty buckets without a bar, on which NautilusTrader builds no bar.
- Ambiguous fills (market, NautilusTrader, open-high-low-close): 9 of 9 exits the other bar path took to the other leg (`bar_path`) were flagged ambiguous by FEFAT (F-BAR-05), which flags a fill the swapped order of extremes would change.
- Ambiguous fills (market, NautilusTrader, nearest extreme first): 5 of 5 exits the other bar path took to the other leg (`bar_path`) were flagged ambiguous by FEFAT (F-BAR-05), which flags a fill the swapped order of extremes would change.
- 5-minute closes identical (limit): 5,796 of 5,796 FEFAT decisions on a bar find NautilusTrader's decision at the same instant with the same close; 0 rows of FEFAT's grid are empty buckets without a bar, on which NautilusTrader builds no bar.
- Ambiguous fills (limit, NautilusTrader, open-high-low-close): 2 of 2 exits the other bar path took to the other leg (`bar_path`) were flagged ambiguous by FEFAT (F-BAR-05), which flags a fill the swapped order of extremes would change.
- Ambiguous fills (limit, NautilusTrader, nearest extreme first): 2 of 2 exits the other bar path took to the other leg (`bar_path`) were flagged ambiguous by FEFAT (F-BAR-05), which flags a fill the swapped order of extremes would change.
- 5-minute closes identical (stop): 5,796 of 5,796 FEFAT decisions on a bar find NautilusTrader's decision at the same instant with the same close; 0 rows of FEFAT's grid are empty buckets without a bar, on which NautilusTrader builds no bar.
- Ambiguous fills (stop, NautilusTrader, open-high-low-close): 2 of 2 exits the other bar path took to the other leg (`bar_path`) were flagged ambiguous by FEFAT (F-BAR-05), which flags a fill the swapped order of extremes would change.
- Ambiguous fills (stop, NautilusTrader, nearest extreme first): 1 of 1 exits the other bar path took to the other leg (`bar_path`) were flagged ambiguous by FEFAT (F-BAR-05), which flags a fill the swapped order of extremes would change.

### Trades

| Strategy | Bar path | FEFAT | Other | Matched | Exact | Exact of matched | bar_boundary | bar_path | entry_bar_path | leg_released_through | gap_limit_clamped | cascade | unknown |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| market | NautilusTrader, open-high-low-close | 1007 | 1007 | 1007 | 540 | 53.6% | 463 | 4 | 0 | 0 | 0 | 0 | 0 |
| market | NautilusTrader, nearest extreme first | 1007 | 1007 | 1007 | 542 | 53.8% | 463 | 2 | 0 | 0 | 0 | 0 | 0 |
| limit | NautilusTrader, open-high-low-close | 909 | 910 | 909 | 768 | 84.5% | 0 | 2 | 26 | 113 | 0 | 1 | 0 |
| limit | NautilusTrader, nearest extreme first | 909 | 911 | 909 | 759 | 83.5% | 0 | 2 | 35 | 113 | 0 | 2 | 0 |
| stop | NautilusTrader, open-high-low-close | 912 | 907 | 907 | 778 | 85.8% | 0 | 2 | 30 | 97 | 0 | 5 | 0 |
| stop | NautilusTrader, nearest extreme first | 912 | 906 | 906 | 793 | 87.5% | 0 | 1 | 16 | 96 | 0 | 6 | 0 |

### Fills

| Strategy | Bar path | Fills compared | Equal | Equal of compared | bar_boundary | bar_path | entry_bar_path | leg_released_through | gap_limit_clamped | cascade | unknown |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| market | NautilusTrader, open-high-low-close | 2014 | 1542 | 76.6% | 463 | 9 | 0 | 0 | 0 | 0 | 0 |
| market | NautilusTrader, nearest extreme first | 2014 | 1546 | 76.8% | 463 | 5 | 0 | 0 | 0 | 0 | 0 |
| limit | NautilusTrader, open-high-low-close | 1818 | 1677 | 92.2% | 0 | 2 | 26 | 113 | 0 | 0 | 0 |
| limit | NautilusTrader, nearest extreme first | 1818 | 1668 | 91.7% | 0 | 2 | 35 | 113 | 0 | 0 | 0 |
| stop | NautilusTrader, open-high-low-close | 1814 | 1685 | 92.9% | 0 | 2 | 30 | 97 | 0 | 0 | 0 |
| stop | NautilusTrader, nearest extreme first | 1812 | 1699 | 93.8% | 0 | 1 | 16 | 96 | 0 | 0 | 0 |

### Gross profit and loss

| Strategy | Bar path | FEFAT (USD) | Other (USD) |
| --- | --- | ---: | ---: |
| market | NautilusTrader, open-high-low-close | -867.50 | -585.00 |
| market | NautilusTrader, nearest extreme first | -867.50 | -705.00 |
| limit | NautilusTrader, open-high-low-close | -352.50 | -925.00 |
| limit | NautilusTrader, nearest extreme first | -352.50 | -847.50 |
| stop | NautilusTrader, open-high-low-close | -1,531.25 | -257.50 |
| stop | NautilusTrader, nearest extreme first | -1,531.25 | -361.25 |

### Examples

- `market`, NautilusTrader, open-high-low-close, `bar_boundary`: the long decided at 2026-08-03 14:00 UTC, entry bar_boundary; exit stop against stop: match; FEFAT less the other engine: entry +3 ticks.
- `market`, NautilusTrader, open-high-low-close, `bar_path`: the long decided at 2026-08-07 13:45 UTC, entry match; exit stop against target: bar_path; FEFAT less the other engine: exit -24 ticks.
- `market`, NautilusTrader, nearest extreme first, `bar_boundary`: the long decided at 2026-08-03 14:00 UTC, entry bar_boundary; exit stop against stop: match; FEFAT less the other engine: entry +3 ticks.
- `market`, NautilusTrader, nearest extreme first, `bar_path`: the long decided at 2026-08-07 13:45 UTC, entry match; exit stop against target: bar_path; FEFAT less the other engine: exit -24 ticks.
- `limit`, NautilusTrader, open-high-low-close, `bar_path`: the long decided at 2026-08-07 14:10 UTC, entry match; exit stop against target: bar_path; FEFAT less the other engine: exit -24 ticks.
- `limit`, NautilusTrader, open-high-low-close, `entry_bar_path`: the short decided at 2026-08-04 18:00 UTC, entry match; exit target against target: entry_bar_path; FEFAT less the other engine: the same prices.
- `limit`, NautilusTrader, open-high-low-close, `leg_released_through`: the long decided at 2026-08-03 13:40 UTC, entry match; exit stop against stop: leg_released_through; FEFAT less the other engine: exit +13 ticks.
- `limit`, NautilusTrader, open-high-low-close, `cascade`: the long decided at 2026-08-17 14:05 UTC, a trade of the other engine alone, FEFAT still in a position at its decision; FEFAT less the other engine: the same prices.
- `limit`, NautilusTrader, nearest extreme first, `bar_path`: the long decided at 2026-08-07 14:10 UTC, entry match; exit stop against target: bar_path; FEFAT less the other engine: exit -24 ticks.
- `limit`, NautilusTrader, nearest extreme first, `entry_bar_path`: the long decided at 2026-08-04 17:05 UTC, entry match; exit target against target: entry_bar_path; FEFAT less the other engine: the same prices.
- `limit`, NautilusTrader, nearest extreme first, `leg_released_through`: the long decided at 2026-08-03 13:40 UTC, entry match; exit stop against stop: leg_released_through; FEFAT less the other engine: exit +13 ticks.
- `limit`, NautilusTrader, nearest extreme first, `cascade`: the long decided at 2026-08-04 17:10 UTC, a trade of the other engine alone, FEFAT still in a position at its decision; FEFAT less the other engine: the same prices.
- `stop`, NautilusTrader, open-high-low-close, `bar_path`: the long decided at 2026-08-06 18:15 UTC, entry match; exit stop against target: bar_path; FEFAT less the other engine: exit -24 ticks.
- `stop`, NautilusTrader, open-high-low-close, `entry_bar_path`: the short decided at 2026-08-03 13:45 UTC, entry match; exit stop against stop: entry_bar_path; FEFAT less the other engine: the same prices.
- `stop`, NautilusTrader, open-high-low-close, `leg_released_through`: the long decided at 2026-08-03 13:35 UTC, entry match; exit target against target: leg_released_through; FEFAT less the other engine: exit -16 ticks.
- `stop`, NautilusTrader, open-high-low-close, `cascade`: the long decided at 2026-08-07 14:10 UTC, a trade of FEFAT alone, the other engine still in a position at its decision; FEFAT less the other engine: the same prices.
- `stop`, NautilusTrader, nearest extreme first, `bar_path`: the long decided at 2026-08-06 18:15 UTC, entry match; exit stop against target: bar_path; FEFAT less the other engine: exit -24 ticks.
- `stop`, NautilusTrader, nearest extreme first, `entry_bar_path`: the long decided at 2026-08-05 13:40 UTC, entry match; exit stop against target: entry_bar_path; FEFAT less the other engine: exit -25 ticks.
- `stop`, NautilusTrader, nearest extreme first, `leg_released_through`: the long decided at 2026-08-03 13:35 UTC, entry match; exit target against target: leg_released_through; FEFAT less the other engine: exit -16 ticks.
- `stop`, NautilusTrader, nearest extreme first, `cascade`: the long decided at 2026-08-06 14:20 UTC, a trade of FEFAT alone, the other engine still in a position at its decision; FEFAT less the other engine: the same prices.

## Difference classes

### `bar_boundary`

A market order decided at a 5-minute close. NautilusTrader settles an order submitted from `on_bar` against the book the bar left, at that bar's close (its backtesting documentation: there is no next-bar-open fill mode). FEFAT activates the order at the close without latency and fills it at the open of the first 1-minute bar after it (F-ACT-02, F-MKT-03), which is also NinjaTrader 8's convention (the builder's spec, H1). The two prices agree whenever the next minute opens at the previous close; the entry and exit levels are set from the signal close, so the bracket is unmoved by it.

### `bar_path`

One later 1-minute bar reached both the stop and the target. FEFAT visits a bar's adverse extreme first while holding a position, so the stop fills (F-BAR-02) and the fill is flagged ambiguous (F-BAR-05). NautilusTrader visits the open, the high, the low, and the close in that order, or with `bar_adaptive_high_low_ordering` the extreme nearer the open first, the low on a tie; NinjaTrader 8 the extreme nearer the open first, the high on a tie (H2). The replay of both paths gives each engine the leg it took.

### `entry_bar_path`

A limit or stop entry filled inside a 1-minute bar, and the two engines visit the rest of the bar in different orders. Flat, FEFAT visits the extreme favourable to the entry first, the high for a buy (F-BAR-03); after the fill, the extremes not yet reached come adverse first, then the close (F-BAR-04), the exit plan working from the entry's point (F-OCO-02). NautilusTrader visits the open, the high, the low, and the close in its fixed or adaptive order whatever the entry, so an extreme FEFAT visited before the fill can come after it there, or the reverse: one engine fills a leg on the rest of the bar while the other carries the position into the next bar, or they fill different legs. The replay of both paths on the entry's bar (`fefat_xcheck.replay`) gives each engine the exit it made.

### `leg_released_through`

A limit or stop entry filled inside a 1-minute bar on a tick already past one of its legs. NautilusTrader releases the stop and the target on the tick that fills the entry, and a leg whose level that tick's price is past fills at that price: a buy limit filled on the low tick has its stop filled at the low, below the stop's level; a buy stop filled on the high tick has its target filled at the high, above the target's level. FEFAT works the legs on the rest of the path from the entry's point and fills a stop at its level (F-STP-04) and a target at its price, never better (F-LMT-03). The replay of both paths gives each engine the price it filled at.

### `gap_limit_clamped`

A bar opened past a resting limit's price in its favour and stayed past it. FEFAT fills the limit at its price, never better and never clamped into the range of prices traded in its interval (F-LMT-03, F-SLP-01); NinjaTrader 8 fills it at its price clamped into the bar, the bar's high for a buy limit or its low for a sell limit, so the fill is better than the limit by the gap (the builder's spec, H4: a limit fills at its own price, also when the bar opens beyond it, clamped into the bar). NautilusTrader fills a resting limit at its price, as FEFAT does.

### `cascade`

A trade one engine made, as its rules give it, while the other still held a position at that decision, after an earlier difference on the same trade date left the two in different states; the flat-by at 15:00 Chicago brings them back together each trade date.

### Classes the data cannot exercise

- **Aggressor-side limit fills.** NautilusTrader fills a resting limit on trade ticks of the aggressor side opposite to it; at bar fidelity there are no trade ticks, and both engines fill a limit on a bar that touches its price (F-LMT-02, `prob_fill_on_limit=1.0`), at the limit price.
- **`ts_recv` ordering.** FEFAT's clock is `ts_recv` (F-CLK-01) and Databento buckets its bars on it; both engines read the vendor's bars stamped at their close (`bars_timestamp_on_close`), so no record is reordered.
- **Roll handling.** MESU2026 and MNQU2026 are the front contracts for the whole window and the FEFAT runs read one contract each and crossed no roll (asserted by `scripts/xcheck.py`), so no engine rolled.

Differences without a class, unknown: 0.

## NinjaTrader 8

- NinjaTrader 8 (the builder's installed platform).
- Strategy Analyzer: `FefatCrossCheck.cs` on MNQ 09-26, a 5-minute series, order fill resolution High on 1-minute bars, slippage 0, limit orders filled on touch, exit on session close off, GTC; the strategy's stop and target are Set() orders at prices from the signal bar's close, its flat-by an exit at the market named `FlatBy`.
- NinjaTrader 8's trades read from `trades.csv`: 1,354 trades, of which 1,354 were decided on a 5-minute close of FEFAT's grid (a market fill stamped with the next minute, H1); commission as exported 0.00 USD, not compared.
- Data: the store's NinjaTrader import of MNQU2026 (`ninjatrader/ohlcv-1m/root=MNQ`, snapshot `9882cbbe70782c9f8fe8eb13691c8b5ed7913c5aa9ab13f04b6ff7d782d33271` of the request 2026-07-31 to 2026-08-31), NinjaTrader's own history exported on 2026-10-13, which the Strategy Analyzer also reads.

### Trades

| Strategy | Bar path | FEFAT | Other | Matched | Exact | Exact of matched | bar_boundary | bar_path | entry_bar_path | leg_released_through | gap_limit_clamped | cascade | unknown |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| market | NinjaTrader 8 | 1354 | 1354 | 1354 | 1293 | 95.5% | 0 | 60 | 0 | 0 | 1 | 0 | 0 |

### Fills

| Strategy | Bar path | Fills compared | Equal | Equal of compared | bar_boundary | bar_path | entry_bar_path | leg_released_through | gap_limit_clamped | cascade | unknown |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| market | NinjaTrader 8 | 2708 | 2647 | 97.7% | 0 | 60 | 0 | 0 | 1 | 0 | 0 |

### Gross profit and loss

| Strategy | Bar path | FEFAT (USD) | Other (USD) |
| --- | --- | ---: | ---: |
| market | NinjaTrader 8 | -4,075.00 | -1,649.50 |

### Examples

- `market`, NinjaTrader 8, `bar_path`: the long decided at 2026-08-03 13:40 UTC, entry match; exit stop against target: bar_path; FEFAT less the other engine: exit -80 ticks.
- `market`, NinjaTrader 8, `gap_limit_clamped`: the short decided at 2026-08-10 16:30 UTC, entry match; exit target against target: gap_limit_clamped; FEFAT less the other engine: exit +51 ticks.

