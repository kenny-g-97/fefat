# Fill semantics

This is the normative specification of how FEFAT's engines activate and fill orders. The Python reference engine (step 2.2) implements it rule by rule, and the Rust engine (steps 2.6 to 2.9) must match the reference exactly (D-07, D-10, [ADR-0005](../adr/0005-bar-close-decisions-finest-data-fills.md), [ADR-0008](../adr/0008-fill-spec-scenarios-reference-engine.md)). The scenarios in [`fixtures/scenarios/`](../../fixtures/scenarios/README.md) apply it to short tapes you can check with a calculator. When a scenario and this document disagree, this document changes first, with you, and then the scenario; an expected value is never edited to match code.

Written in step 2.1 (2026-10-22) from [`02-engine-and-data.md`](../masterplan/02-engine-and-data.md) §3 and §4, your answers at the Phase 2 kickoff (D-51), and CME's stop rule, and revised after the step's engine-accuracy review. Rules marked _proposed_ fill gaps the design left open; you signed them off in §18 on 2026-10-26, at step 2.6, and chose two readings of TBBO on 2026-10-27, after the step's engine-accuracy review. Step 2.7 writes down six readings of the bar path and of activation that the reference engine already made (D-52), each pinned by a scenario and marked _proposed in step 2.7_, which you signed off in §18 on 2026-10-27, after the step's reviews. Step 2.8 adds the execution template's rules, §20 to §28, each marked _proposed in step 2.8_ and listed in §18 for your sign-off; four of them carry the choices you made in the step's plan on 2026-10-27.

## 1. How to read it

- Every rule has an identifier, such as F-STP-03. The engines name the rule that priced each fill they make, and the scenarios cite the rules they exercise. Identifiers are never renumbered or reused.
- Each rule is written for the buy side. Sells mirror it: below for above, the bid for the ask, the low for the high, minus for plus, the lower of two prices for the higher.
- Prices are written as decimals. The engines count them as integers in 1e-9 units of the quote currency (5,432.25 is 5,432,250,000,000), money in micro-units of its currency, quantities in the instrument's lot steps, and instants in nanoseconds since the Unix epoch, UTC, so the two engines compare integers (ADR-0019; Phase 2's conventions).
- A tick is the instrument's tick size: 0.25 for ES and MES, 0.10 for BTCUSDT-PERP. Order prices lie on the tick: the execution template rounds the prices it computes to the tick (F-RND-01), and a run or a scenario refuses any other.
- Each rule names its source in brackets: _design_ (`02` §3 or §4), _D-51_ (your kickoff answers), _CME_, or _proposed_.

## 2. Words

| Word | Meaning |
| --- | --- |
| Order class | Market, stop-market (a stop), or limit. Stop-limit orders wait for event strategies (`02` §2.1). |
| Fidelity | The data an order fills on, for a day: `tbbo` (trades, each with the best bid and ask just before it), `trades` (trade prints alone), or bars of a timeframe, `1s`, `1m`, or an import's coarser `5m` or `1d`. The engine uses the finest the day has (`02` §1.6). |
| Record | One trade print, one TBBO record, or one stored bar. |
| Quote | A TBBO record's best bid and ask from just before its trade, read no better than that trade (F-SLP-01). |
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

**F-ACT-01** (design, D-51) An order decided at a bar close becomes active at that close plus the run's latency, 100 ms by default. On trades and TBBO it triggers and fills only on records received after the decision that placed it and at or after its activation: a record at the activation instant counts, since activations come before the records of their instant (F-CLK-02). With no latency, a record received at the decision's own instant comes before the decision (F-CLK-02): the orders it places never see that record, though it sets the mark they are judged against (F-STP-05; proposed in step 2.7, S-fill-054). On bars, F-ACT-02 decides which bars it sees.

**F-ACT-02** (proposed) On bars, an order decided at a bar close sees the first bar whose `ts_close` is after its activation, from that bar's open on, and every later bar. A bar cannot show what traded before the activation inside it, so it counts whole. A bar that closes at or before the activation, at the activation instant included, is never seen, so an order without latency never sees the bar it was decided on. A bracket placed at its entry's fill inside a bar works on the rest of that bar's path instead (F-OCO-02).

## 5. Market orders (F-MKT)

**F-MKT-01** (design, D-51) On TBBO, a buy market order fills at the ask of the first record at or after its activation, plus the market slippage ticks, none by default: TBBO fills at the quote.

**F-MKT-02** (design, D-51) On trades, a buy market order fills at the price of the first trade at or after its activation, plus the market slippage ticks, one by default, whatever that trade's aggressor side.

**F-MKT-03** (design, D-51) On bars, a buy market order fills at the open of the first bar it sees (F-ACT-02), plus the market slippage ticks, one by default.

## 6. Stop-market orders (F-STP)

