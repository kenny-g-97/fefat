# Fill semantics

This is the normative specification of how FEFAT's engines activate and fill orders. The Python reference engine (step 2.2) implements it rule by rule, and the Rust engine (steps 2.6 to 2.9) must match the reference exactly (D-07, D-10, [ADR-0005](../adr/0005-bar-close-decisions-finest-data-fills.md), [ADR-0008](../adr/0008-fill-spec-scenarios-reference-engine.md)). The scenarios in [`fixtures/scenarios/`](../../fixtures/scenarios/README.md) apply it to short tapes you can check with a calculator. When a scenario and this document disagree, this document changes first, with you, and then the scenario; an expected value is never edited to match code.

Written in step 2.1 (2026-10-22) from [`02-engine-and-data.md`](../masterplan/02-engine-and-data.md) §3 and §4, your answers at the Phase 2 kickoff (D-51), and CME's stop rule, and revised after the step's engine-accuracy review. Rules marked _proposed_ fill gaps the design left open; they wait for your sign-off in §18.

## 1. How to read it

- Every rule has an identifier, such as F-STP-03. The engines name the rule that priced each fill they make, and the scenarios cite the rules they exercise. Identifiers are never renumbered or reused.
- Each rule is written for the buy side. Sells mirror it: below for above, the bid for the ask, the low for the high, minus for plus, the lower of two prices for the higher.
- Prices are written as decimals. The engines count them as integers in 1e-9 units of the quote currency (5,432.25 is 5,432,250,000,000), money in micro-units of its currency, quantities in the instrument's lot steps, and instants in nanoseconds since the Unix epoch, UTC, so the two engines compare integers (ADR-0019; Phase 2's conventions).
- A tick is the instrument's tick size: 0.25 for ES and MES, 0.10 for BTCUSDT-PERP. Order prices lie on the tick: the execution template rounds the prices it computes to the tick (step 2.8), and a run or a scenario refuses any other.
- Each rule names its source in brackets: _design_ (`02` §3 or §4), _D-51_ (your kickoff answers), _CME_, or _proposed_.

## 2. Words

| Word | Meaning |
| --- | --- |
| Order class | Market, stop-market (a stop), or limit. Stop-limit orders wait for event strategies (`02` §2.1). |
| Fidelity | The data an order fills on, for a day: `tbbo` (trades, each with the best bid and ask just before it), `trades` (trade prints alone), or bars of a timeframe, `1s`, `1m`, or an import's coarser `5m` or `1d`. The engine uses the finest the day has (`02` §1.6). |
| Record | One trade print, one TBBO record, or one stored bar. |
| Tape | The records of a run or a scenario, in the order the engine reads them. |
| Decision | A strategy's choice at a bar close, which places orders. |
| Activation | The instant from which an order can fill (F-ACT-01). |
| Trigger | The moment a stop becomes a market order (F-STP-01). |
| Pseudo-tick | One of the four prices a bar is replayed as (F-BAR-01). |
| Gap | A jump of the price past an order's level without a trade at the level: between two records, between a bar and the next bar's open, or across a session break (§9). |
| Bracket | A stop and a target attached to an entry and placed when it fills, as one OCO group (F-OCO-02). |
| OCO group | Orders of which only one may fill: the first fill cancels the others. |
| Slippage ticks | Whole ticks by which a market or stop-market fill is worse than its reference price (F-SLP-01). |
| Mark | The price an open position is valued at, for equity and trade paths (F-MRK-01). |
| Run settings | What every run records: the latency (100 ms), the slippage ticks per order class (one on trades and bars, none on TBBO), the limit fill (`through`), the fee table, and, for perpetuals, the funding rates. |

## 3. Clock and order of events (F-CLK)

**F-CLK-01** (design) The engine's clock is the instant a record became available: `ts_recv` for trades and TBBO records, never the exchange's `ts_event`, and `ts_close` for bars. Every rule reads time on this clock, so nothing acts on a record before it was received (`02` §1.1, ADR-0006).