**F-STP-01** (CME, design) A buy stop at S triggers on the first price at or above S that it sees after its activation: on trades and TBBO, a record's trade price; on bars, the bar's path reaching S, at its open or on the way to its high (F-BAR-01). CME triggers a stop when "the market trades at or through the stop trigger price" ([CME Globex order types](https://www.cmegroup.com/confluence/display/EPICSANDBOX/Order+Types+for+Futures+and+Options)).

**F-STP-02** (design, D-51, your choice of 2026-10-27) On TBBO, a triggered buy stop fills at the ask of the next tradeable record after the trigger record (F-SES-02), and never below S plus the stop slippage ticks (none by default): at the higher of the two. From its trigger the stop is a market order already sent: no decision cancels it, the execution template waits for it as for its own exit, and on that next record it fills before the orders that become active there, a market order of its OCO group among them (S-fill-047, S-template-005).

**F-STP-03** (design, D-51, your choice of 2026-10-21) On trades, a triggered buy stop fills at the higher of S plus the stop slippage ticks (one by default) and the trigger trade's price. After a trade at S it fills one tick above S; when the market jumps past S, it fills at the first trade past it, the gap price, with no ticks added beyond it. A sell stop at 4995.00 whose next trade prints 4990.25 fills at the lower of 4994.75 and 4990.25: 4990.25.

**F-STP-04** (design, D-51) On bars, a triggered buy stop fills at S plus the stop slippage ticks (one by default) when the path reaches S inside the bar, and at the higher of that price and the bar's open when the bar opens at or above S (a gap at the open).

**F-STP-05** (proposed) A stop is accepted at any price. A buy stop at or below the market when it becomes active, which CME would refuse, fills at once as a market order would, taking the larger of the stop and the market slippage ticks, so it never fills better than a market order placed beside it. For an order decided at a bar close, the market is the last tradeable trade or bar close before its activation, its mark (F-MRK-01); for a bracket's stop, it is the market at its entry's fill, before any slippage: the trade price of the record that filled the entry on trades and TBBO, and the entry's point of the path on bars. On trades and TBBO such a stop fills on the first record it sees, by F-MKT-01 or F-MKT-02; on bars, a stop decided at a close fills by F-MKT-03, and a bracket's stop at its entry's point of the path, that price moved by the ticks. A stop on the right side of the market when it becomes active fills by F-STP-02 to F-STP-04, gap or not; with no price seen yet, a stop is on the right side. A stop is judged against the market once, when it becomes active: one through the market then fills as a market order on the first record or bar it sees, even where that bar opens back on its right side (proposed in step 2.7, S-fill-055).

## 7. Limit orders (F-LMT)

**F-LMT-01** (design, D-51) A buy limit at L fills when the market trades through L after its activation: on trades, a trade below L; on TBBO, a trade below L, or a record whose ask is at or below L (a seller offered at the limit); on bars, a path that goes below L, at its open or on the way to its low.

**F-LMT-02** (design option) With the run setting `limit_fill: touch`, a price at L is enough: a trade at or below L (on TBBO also an ask at or below L), or a bar's open or low at or below L. Touch fills are the optimistic bound and the setting of the NautilusTrader comparison (step 2.14); `through` is the default.

**F-LMT-03** (design) A limit fills at its limit price, never better, even when the market jumps past it in its favour: no price improvement. A buy limit above the market therefore fills at its limit, which can be worse than a market order would fill.

**F-LMT-04** (proposed) A limit that fills on the first price it sees, the first record at or after its activation or the open of the first bar it sees, took liquidity: it is a taker. A limit filled later rested on the book: it is a maker. Market and stop-market fills are takers.

## 8. Replaying bars (F-BAR)

On days whose finest data is bars, each bar is replayed as a short path of prices, since a bar does not say in which order its prices traded. For a long held into it, a bar with open 5004.00, high 5013.00, low 5000.50, and close 5008.25 replays as 5004.00, 5000.50, 5013.00, 5008.25.

**F-BAR-01** (design) A bar is replayed as a path through four pseudo-ticks: its open, a first extreme, a second extreme, and its close. Between two pseudo-ticks the price passes every level in between, so a stop or a limit inside the bar is reached at its own price; only the open can jump past a level. Bars cannot show a jump inside them, so a stop inside a bar's range fills at its price plus the slippage ticks even where the market jumped through it, an optimistic reading that the +1 tick rerun bounds.

**F-BAR-02** (design) Holding a position after the open, the first extreme is the adverse one: the low for a long, the high for a short. When the path reaches both a position's stop and its target after the open, the stop fills; a bar that opens through the target fills the target at its open.

**F-BAR-03** (proposed) Flat after the open, the first extreme is the favourable one for the earliest placed working entry, the lower order id among entries placed at one instant: the high for a buy entry, the low for a sell entry. An entry the bar fills is then followed by the move against it (F-BAR-04). With no working entry, nothing can fill and the order does not matter. The entry's side alone decides, whatever its kind: a buy limit, which fills on the way down, puts the high first as a buy stop does (proposed in step 2.7, S-fill-053).

**F-BAR-04** (proposed) When an entry fills inside a bar, the extremes the path has not yet reached come next in the order F-BAR-02 gives the new position, the adverse one first, and then the close. An entry here is a fill that opens a position, from flat or by reversing one (S-fill-042), judged on the position after all the fills at one point of the path: a point whose fills add to a position, close it, or open one and close it again leaves the order as it was, so that after an exit leaves the position flat the path goes on to the extremes it has not reached in the order it had (proposed in step 2.7, S-fill-050, S-fill-057).

**F-BAR-05** (design, proposed test) A bar is ambiguous when replaying it with its two extremes the other way round would give different fills: another order filled, at another price, or none. Only the first choice of extreme is the other way round: an entry that fills on the swapped path is followed by the move against it, by F-BAR-04, as on the real path (proposed in step 2.7, S-fill-056). Every fill of an ambiguous bar is flagged `ambiguous`, and the run counts them.

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

**F-SES-01** (proposed) Orders are good till cancelled: a working order stays through session breaks, halts, and weekends until it fills, its OCO sibling fills, or its strategy cancels it. The engine cancels nothing at a session's close; the execution template's time rules do (F-TIM-01, F-TIM-03).

**F-SES-02** (proposed) Records received while the market is closed, in the break after a session's close or inside a halt (`02` §1.3, D-43), are not tradeable: trades and TBBO records received there, and bars that open there. Nothing triggers or fills on them, and they set no mark.

## 11. Brackets and OCO groups (F-OCO)

**F-OCO-01** (design, proposed tie) When an order of an OCO group fills, the others are cancelled at once: the record or pseudo-tick that filled it cannot fill them. When one trade or TBBO record would fill both a stop and a limit of one group, the stop fills; on bars, the path decides (F-BAR-01, F-BAR-02), and the orders that one point of it fills come in a set order: at a bar's open, first those that see their first bar there, market orders and stops through the market, then the stops the open reaches, then the limits; at a level on the way between pseudo-ticks, the stops it reaches, then the limits; each class by order id. So a bar opening past a stop and a limit of one group fills the stop (S-fill-052), and of two stops of one group through the market when they became active, the lower id (proposed in step 2.7, S-fill-051). On TBBO, the record that triggers a stop does not fill it (F-STP-02), so a limit of its group that the same record fills, by its trade or its quote, fills and cancels the stop.

**F-OCO-02** (proposed) A bracket's stop and target are placed when their entry fills, as one OCO group for the whole position, and work from the next record after the entry's fill; on bars, from the entry's point on the path (F-BAR-04). They take no latency, as brackets held at the broker or the exchange do, so a latency rerun does not delay them. An entry's exit plan places its stop and its targets so, and shares its open lots among them (F-PLN-01, F-PLN-02).

## 12. Slippage (F-SLP)

**F-SLP-01** (design, D-51, your choice of 2026-10-27) Slippage is a whole number of ticks per order class, market and stop-market, set for each run and recorded in it: by default one tick on trades and on bars of every timeframe, and none on TBBO, which fills at the quote. Limits never slip (F-LMT-03). The +1 tick rerun every report includes (`02` §7) adds one tick to both classes on every fidelity. The ticks may carry a fill beyond every price traded in its interval (a buy stop at a bar's high fills a tick above it), as a quote or a limit's own price may, and a fill is never clamped into that range. What holds for every fill is that it lies on the costly side of the prices traded in its interval: a buy never fills below the lowest of them, a sell never above the highest. On TBBO a record's quote is read no better than its trade, so that no quote breaks this: the later prints of a sweep carry the quote from before the sweep, and an ask below its record's trade counts as that trade, its price and its size (F-QTY-01), as does a bid above it, wherever F-MKT-01, F-STP-02, F-LMT-01, and F-LMT-02 read the quote (S-fill-044 to S-fill-046, S-fill-048).

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

**F-TAG-01** (design) Every fill records the fidelity of the data that priced it (`tbbo`, `trades`, or the bars' timeframe: `1s`, `1m`, `5m`, `1d`), the rule that priced it (one of F-MKT-01 to F-MKT-03, F-STP-02 to F-STP-05, and F-LMT-03), its flags (`ambiguous`, `size_exceeded`), its liquidity (maker or taker), its fee, and its slippage: how many ticks worse than its reference it is, the reference being the price before ticks of a market order or of a stop filled as one (F-STP-05), a triggered stop's price, or a limit's price. It also records its order's role: `entry`, `stop`, `target_1` to `target_3`, or the exit reason of an execution template's market exit (§20), or `exit` for a strategy's own.

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
| An order becomes active 100 ms after the bar close that decided it. On bar days a latency rerun moves a fill only when the latency passes a bar's close. | F-ACT-01 | D-51 | Any latency: none in the NautilusTrader profile, 1 s in the stress rerun. | 2026-10-26 |
| Market and stop-market fills slip one tick on trades and bars and none on TBBO, which fills at the quote; ticks per order class are a run setting. | F-SLP-01, F-MKT-01, F-MKT-02, F-MKT-03 | D-51 | The design's rule by aggressor side on trades: no tick after a trade by a buyer, for a buy (`BACKLOG.md`). | 2026-10-26 |
| On TBBO a quote is read no better than its record's trade: an ask below the trade counts as the trade, as does a bid above it, since the later prints of a sweep carry the quote from before it. | F-SLP-01, F-MKT-01, F-STP-02, F-LMT-01, F-LMT-02, F-QTY-01 | your choice of 2026-10-27 | The quote as recorded, which fills a sweep's stop above every later print of the sweep. | 2026-10-27 |
| A limit fills only when the market trades through its price. | F-LMT-01 | D-51 | Touch (F-LMT-02). | 2026-10-26 |
| Bars coarser than a minute replay like 1-minute bars, and a bucket without trades fills nothing. | F-BAR-07 | D-51 | | 2026-10-26 |
| A trade date before a fee table's first schedule takes that schedule, with a warning in the run. | F-FEE-01 | D-51 | Refuse the run. | 2026-10-26 |
| A triggered stop fills at the worse of its price plus the ticks and the price that triggered it (on TBBO, the next record's quote), so a gap fills at the gap price with no ticks beyond it. | F-STP-02, F-STP-03, F-STP-04 | design, your choice of 2026-10-21 | The design table's gap price plus one tick; on trades, the next trade's price, as TBBO takes the next record's quote. | 2026-10-26 |
| A stop triggered on TBBO is a market order from its trigger: no decision cancels it, and it fills before the orders that become active on its fill record. | F-STP-02 | your choice of 2026-10-27 | A working order until it fills, which a decision can cancel and a market order of its group can beat. | 2026-10-27 |
| A limit fills at its price, never better, even above the market. | F-LMT-03 | design | | 2026-10-26 |
| Holding a position, a bar's adverse extreme comes first, so a stop beats a target in one bar. | F-BAR-02 | design | | 2026-10-26 |
| Between its pseudo-ticks a bar passes every price, so a stop inside it fills at its price plus the ticks. | F-BAR-01 | design | | 2026-10-26 |
| Records received at one instant keep the vendor's order. | F-CLK-03 | proposed | | 2026-10-26 |
| The bars that close at an instant come before its other events, and their fills keep the bar's trade date. | F-CLK-02, F-BAR-06 | proposed | | 2026-10-26 |
| On bars, an order decided at a close sees the first bar closing after its activation, whole from its open; a bracket works on the rest of its entry's bar. | F-ACT-02 | proposed | | 2026-10-26 |
| A stop at or through the market when it becomes active fills at once as a market order, with the larger of the two classes' ticks; for a bracket's stop, the market is the price at its entry's fill before slippage, the trade's price or the entry's point of a bar's path. | F-STP-05 | proposed | Refuse it, as CME does. | 2026-10-26 |
| A limit filled on the first price it sees is a taker, any later one a maker. | F-LMT-04 | proposed | | 2026-10-26 |
| Flat, a bar's extreme favourable to the earliest placed working entry comes first, the lower order id breaking ties. | F-BAR-03 | proposed | The extreme nearer the open first. | 2026-10-26 |
| After an entry inside a bar, the extremes not yet reached come adverse first. | F-BAR-04 | proposed | | 2026-10-26 |
| A bar whose fills would differ with its extremes swapped flags every fill `ambiguous`, and the run counts them. | F-BAR-05 | design, proposed test | | 2026-10-26 |
| Working orders stay through breaks and weekends; the engine cancels nothing at a close. | F-SES-01 | proposed | Day orders, cancelled at each session's close. | 2026-10-26 |
| Records received in a break or a halt are not tradeable. | F-SES-02 | proposed | | 2026-10-26 |
| When one trade or TBBO record would fill a stop and a limit of one group, the stop fills; on bars the path decides. A TBBO record that triggers a stop cannot fill it, so a limit of its group that the record fills wins. | F-OCO-01 | design, proposed tie | | 2026-10-26 |
| A bracket's legs work from the record after their entry's fill, without latency. | F-OCO-02 | proposed | | 2026-10-26 |
| Orders fill whole; on trades and TBBO, a fill larger than its record's size is flagged. | F-QTY-01 | design, proposed flag | A volume or queue model (`BACKLOG.md`). | 2026-10-26 |
| Every amount of money rounds to the micro-unit against the trader, and none wraps. | F-FEE-03 | proposed | Halves away from zero. | 2026-10-26 |
| Funding is paid on the signed quantity at the last trade, a long paying a positive rate. | F-FND-01 | design, proposed mark | The venue's own mark price, once imported. | 2026-10-26 |
| Positions are marked at the last trade, on bar days at the pseudo-ticks; a fill does not move the mark. On bar days, trade paths flag the bars whose order could change a drawdown (§15). | F-MRK-01 | step 2.1's prompt, proposed detail | The bid for a long and the ask for a short on TBBO days (`BACKLOG.md`). | 2026-10-26 |
| With no latency, a record received at a decision's instant comes before it: the orders it places never see that record, which sets the mark they are judged against. | F-ACT-01, F-CLK-02, F-STP-05 | proposed in step 2.7 | The record seen by the orders its decision places. | 2026-10-27 |
| At one point of a bar's path, the orders that see their first bar fill first, then the stops, then the limits, each class by order id. | F-OCO-01 | proposed in step 2.7 | By order id alone. | 2026-10-27 |
| Flat, the side of the earliest working entry orders a bar's extremes, whatever its kind: a buy limit puts the high first, as a buy stop does. | F-BAR-03 | proposed in step 2.7 | The extreme at which the entry fills: the low for a buy limit. | 2026-10-27 |
| Only the fills at one point of a bar's path that leave a position opened, from flat or by reversing one, turn the path adverse first; an exit, or an entry closed again at the same point, leaves its order as it was. | F-BAR-04 | proposed in step 2.7 | After an exit leaves the position flat, the extreme favourable to the earliest working entry first; or each fill that opens a position turns the path, though another fill at the same point closes it. | 2026-10-27 |
| The swapped replay of F-BAR-05 swaps a bar's first extreme only, and F-BAR-04 orders the rest of both paths. | F-BAR-05 | proposed in step 2.7 | Every choice of the path the other way round. | 2026-10-27 |
| A stop is judged against the market once, when it becomes active, even where the next bar opens back on its right side. | F-STP-05 | proposed in step 2.7 | Judged again at each record or bar until it fills. | 2026-10-27 |
| The template rounds a stop's and a trailing stop's distance toward the entry and a target's and a profit trigger's away from it, each to at least one tick, working every number out exactly. | F-RND-01 | your choice of 2026-10-27 | Every distance to the nearest tick, halves away from the entry; or away from the entry for every class. | |
| A feature an exit rule reads, such as an ATR, is a distance in the 1e-9 units of price that the bars' prices are in, as one worked out from them is, cut to whole units before it is multiplied. | F-RND-01 | proposed in step 2.8 | A feature in points, multiplied by 1e9 before it is cut, which a feature worked out from the bars would have to be divided into first. | |
| The initial risk is the ticks from the entry's fill to its stop's first level, at least one. | F-RND-02 | proposed in step 2.8 | | |
| A target closes its fraction of the lots its earlier targets leave, rounded down, and a target of no lots is not placed. | F-PLN-01 | your choice of 2026-10-27 | Rounded to the nearest lot; or all the lots apportioned at once by largest remainder. | |
| An exit plan's legs share its open lots: the stop's fill cancels the targets, and a target's fill reduces the stop or, with no lots left, cancels it. | F-PLN-02 | proposed in step 2.8 | | |
| A stop moves only in the position's favour and never to or through the market, at most to a tick short of it. | F-PLN-03 | proposed in step 2.8 | A move through the market fills the stop at once as a market order (F-STP-05). | |
| An exit plan moves its stop at every price marked and at each decision, its best price starting at the market at its entry's fill. | F-PLN-04 | proposed in step 2.8 | | |
| Skipping descends wherever a trailing stop could follow a new best price or a profit trigger could fire. | F-PLN-05 | proposed in step 2.8 | | |
| Breakeven moves the stop once, to the fill price plus its offset; a profit trigger fires at the first price marked at its level, and `after_target` at that target's fill. | F-BRK-01, F-BRK-02 | proposed in step 2.8 | | |
| A trailing stop follows the best price since the entry's fill from its activation, by ticks, by a multiple of a feature taken again at each decision, or by the column at decisions, in whole steps where it has them. | F-TRL-01, F-TRL-02, F-TRL-03 | proposed in step 2.8 | | |
| `intrabar` moves a trailing stop at every price marked, `bar_close` at decisions alone. | F-TRL-04 | proposed in step 2.8 | | |
| At a decision the template counts, moves, and expires, then exits by flat-by, no overnight, no weekend, max bars or minutes, an opposite signal, or a signal exit, and only then enters; a long and short pair counts as one entry. | F-ENT-01 | proposed in step 2.8 | | |
| An offset entry counts its ticks from the mark at the decision, and with no mark there is none. | F-ENT-02 | proposed in step 2.8 | From the signal bar's close in the signal frame. | |
| A resting entry expires at the n-th decision after its own; an entry stop triggered on TBBO is not cancelled, and nothing else is decided until it fills. | F-ENT-03 | proposed in step 2.8 | | |
| An opposite signal comes before a signal exit, and `reverse` places the exit and then the new entry at one decision. | F-ENT-04 | proposed in step 2.8 | The signal exit first. | |
| Flat-by acts at the first signal close at or after its local time on the trade date's own day, or at the last before the close on a date that closes earlier; a holiday's halt is no overnight's to close before. | F-TIM-01 | your choice of 2026-10-27 | Refuse a flat-by time at or after a session's close; or make flat-by a timer event. | |
| Max bars counts the decisions from the entry's fill, and max minutes the minutes from it. | F-TIM-02 | proposed in step 2.8 | | |
| No overnight closes before each session's close and each holiday's halt; no weekend before each stop whose break holds a day without trade dates. | F-TIM-03 | your choice of 2026-10-27 | No overnight before the session's close alone. | |
| Entry windows read the decision's local time and the day of the week of its local date. | F-TIM-04 | proposed in step 2.8 | The day of the week a window past midnight starts on. | |
| Local times become instants per trade date through the session table and the time zone's rules. | F-TIM-05 | proposed in step 2.8 | | |
| A null blackout counts as false. | F-LIM-01 | proposed in step 2.8 | | |
| A day's limits count the entries placed and the trades closed, each trade at the first decision after its close, and start again each trade date. | F-LIM-02 | proposed in step 2.8 | Count the entries filled. | |
| A cooldown counts its bars from the decision that counts the loss, and its minutes from the loss's closing fill. | F-LIM-03 | proposed in step 2.8 | | |
| A fresh signal is one that was false on the row before, for entries and opposite signals alike. | F-LIM-04 | proposed in step 2.8 | | |
| A fixed size times `size_mult` must make whole lots; notional and risk sizes, worked out at the entry's price, round down, and no lots places no entry. | F-SIZ-01, F-SIZ-02, F-SIZ-03, F-SIZ-04 | proposed in step 2.8 | | |

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
- The NautilusTrader compatibility profile: touch fills, no slippage ticks, no latency, and Nautilus's own bar path (step 2.14).
- Stop-limit orders (event strategies, Phase 9), partial fills, a queue or volume model for limits, and order rejections.
- Funding paid while a trade is open, which a trade's profit and loss (§20) leaves out until step 2.9 brings costs to both engines.

## 20. The execution template

From here the specification says how the execution template of a signal strategy (`02-engine-and-data.md` §2.1, D-53) turns its specification and its signal frame into orders, which then fill by the rules above. The template decides only at its decisions, one at each signal row's `ts_close` (F-ACT-01); between them it acts through the exit plan each entry carries (§22), which the engine works on every record and at every point of a bar's path. Each rule is written for a long, and a short mirrors it.

| Word | Meaning |
| --- | --- |
| Entry row | The signal row of the decision that placed an entry. |
| Exit plan | The stop, the targets (three at most), the breakeven, and the trailing stop an entry carries, placed when it fills (F-PLN-01). |
| Leg | One order of an exit plan: its stop or one of its targets. |
| Open lots | An exit plan's entry's lots less those its legs have filled (F-PLN-02). |
| Initial risk | The distance in ticks from an entry's fill price to its stop's first level (F-RND-02). |
| Best price | For a long, the highest price marked since its entry's fill, starting from the market at the fill (F-PLN-04); for a short, the lowest. |
| Trade | A position from the fill that opens it from flat to the fill that leaves it flat. Its profit and loss is what its fills moved the cash by, less their fees (F-FEE-03), and it is a loss below zero. |
| Exit reason | Why an order closed the position, which its fill records as its role (F-TAG-01): `stop`; `target_1`, `target_2`, or `target_3`; or a market exit of the template, `flat_by`, `no_overnight`, `no_weekend`, `max_bars`, `max_minutes`, `opposite_signal`, or `signal_exit`. A strategy's own exit, outside the template, is `exit`. |
| Stop of trading | A point at which a session's trading stops: its close, and a holiday's halt, from which trading resumes at the calendar's regular open (D-41). A halt in every session, such as equity index's 15:15 to 15:30 Chicago before 2021-06-28, is not one. |

## 21. Rounding (F-RND)

**F-RND-01** (proposed in step 2.8, your choice of 2026-10-27) The template places orders on the tick. A distance it works out, a percentage of a price, a multiple of a feature, or a multiple of the initial risk, is a whole number of ticks, at least one: rounded down for a stop and for a trailing stop's distance, so that no stop lies farther away than asked, and up for a target and for a profit trigger (F-BRK-02), so that no target lies nearer than asked. Every number is worked out exactly, so there are no halves to break: a number of the specification or of the signal frame counts as the decimal it prints as, a feature's value, in the 1e-9 units of price that a feature worked out from the bars' prices has, is cut to whole units before it is multiplied, and an amount of money is rounded down to the micro-unit. A price the signal frame gives (`entry_price`, `stop_price`, `target_price`, `trail_ref`) must lie on the tick, and a run that meets one off it is refused, as is a run whose rule reads a feature that is missing, or at or below zero, on the row it needs.

**F-RND-02** (proposed in step 2.8) An exit plan's initial risk is the distance from its entry's fill price to its stop's first level (F-PLN-01) in whole ticks, at least one: a stop in ticks, its ticks; a percent or ATR stop, its rounded ticks; and a stop at `stop_price`, the ticks to that price. Targets and profit triggers given in R multiples count in it, so a specification that gives them, or a risk size, without a stop is refused.

## 22. Exit plans (F-PLN)

**F-PLN-01** (proposed in step 2.8, your choice of 2026-10-27) When an entry fills, its exit plan is placed at once, as F-OCO-02 places a bracket: its stop, then its targets in order, each taking the next order id, and a target with no lots none. The stop is a stop-market order for all the entry's lots below its fill price: `ticks` ticks below it, `percent` % of the fill price below it, or `multiple` times the entry row's feature below it (each rounded down, F-RND-01), or at the entry row's `stop_price`. A target is a limit above the fill price: `ticks` ticks, `multiple` times the entry row's feature, or `multiple` times the initial risk above it (each rounded up), or at the entry row's `target_price`. Target n closes `fraction` of the lots its earlier targets leave, rounded down to whole lots: 3 lots under fractions 0.5, 0.5, and 1 give targets of 1, 1, and 1 lot, and 1 lot under 0.5 and 1 gives the first target no lots, so it is not placed, and the second the lot.

**F-PLN-02** (proposed in step 2.8) An exit plan's legs work for its open lots, its entry's lots less those its legs have filled. When its stop fills, its targets are cancelled (F-OCO-01). When a target fills, the plan's other legs are cancelled if no open lots remain, and otherwise its stop is reduced to the open lots, which the log records; a stop triggered on TBBO is cancelled or reduced like any other, as F-OCO-01 lets a limit beat it. The orders one point of a bar's path fills come in F-OCO-01's order, stops first, so a stop that fills there for all the open lots leaves nothing for a target at that point.

**F-PLN-03** (proposed in step 2.8) An exit plan moves its stop only up, and never to or above the market: a move that would put the stop at or above the market at the move puts it one tick below that price instead, and a move that would not raise it leaves it. The market at a move is the price whose marking moves it (F-PLN-04), or at a decision the mark (F-MRK-01). A moved stop works from the next record, on bars from the rest of the bar's path, and a stop triggered on TBBO, a market order already sent, does not move (F-STP-02).

**F-PLN-04** (proposed in step 2.8) An exit plan follows the market from its entry's fill. Its best price starts at the market at the fill, as F-STP-05 defines it, and rises with each price marked after it (F-MRK-01): each tradeable record's trade on trades and TBBO, and on bars the open, each extreme the path reaches, and the close, each once the fills at that point are done. At each such price, and at each decision, its breakeven and its trailing stop may move its stop (F-BRK-01, F-TRL-01); a trailing stop that works from the fill raises the stop's first level at once, at the market at the fill, as it would at a price marked. A trigger that a target's fill sets off acts at the next price marked, which on trades and TBBO is that record's own trade. Between two of those points a bar's path does not turn, so a stop moved at them stands where a stop following every price of the path would.

**F-PLN-05** (proposed in step 2.8) Skipping (`02` §4) passes over a block of records only where no exit plan could move inside it, besides its other conditions: the bar holding the block rises no higher than the best price of a plan with a trailing stop, does not reach the level of a profit trigger still waiting (F-BRK-02), and meets no intrabar trailing stop that stands below its level, held there by the market (F-PLN-03), since a price under the best price can still raise such a stop. A skipped block so leaves every plan as a full replay of it would.

## 23. Breakeven (F-BRK)

**F-BRK-01** (proposed in step 2.8) An exit plan's breakeven moves its stop once, when its trigger fires, to the entry's fill price plus `offset_ticks` ticks, below it for a negative offset, as F-PLN-03 moves a stop.

**F-BRK-02** (proposed in step 2.8) A profit trigger fires at the first price marked (F-PLN-04) at or above the entry's fill price plus its distance: `ticks` ticks, or `multiple` times the initial risk, rounded up (F-RND-01). An `after_target` trigger fires when that target fills, and never when the target was not placed (F-PLN-01).

## 24. Trailing stops (F-TRL)

**F-TRL-01** (proposed in step 2.8) A trailing stop works from its activation: the entry's fill when it has none, or the firing of its trigger (F-BRK-02). Working, it raises the stop to the best price less its distance (F-TRL-02), as F-PLN-03 moves a stop, so that the stop is the highest of where it stands, the breakeven's level once fired, and the trailing level.

**F-TRL-02** (proposed in step 2.8) A trailing stop's distance is `ticks` ticks, or `multiple` times its feature on the latest decision's row, rounded down (F-RND-01) and taken again at each decision whose row gives the feature. A trailing stop `by` the column instead raises the stop at each decision to that row's `trail_ref`, where the row gives one.

**F-TRL-03** (proposed in step 2.8) With `step_ticks`, a trailing stop raises the stop by whole steps of that many ticks from where it stands, as many as the trailing level allows within F-PLN-03, and not at all while it allows none.

**F-TRL-04** (proposed in step 2.8) With `update: intrabar` a trailing stop moves at every price its plan marks and at each decision (F-PLN-04); with `bar_close`, which a trailing stop by the column needs, at decisions alone, from the best price so far, which the plan follows at every price all the same.

## 25. Decisions and entries (F-ENT)

**F-ENT-01** (proposed in step 2.8) At each decision the template works in this order. It counts the trades closed since its last decision (F-LIM-02), moves the stops that move at decisions (F-TRL-02, F-TRL-04), and cancels the entries whose time to live has ended (F-ENT-03); while a market order is on its way out of the position or into it, its own exit or a stop triggered on TBBO (F-STP-02), it does nothing more. Otherwise the first time exit that applies closes the position at the market with its exit reason and cancels the working orders: flat-by, no overnight, or no weekend (F-TIM-01, F-TIM-03), which also cancel a flat strategy's working entries and place no entry at that decision, then max bars or max minutes (F-TIM-02); then an opposite signal or a signal exit (F-ENT-04). Last, flat and with no live order, it enters on a row whose `wake` is true and that its time rules and limits allow (F-TIM-04, §27): `long_entry` buys and `short_entry` sells. With a market entry a row may give only one of them; with a limit or a stop entry a row that gives both places the buy and then the sell as one OCO group, the long and short pair.

**F-ENT-02** (proposed in step 2.8) An entry is a market order; a limit or a stop at the row's `entry_price` (`limit_at_column`, `stop_at_column`), which a row that enters must give; or a limit or a stop `ticks` ticks from the mark at the decision, the last tradeable price before it (F-MRK-01): a buy limit below it and a buy stop above it (`limit_offset`, `stop_offset`). With no mark yet, an offset entry is not placed, and the log says why. Each is active the run's latency after its decision (F-ACT-01), fills by the rules of its class, and carries its exit plan (F-PLN-01).

**F-ENT-03** (proposed in step 2.8) A limit or stop entry with `time_to_live_bars` n that is still live at the n-th decision after the one that placed it is cancelled there (F-ENT-01). An entry stop triggered on TBBO is a market order already sent, which no decision cancels (F-STP-02): until it fills the template decides nothing more, and from the next decision after its fill its position meets the time exits as any other.

**F-ENT-04** (proposed in step 2.8) Holding a long, a `short_entry` does what `on_opposite_signal` says: `ignore`, nothing; `close`, the long is closed at the market (exit reason `opposite_signal`); `reverse`, the long is closed so, and at the same decision a short is entered under the conditions of F-ENT-01 but flatness, its order taking a higher id than the exit's, so that the exit fills first. Otherwise, with `signal_exit` on, `long_exit` closes the long at the market (exit reason `signal_exit`).

## 26. Time rules (F-TIM)

**F-TIM-01** (proposed in step 2.8, your choice of 2026-10-27) From its flat-by time each trade date, the template closes the position (exit reason `flat_by`), cancels its working orders, and places no entry: from the first signal close at or after that local time on the trade date's own day, which must fall after the session's open, outside its halts, and on the signal bars' grid counted from the open (D-53), or, on a trade date whose session closes at or before that time, as an early close does, from the last signal close before the close. A halt day's trading belongs to the next trade date (D-41), so a holiday's halt before the flat-by time is no overnight's to close before (F-TIM-03).

**F-TIM-02** (proposed in step 2.8) With `max_bars` n, the template closes the position (exit reason `max_bars`) at the n-th decision at or after its entry's fill; with `max_minutes` m, at the first decision at or after the fill plus m minutes (exit reason `max_minutes`).

**F-TIM-03** (proposed in step 2.8, your choice of 2026-10-27) With `no_overnight`, the template closes the position (exit reason `no_overnight`), cancels its working orders, and places no entry from the last signal close before each stop of trading (§20) until trading resumes. With `no_weekend`, it does the same before each stop whose break holds a day of the week on which its calendar has no trade date, such as a Saturday for CME (exit reason `no_weekend`): Friday's close, and the halt from noon on Friday 2026-07-03 to the Sunday open. A calendar that trades every day has no weekend.

**F-TIM-04** (proposed in step 2.8) With entry windows, the template enters only at a decision whose local time in `tz` lies in one of them, from its `start` to just before its `end`, a window whose `end` comes before its `start` running past midnight, and on one of its `weekdays`, the days of the week of the decision's local date. Exits and the other rules act at every decision.

**F-TIM-05** (proposed in step 2.8) Local times become instants per trade date, through the session table and the time zone's own rules (`02` §1.3), never by a fixed offset, so that a clock change moves them: 15:05 Chicago is 21:05 UTC on 2026-03-06 and 20:05 UTC on 2026-03-09. A local time that a clock change skips or repeats is refused.

## 27. Entry limits (F-LIM)

**F-LIM-01** (proposed in step 2.8) With `blackout`, a row on which that boolean column of the signal frame is true places no entry; a null counts as false.

**F-LIM-02** (proposed in step 2.8) Each trade date the template counts the entries it places, a long and short pair as one, and the trades that close (§20), each at the first decision at or after its closing fill, on that decision's trade date. It places no entry once that date's entries reach `max_trades_per_day` or its losing trades `max_losses_per_day`, or once its closed trades' profit and loss is at or below minus `daily_loss_stop` or at or above `profit_lock`. The counts start again each trade date.

**F-LIM-03** (proposed in step 2.8) After a losing trade, `cooldown_after_loss` places no entry at the `bars` decisions from the one that counts it (F-LIM-02) on, or at the decisions before its closing fill plus `minutes` minutes.

**F-LIM-04** (proposed in step 2.8) With `fresh_signal`, an entry signal counts only on a row where it was false on the row before, the first row's counting, so that a signal still true after an exit does not enter again. It holds for opposite signals too (F-ENT-04).

## 28. Sizing (F-SIZ)

**F-SIZ-01** (proposed in step 2.8) A fixed size enters its `units` in whole lot steps, times the row's `size_mult` where the signal frame has one, which must make whole lots, at least one, or the run is refused (D-53).

**F-SIZ-02** (proposed in step 2.8) A notional size enters the whole lots whose value at the entry's price is at most its `amount`, rounded down. The entry's price is a limit's or a stop's own price, and for a market entry the mark at the decision.

**F-SIZ-03** (proposed in step 2.8) A risk size enters the whole lots that lose at most its amount at the stop, rounded down: one lot's loss from the entry's price (F-SIZ-02) to the stop, as F-PLN-01 would place it for a fill at that price. `risk_amount` gives the amount in the account's currency; `risk_percent` gives `percent` % of equity at the decision, the cash and the open position's value at the mark (F-MRK-01), which starts at the run's capital (D-51). A stop at `stop_price` not below the entry's price places no entry.

**F-SIZ-04** (proposed in step 2.8) A notional or risk size times the row's `size_mult` is rounded down to whole lots. A size of no lots, or one without a mark to price it, places no entry, and the log says why.