**F-CLK-02** (design, proposed bar order) Events at one instant are handled in this order: the pseudo-ticks of the bars that close at that instant, whose trades all came before it (F-BAR-06); session and timer events (a session's open and close, funding); order activations; the trades and TBBO records received at that instant; then the bar-close decision. A bar `[t, t+Δ)` closes after every event before `t+Δ` (`02` §4). Putting bars first keeps their fills before a funding payment or a session close at their close, where their trades were.

**F-CLK-03** (proposed) Records received at the same instant are read in the order the data holds them, the vendor's order, which a scenario writes as the order of its tape.

## 4. Activation (F-ACT)

**F-ACT-01** (design, D-51) An order decided at a bar close becomes active at that close plus the run's latency, 100 ms by default. On trades and TBBO it triggers and fills only on records received after the decision that placed it and at or after its activation: a record at the activation instant counts, since activations come before the records of their instant (F-CLK-02). On bars, F-ACT-02 decides which bars it sees.

**F-ACT-02** (proposed) On bars, an order decided at a bar close sees the first bar whose `ts_close` is after its activation, from that bar's open on, and every later bar. A bar cannot show what traded before the activation inside it, so it counts whole. A bar that closes at or before the activation, at the activation instant included, is never seen, so an order without latency never sees the bar it was decided on. A bracket placed at its entry's fill inside a bar works on the rest of that bar's path instead (F-OCO-02).

## 5. Market orders (F-MKT)

**F-MKT-01** (design, D-51) On TBBO, a buy market order fills at the ask of the first record at or after its activation, plus the market slippage ticks, none by default: TBBO fills at the quote.

**F-MKT-02** (design, D-51) On trades, a buy market order fills at the price of the first trade at or after its activation, plus the market slippage ticks, one by default, whatever that trade's aggressor side.

**F-MKT-03** (design, D-51) On bars, a buy market order fills at the open of the first bar it sees (F-ACT-02), plus the market slippage ticks, one by default.

## 6. Stop-market orders (F-STP)

**F-STP-01** (CME, design) A buy stop at S triggers on the first price at or above S that it sees after its activation: on trades and TBBO, a record's trade price; on bars, the bar's path reaching S, at its open or on the way to its high (F-BAR-01). CME triggers a stop when "the market trades at or through the stop trigger price" ([CME Globex order types](https://www.cmegroup.com/confluence/display/EPICSANDBOX/Order+Types+for+Futures+and+Options)).

**F-STP-02** (design, D-51) On TBBO, a triggered buy stop fills at the ask of the next tradeable record after the trigger record (F-SES-02), and never below S plus the stop slippage ticks (none by default): at the higher of the two.

**F-STP-03** (design, D-51, your choice of 2026-10-21) On trades, a triggered buy stop fills at the higher of S plus the stop slippage ticks (one by default) and the trigger trade's price. After a trade at S it fills one tick above S; when the market jumps past S, it fills at the first trade past it, the gap price, with no ticks added beyond it. A sell stop at 4995.00 whose next trade prints 4990.25 fills at the lower of 4994.75 and 4990.25: 4990.25.

**F-STP-04** (design, D-51) On bars, a triggered buy stop fills at S plus the stop slippage ticks (one by default) when the path reaches S inside the bar, and at the higher of that price and the bar's open when the bar opens at or above S (a gap at the open).

**F-STP-05** (proposed) A stop is accepted at any price. A buy stop at or below the market when it becomes active, which CME would refuse, fills at once as a market order would, taking the larger of the stop and the market slippage ticks, so it never fills better than a market order placed beside it. For an order decided at a bar close, the market is the last tradeable trade or bar close before its activation, its mark (F-MRK-01); for a bracket's stop, it is the market at its entry's fill, before any slippage: the trade price of the record that filled the entry on trades and TBBO, and the entry's point of the path on bars. On trades and TBBO such a stop fills on the first record it sees, by F-MKT-01 or F-MKT-02; on bars, a stop decided at a close fills by F-MKT-03, and a bracket's stop at its entry's point of the path, that price moved by the ticks. A stop on the right side of the market when it becomes active fills by F-STP-02 to F-STP-04, gap or not; with no price seen yet, a stop is on the right side.

## 7. Limit orders (F-LMT)

**F-LMT-01** (design, D-51) A buy limit at L fills when the market trades through L after its activation: on trades, a trade below L; on TBBO, a trade below L, or a record whose ask is at or below L (a seller offered at the limit); on bars, a path that goes below L, at its open or on the way to its low.

**F-LMT-02** (design option) With the run setting `limit_fill: touch`, a price at L is enough: a trade at or below L (on TBBO also an ask at or below L), or a bar's open or low at or below L. Touch fills are the optimistic bound and the setting of the NautilusTrader comparison (step 2.14); `through` is the default.

**F-LMT-03** (design) A limit fills at its limit price, never better, even when the market jumps past it in its favour: no price improvement. A buy limit above the market therefore fills at its limit, which can be worse than a market order would fill.

**F-LMT-04** (proposed) A limit that fills on the first price it sees, the first record at or after its activation or the open of the first bar it sees, took liquidity: it is a taker. A limit filled later rested on the book: it is a maker. Market and stop-market fills are takers.

## 8. Replaying bars (F-BAR)

On days whose finest data is bars, each bar is replayed as a short path of prices, since a bar does not say in which order its prices traded. For a long held into it, a bar with open 5004.00, high 5013.00, low 5000.50, and close 5008.25 replays as 5004.00, 5000.50, 5013.00, 5008.25.

**F-BAR-01** (design) A bar is replayed as a path through four pseudo-ticks: its open, a first extreme, a second extreme, and its close. Between two pseudo-ticks the price passes every level in between, so a stop or a limit inside the bar is reached at its own price; only the open can jump past a level. Bars cannot show a jump inside them, so a stop inside a bar's range fills at its price plus the slippage ticks even where the market jumped through it, an optimistic reading that the +1 tick rerun bounds.

**F-BAR-02** (design) Holding a position after the open, the first extreme is the adverse one: the low for a long, the high for a short. When the path reaches both a position's stop and its target after the open, the stop fills; a bar that opens through the target fills the target at its open.

**F-BAR-03** (proposed) Flat after the open, the first extreme is the favourable one for the earliest placed working entry, the lower order id among entries placed at one instant: the high for a buy entry, the low for a sell entry. An entry the bar fills is then followed by the move against it (F-BAR-04). With no working entry, nothing can fill and the order does not matter.

**F-BAR-04** (proposed) When an entry fills inside a bar, the extremes the path has not yet reached come next in the order F-BAR-02 gives the new position, the adverse one first, and then the close.

**F-BAR-05** (design, proposed test) A bar is ambiguous when replaying it with its two extremes the other way round would give different fills: another order filled, at another price, or none. Every fill of an ambiguous bar is flagged `ambiguous`, and the run counts them.

**F-BAR-06** (proposed) A bar's pseudo-ticks happen at the bar's `ts_close`, when it is available (F-CLK-01), one after another in path order and before the other events of that instant (F-CLK-02). A fill on a bar carries that time and the bar's own trade date, so a fill on a session's last bar belongs to that session. A fill at the open stamped with `ts_open` would come before the order's activation.

**F-BAR-07** (D-51) Only stored bars are replayed, of the timeframe the day's finest data has: 1-second, 1-minute, or an import's coarser bars (5-minute, daily), which replay like the others. A bucket without trades has no stored bar, so nothing triggers or fills in it: the `zero_volume` rows that `load` adds to the session grid for signals are never replayed.

## 9. Gaps

A gap is the price jumping past an order's level without trading at it. It needs no rule of its own:

- A stop passed by a gap fills at the first price past its level, the gap price, with no slippage ticks added beyond it: F-STP-02 to F-STP-04 take the worse of the stop price moved by the slippage ticks and that first price.
- A stop already at or through its price when it becomes active is no gap: it fills as a market order (F-STP-05).
- A limit passed by a gap in its favour fills at its limit price, not at the better gap price (F-LMT-03).
- A market order takes the first price after its activation, gap or not, plus its ticks (F-MKT-01 to F-MKT-03).
- On bars only the open can jump (F-BAR-01). A session break is a gap like any other: every working order next sees the next session's first record (F-SES-02).

## 10. Sessions and breaks (F-SES)

**F-SES-01** (proposed) Orders are good till cancelled: a working order stays through session breaks, halts, and weekends until it fills, its OCO sibling fills, or its strategy cancels it. The engine cancels nothing at a session's close; the template's time rules (flat-by, no overnight) do, from step 2.8.

**F-SES-02** (proposed) Records received while the market is closed, in the break after a session's close or inside a halt (`02` §1.3, D-43), are not tradeable: trades and TBBO records received there, and bars that open there. Nothing triggers or fills on them, and they set no mark.

## 11. Brackets and OCO groups (F-OCO)

**F-OCO-01** (design, proposed tie) When an order of an OCO group fills, the others are cancelled at once: the record or pseudo-tick that filled it cannot fill them. When one trade or TBBO record would fill both a stop and a limit of one group, the stop fills; on bars, the path decides (F-BAR-01, F-BAR-02).

**F-OCO-02** (proposed) A bracket's stop and target are placed when their entry fills, as one OCO group for the whole position, and work from the next record after the entry's fill; on bars, from the entry's point on the path (F-BAR-04). They take no latency, as brackets held at the broker or the exchange do, so a latency rerun does not delay them.

## 12. Slippage (F-SLP)

**F-SLP-01** (design, D-51) Slippage is a whole number of ticks per order class, market and stop-market, set for each run and recorded in it: by default one tick on trades and on bars of every timeframe, and none on TBBO, which fills at the quote. Limits never slip (F-LMT-03). The +1 tick rerun every report includes (`02` §7) adds one tick to both classes on every fidelity. The ticks may carry a fill beyond every price traded in its interval (a buy stop at a bar's high fills a tick above it), as a quote or a limit's own price may, and a fill is never clamped into that range. What holds for every fill is that it lies on the costly side of the prices traded in its interval: a buy never fills below the lowest of them, a sell never above the highest.

## 13. Quantities (F-QTY)

**F-QTY-01** (design, proposed flag) Orders fill whole, never in part. On trades and TBBO, a fill whose quantity exceeds the size its record shows is flagged `size_exceeded`, and the run counts such fills: on TBBO, the size at the quote a market or stop-market fill takes (the ask size for a buy), or the ask's size for a limit the ask filled; otherwise, the size of the trade that filled the order. Sizes count the dataset's size unit, which is the instrument's lot step.

## 14. Fees, funding, and money (F-FEE, F-FND)

**F-FEE-01** (design, D-51) A futures fill pays the charge per contract per side of the run's fee table, from the schedule in force on the fill's trade date. A trade date before the table's first schedule takes that schedule, with a warning in the run. A scenario states the charge of the schedule in force.

**F-FEE-02** (design) A crypto fill pays basis points of the size of its value, |price × quantity × point value|: the maker rate for a limit that rested, the taker rate for every other fill (F-LMT-04).

**F-FEE-03** (proposed) Every amount the engine books, a fill's value, a fee, or a funding payment, is worked out exactly, wider than 64 bits where the product needs it, and rounded to the micro-unit toward minus infinity of the trader's cash: what the trader pays rounds up, what the trader receives rounds down. An amount that does not fit the ledger's money type is an error, never wrapped.

**F-FND-01** (design, proposed mark) At each funding time of a perpetual, an open position pays its signed quantity (positive long, negative short) × the mark (F-MRK-01) × point value × the funding rate: a positive amount is paid and a negative one received, so with a positive rate a long pays and a short receives, as on Binance. Funding is a timer event: a bar closing at the funding time comes before it, and a trade received at that instant after it (F-CLK-02). A funding time inside a bar, on daily bars for instance, sees the position as it stood before the bar, whose fills happen at its close.

## 15. Marking open positions (F-MRK)

**F-MRK-01** (step 2.1's prompt, proposed detail) An open position is marked at the last trade the engine has seen at the day's fidelity: on TBBO and trades days the last trade's price, on bar days the last pseudo-tick, so at a bar's close the bar's close. A fill does not move the mark, so a position shows its entry's slippage at once, and records that are not tradeable set none (F-SES-02). Equity is cash plus the open position's value at its mark, signed quantity × mark × point value, rounded like any amount (F-FEE-03), a fill's value having moved cash the other way.

On bar days the order of a bar's extremes is assumed (F-BAR-02 to F-BAR-04), and for a rule that measures a fall from a peak, such as a prop firm's trailing drawdown, the adverse-first path can be the kind one. When a bar takes a long to a new high and its low lies below its close, the path records a fall from that high to the close, while the bar allows a fall from the high to its low. Trade paths therefore keep that order open: step 2.13 records the bars in which a position reaches a new favourable extreme while the bar's adverse extreme lies beyond its close (for a long, a low below the close), and the prop simulator takes the order worst for each rule there, as it does for imported excursions (`03-prop-simulator.md` §4.3).

## 16. What every fill records (F-TAG)

**F-TAG-01** (design) Every fill records the fidelity of the data that priced it (`tbbo`, `trades`, or the bars' timeframe: `1s`, `1m`, `5m`, `1d`), the rule that priced it (one of F-MKT-01 to F-MKT-03, F-STP-02 to F-STP-05, and F-LMT-03), its flags (`ambiguous`, `size_exceeded`), its liquidity (maker or taker), its fee, and its slippage: how many ticks worse than its reference it is, the reference being the price before ticks of a market order or of a stop filled as one (F-STP-05), a triggered stop's price, or a limit's price.

## 17. Order type by fidelity

The rules that decide each order type's fill on each fidelity:

| Order | `tbbo` | `trades` | `1s` | `1m` | coarser (`5m`, `1d`) |
| --- | --- | --- | --- | --- | --- |
| Market | F-MKT-01 | F-MKT-02 | F-MKT-03 | F-MKT-03 | F-MKT-03, F-BAR-07 |
| Stop-market | F-STP-01, F-STP-02, F-STP-05 | F-STP-01, F-STP-03, F-STP-05 | F-STP-01, F-STP-04, F-STP-05 | F-STP-01, F-STP-04, F-STP-05 | F-STP-01, F-STP-04, F-STP-05, F-BAR-07 |
| Limit | F-LMT-01, F-LMT-03 | F-LMT-01, F-LMT-03 | F-LMT-01, F-LMT-03 | F-LMT-01, F-LMT-03 | F-LMT-01, F-LMT-03, F-BAR-07 |

Every cell also follows F-CLK-01 to F-CLK-03, F-ACT-01, F-SLP-01, F-QTY-01, F-SES-01, F-SES-02, F-OCO-01, F-OCO-02, F-TAG-01, and the costs and marks of §14 and §15. The three bar columns also follow F-ACT-02 and F-BAR-01 to F-BAR-06.

## 18. Sign-off

The defaults below are what every run uses unless its settings say otherwise, and each run records the settings it used. The first rows come from your answers at the kickoff (D-51). Your sign-off on the pull request is recorded in the last column, with its date.

| Default | Rules | Source | Alternatives | Signed off |
| --- | --- | --- | --- | --- |
| An order becomes active 100 ms after the bar close that decided it. On bar days a latency rerun moves a fill only when the latency passes a bar's close. | F-ACT-01 | D-51 | Any latency: none in the NautilusTrader profile, 1 s in the stress rerun. | |
| Market and stop-market fills slip one tick on trades and bars and none on TBBO, which fills at the quote; ticks per order class are a run setting. | F-SLP-01, F-MKT-01, F-MKT-02, F-MKT-03 | D-51 | The design's rule by aggressor side on trades: no tick after a trade by a buyer, for a buy (`BACKLOG.md`). | |
| A limit fills only when the market trades through its price. | F-LMT-01 | D-51 | Touch (F-LMT-02). | |
| Bars coarser than a minute replay like 1-minute bars, and a bucket without trades fills nothing. | F-BAR-07 | D-51 | | |
| A trade date before a fee table's first schedule takes that schedule, with a warning in the run. | F-FEE-01 | D-51 | Refuse the run. | |
| A triggered stop fills at the worse of its price plus the ticks and the price that triggered it (on TBBO, the next record's quote), so a gap fills at the gap price with no ticks beyond it. | F-STP-02, F-STP-03, F-STP-04 | design, your choice of 2026-10-21 | The design table's gap price plus one tick; on trades, the next trade's price, as TBBO takes the next record's quote. | |
| A limit fills at its price, never better, even above the market. | F-LMT-03 | design | | |
| Holding a position, a bar's adverse extreme comes first, so a stop beats a target in one bar. | F-BAR-02 | design | | |
| Between its pseudo-ticks a bar passes every price, so a stop inside it fills at its price plus the ticks. | F-BAR-01 | design | | |
| Records received at one instant keep the vendor's order. | F-CLK-03 | proposed | | |
| The bars that close at an instant come before its other events, and their fills keep the bar's trade date. | F-CLK-02, F-BAR-06 | proposed | | |
| On bars, an order decided at a close sees the first bar closing after its activation, whole from its open; a bracket works on the rest of its entry's bar. | F-ACT-02 | proposed | | |
| A stop at or through the market when it becomes active fills at once as a market order, with the larger of the two classes' ticks; for a bracket's stop, the market is the price at its entry's fill before slippage, the trade's price or the entry's point of a bar's path. | F-STP-05 | proposed | Refuse it, as CME does. | |
| A limit filled on the first price it sees is a taker, any later one a maker. | F-LMT-04 | proposed | | |
| Flat, a bar's extreme favourable to the earliest placed working entry comes first, the lower order id breaking ties. | F-BAR-03 | proposed | The extreme nearer the open first. | |
| After an entry inside a bar, the extremes not yet reached come adverse first. | F-BAR-04 | proposed | | |
| A bar whose fills would differ with its extremes swapped flags every fill `ambiguous`, and the run counts them. | F-BAR-05 | design, proposed test | | |
| Working orders stay through breaks and weekends; the engine cancels nothing at a close. | F-SES-01 | proposed | Day orders, cancelled at each session's close. | |
| Records received in a break or a halt are not tradeable. | F-SES-02 | proposed | | |
| When one trade or TBBO record would fill a stop and a limit of one group, the stop fills; on bars the path decides. | F-OCO-01 | design, proposed tie | | |
| A bracket's legs work from the record after their entry's fill, without latency. | F-OCO-02 | proposed | | |
| Orders fill whole; on trades and TBBO, a fill larger than its record's size is flagged. | F-QTY-01 | design, proposed flag | A volume or queue model (`BACKLOG.md`). | |
| Every amount of money rounds to the micro-unit against the trader, and none wraps. | F-FEE-03 | proposed | Halves away from zero. | |
| Funding is paid on the signed quantity at the last trade, a long paying a positive rate. | F-FND-01 | design, proposed mark | The venue's own mark price, once imported. | |
| Positions are marked at the last trade, on bar days at the pseudo-ticks; a fill does not move the mark. On bar days, trade paths flag the bars whose order could change a drawdown (§15). | F-MRK-01 | step 2.1's prompt, proposed detail | The bid for a long and the ask for a short on TBBO days (`BACKLOG.md`). | |

How the rules answer the red-flag checklist of the `backtest-expert` skill (`references/failed_tests.md` §4), for the items that concern fills:

| Red flag | How the rules answer it |
| --- | --- |
| Realistic commissions included? | Every fill pays the run's dated fee table (F-FEE-01 to F-FEE-03); a run names its table (`02` §1.2). |
| Slippage modelled conservatively (1.5 to 2 times typical)? | One tick on every market and stop fill outside TBBO (F-SLP-01); the +1 tick rerun of every report doubles it. |
| Worst-case fills considered? | Mostly: limits need a trade through their price (F-LMT-01) and never improve (F-LMT-03), a stop placed through the market fills no better than a market order (F-STP-05), and bars put the adverse extreme first and flag what their order decided (F-BAR-02 to F-BAR-05). Three readings are kinder than the skill's worst case: a gap fills at the gap price without its extra tick (your choice of 2026-10-21), a stop on trades fills from the trigger trade rather than the next one (F-STP-03), and a jump inside a bar is not seen (F-BAR-01). The +1 tick rerun covers them. |
| Order rejection and partial fills addressed? | In part: orders fill whole, and a fill larger than its record's size is flagged (F-QTY-01). Rejections are not modelled (F-STP-05 fills a stop CME would refuse as a market order), and neither are partial fills. |
| Aware of the platform's interpolation? | The bar path is written down (F-BAR-01 to F-BAR-06), every fill names its fidelity (F-TAG-01), so reports split results by it, and trade paths flag the bars whose order could change a drawdown (§15). |
| How low liquidity is handled? | A minute without trades fills nothing (F-BAR-07), and a fill larger than its record's size is flagged (F-QTY-01); queue position and market impact are not modelled beyond the slippage ticks and trade-through. |
| Quirks of the data provider? | The engine's clock is the receive time (F-CLK-01), and prints received in breaks and halts are not tradeable (F-SES-02). |
| Data alignment correct, no look-ahead? | Nothing fills before it is known: activation follows the decision (F-ACT-01), bars are seen whole only after the activation (F-ACT-02), and their fills happen at their close (F-BAR-06). |

## 19. Not in this specification

- Rolls: a position held across a roll is transferred at the first event of the new front's first session, both legs at market and costed (step 2.9, D-44); step 2.9 also says what happens to working orders across a roll.
- Trailing stops, breakeven, several targets, time exits, entry filters, sizing, and the rounding of computed order prices to the tick (step 2.8).
- The NautilusTrader compatibility profile: touch fills, no slippage ticks, no latency, and Nautilus's own bar path (step 2.14).
- Stop-limit orders (event strategies, Phase 9), partial fills, a queue or volume model for limits, and order rejections.
