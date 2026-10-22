# 03 — Prop-firm simulator

The simulator answers one question: _given this backtest, which prop plan and which prop strategy give the best expected outcome, and with what risk?_ It takes three inputs — **prop rules**, a **prop strategy**, and an **existing backtest file** with the full trade log — and never re-runs the trading strategy (decision D-25). It builds on the trade paths every FEFAT run stores (`02-engine-and-data.md` §4 and §7) and on the rules research (`appendix/research-prop-firms.md`).

## 1. The three inputs

| Input | What it is | Where it comes from |
| --- | --- | --- |
| Prop rules | A rule set: one firm's plan as data (stages, drawdown, daily loss, consistency, payouts, fees, commissions, …) | Dated presets with sources, or your own custom rule sets (§2) |
| Prop strategy | The account-management decisions: accounts over time, sizing per stage, payouts and reinvestment, trade allocation (`PropStrategySpec` in the code) | Presets or your own (§5) |
| Backtest file | An existing backtest with its full trade log and, for full precision, each trade's intrabar path | A saved FEFAT run, or a trade log imported from another platform (§4) |

Because the strategy is never re-run, a simulation of thousands of account lifetimes takes seconds, and the same backtest can be tested against any number of firms and prop strategies. One backtest file feeds one simulation; combining several backtests in one account (a portfolio) is a backlog item.

## 2. Rules as data

A rule set is a versioned YAML file under `python/fefat/src/fefat/prop/presets/<firm>/<plan>@<as-of>.yaml`, plus user-defined rule sets stored in the database with the same schema. Every preset carries source URLs, retrieval dates, and worked examples transcribed from the firm's own documentation. A preset is not `verified` until its examples pass, including one breach and one payout. Results show the preset's status (`verified`, `draft`, `stale`).

Schema shape (refined in step 7.1; types generated from Rust with `schemars`):

```text
Firm      id, timezone, account_caps{eval, funded, live, scope: user|household, overflow: queue|block},
          conduct{automation: allowed|conditions|prohibited|unknown, copy_own, hedging, min_hold_seconds}
Plan      id, firm_id, version{as_of, applies_to_purchases_from}, size, currency,
          fees{model: one_time|monthly, price, activation, reset, funded_monthly, data},
          commissions{per_contract_side by product, crypto_bps}, stages[]
Stage     kind: eval|funded|live|prelive, expiry_days, min_days{n, day_definition},
          target{amount, basis: closed|equity, require_flat},
          drawdown{type: static|eod_trailing|intraday_trailing|balance_trailing, amount,
                   hwm_source: close|realized|peak_equity|gross, touch_is_breach,
                   lock{level: start|start_plus|target|none, plus_amount, triggers:[hwm, payout_request, first_payout]},
                   on_payout: none|lock|reset_to_zero|keep_gross},
          daily_loss{mode: none|soft|hard, amount|pct, anchor: session_pnl|snapshot_balance|day_peak_equity,
                     reset_time, dynamic: none|tiers|pct_of_peak_profit, remove_when_locked},
          consistency{window: eval|payout_cycle|lifetime, numerator: day|trade|instrument,
                      denominator: net_profit|target|positive_days|gross, theta[], inclusive,
                      effect: raise_target|block_payout|discount|penalty},
          session{day_start, flat_by, overnight, weekend, news_windows[]},
          position{max_units, micro_ratio, scaling{basis, table, effective: next_session}},
          payout{gates[], amount{rule, caps_by_payout_no[], min}, split{schedule}, cadence,
                 lifetime_cap{count|usd}, while_pending: trade|no_trade|flat},
          transitions[{trigger, to, mandatory, side_effects:[close_others, forfeit_sim, reserve, cooldown]}]
```

## 3. Account state machine

States: `EvalActive`, `EvalPassed`, `FundedActive`, `Live`, `LockedUntil(t)`, `PayoutPending`, `Failed`, `Expired`.

Events: `Mark` (equity inside a trade, from its path), `TradeEnd` (trade closed), `DayAnchor` (firm day boundary, for crypto-style snapshots), `SessionEnd` (end-of-day high-water mark, minimum-day tally, consistency, target check), `FlatBy`, `PayoutRequest`, `PayoutApproved`, `FeeDue`, `Expiry`, `Reset`.

Each rule is a pure function from `(state, event)` to `(state, actions)` in integer money. The Python reference implementation (`fefat/reference/prop.py`) is the oracle for the Rust one.

### Drawdown types, precisely

| Type | High-water mark tracks | Floor updates | Breach test |
| --- | --- | --- | --- |
| Static | initial balance | never | equity (incl. open P&L, fees) ≤ floor at any instant |
| EOD trailing (futures) | highest closing balance (flat-by rules make this realized balance) | once per day at the firm's close, effective next session | real-time equity, intraday |
| EOD trailing (24h markets) | highest balance at the firm's snapshot time, open positions excluded | daily | equity |
| Intraday trailing | peak equity including unrealized, tick by tick | continuous | equity |
| Balance trailing | highest realized balance | on each trade close | equity |

Daily loss limits in futures firms count unrealized losses; a soft breach flattens, cancels orders, and locks until the next session; liquidation fills can go past the limit. Consistency: ratio = best day ÷ denominator; "raise target" means required total = max(target, best ÷ θ); windows reset on payout approval and usually exclude the request day. See the research appendix §3 for per-firm anchors and boundaries.

## 4. The backtest file and its replay

### 4.1 What a backtest file contains

- **From FEFAT:** a saved run's `trades` (side, contract, initial risk, MAE and MFE, exit reason), its `fills` (each leg's entry and exit, so partial exits and scale-ins keep their timing), its `trade_paths` (§4.2), funding payments for perpetuals, the instrument specification, the calendar reference, the fee table used, and `run.json`. Every run stores these (decision D-26), so every saved backtest is ready for prop simulation. A run can be exported as one file (a zip of the same tables) to move it between your own machines; its prices come from licensed data, so an export is for your own use, and its manifest says so.
- **Imported:** a trade log from another platform's strategy tester or your own records, converted into the same tables by the trade-log importer (step 7.5) through an import profile, with a path fidelity (§4.4). Overlapping trades on the same instrument and side become legs of one position; logs with overlapping positions across instruments or on opposite sides are refused in the first release.

### 4.2 Trade paths

For every flat-to-flat trade, the engine records a compact path of the price its position is marked at (the marking price defined in the fill specification: the last trade by default, bar prices on bar-fidelity days):

- each new favourable extreme, and each new adverse extreme since the last favourable extreme;
- a mark at every minute boundary and at every fill, where this tracking restarts — so the extremes after any reference point a rule can use (session starts, firm day anchors, snapshot times, and flat-by times all fall on minute boundaries), and their order, survive;
- the data fidelity used for the trade;
- a per-trade summary: final, MAE, MFE, maximum drawdown from the in-trade peak, initial risk.

The path is of price, not of profit. Together with the trade's fills, it lets the replay compute open and realized profit and loss for any size, mini or micro contract, and commission table, partial exits and scale-ins included: for a fixed set of open legs on one side, open profit moves monotonically with price.

This record is enough for every rule in the taxonomy. A design review simulated 3,000–4,000 randomised multi-day accounts per rule type: with the adverse-extreme records and a mark plus restart at every minute boundary, replaying the compact record reproduced tick-by-tick results in every trial, including forced liquidations and soft daily-loss lockouts. (Without the adverse-extreme records, breaches were found, but full account histories were reproduced only when prices had no gaps.) The per-trade summary proves "no rule event" for most trades, so the detailed records are rarely scanned; that is what keeps replays to milliseconds.

Size: compressed, a few MB for a typical intraday run; runs with many multi-day holds carry more, because every minute in a position has a mark. Step 2.13 measures both.

### 4.3 Replay

The replay walks the trades in time order and turns each trade path into account events (§3):

- path marks drive intraday-trailing high-water marks and breach tests on equity;
- session ends drive end-of-day high-water marks, daily tallies, and consistency;
- minute marks give equity at any firm day anchor or snapshot time;
- flat-by times, contract limits, and scaling tiers come from the rule set; sizing comes from the prop strategy;
- commissions come from the rule set's commission table, or from the backtest's fee table when the rule set has none.

When a rule fires during a trade — a breach, a soft daily-loss lockout, a flat-by — the trade is cut at that point of its path, the liquidation is priced at the path's price there plus the configured liquidation slippage (by default the fill specification's stop slippage, one tick against the position), and the reason is recorded. While the account is locked or failed, the backtest's later trades are skipped for that account.

### 4.4 Path fidelity

Fidelity is recorded per trade, because a FEFAT run can mix days with ticks and days with bars, and a backtest file shows the mix.

| Fidelity | Source | Treatment |
| --- | --- | --- |
| `tbbo`, `trades`, `1s`, `1m`, or a coarser bar timeframe | FEFAT runs (the finest data used for each trade, named as `docs/spec/fill-semantics.md` names it) | exact within the data's resolution; on bars the order of a bar's extremes is not known, and trade paths flag the bars where it could change a rule's answer (`docs/spec/fill-semantics.md` §15) |
| `enriched:<resolution>` | imported trades re-marked to market on market data in your store (no strategy logic runs; each trade's own entries and exits are kept) | as exact as the stored data |
| `excursions` | imported trades with MAE and MFE | conservative: loss rules assume the order of extremes that is worst for the account (for trailing drawdowns, the favourable extreme first); profit targets and other favourable-side rules count only closed trades |
| `close-only` | imported trades with entries and exits only | with each trade's initial stop, or a worst-case adverse excursion set in the import profile, every trade is assumed to reach it before closing (a pessimistic bound); with neither, intraday rules cannot be checked, and a pass is reported as "pass, intraday unchecked" (an optimistic bound, left out of plan rankings by default) |

Every result states its fidelity. Tests require the conservative treatments never to report a plain pass that the full path would fail.

### 4.5 What replay does not model

- **Strategy reactions to account state.** After a forced cut, the backtest's later trades are taken as recorded (unless the account is locked or failed); a strategy that would have behaved differently after a lockout or a forced exit is approximated. Results count the trades that followed a forced cut on the same day.
- **Order-book effects.** Forced liquidations are priced at the path's price plus slippage; larger sizes do not change fill prices beyond the configured slippage.
- **News windows.** Not checked in the first release; results for firms with news rules say so (backlog).
- **Several backtests in one account.** One backtest file per simulation in the first release (backlog).

These limits are shown as a note on every result.

### 4.6 Correctness

- The Python reference account machine (`fefat/reference/prop.py`) is the oracle.
- Replay of compact paths must equal the reference fed with test-only full-resolution paths (every tick while in a position), with forced liquidations priced the same way in both, on generated tapes, fills, sizes, and rule sets.
- Every preset's worked examples pass in both implementations.

## 5. Prop strategy

A declarative `PropStrategySpec` compiled to Rust for Monte Carlo speed:

- **Accounts over time:** plans to buy, maximum evaluation and funded accounts, start schedule and stagger, actions on fail, pass, and expiry, all conditioned on bankroll.
- **Sizing per stage:** fixed, as recorded in the backtest (scaled), risk-based on each trade's initial risk, or a ladder on drawdown cushion, per stage; mini or micro contracts; partial exits are re-allocated across the new size with the recorded fractions and the engine's rounding rule; firm contract limits enforced.
- **Payouts and reinvestment:** when to request, minimum amount, buffer kept, share recycled into new evaluations.
- **Allocation:** copy all, rotate, by session, by firm, staggered start; optional per-account noise.

Correlation between accounts is structural, not a parameter: all accounts consume the same backtest file's trades, so a bad day hits every copied account. The cash ledger holds real money only (fees, resets, activations, payouts after split); simulated balances are separate. Python hooks for prop strategies are a backlog item for cases the declarative spec cannot express.

## 6. Monte Carlo and reports

- Every historical start date in the backtest file, plus a stationary bootstrap of whole session-days shared by all accounts in a path (mean block length by Politis–White), plus stress (ticks haircut, skipped trades).
- The input defaults to a walk-forward study's stitched out-of-sample run when one exists for the strategy; intervals state the effective sample size.
- Reports: pass probability and time to pass; probability and time of first payout; net cash at the horizon (mean, median, 5/25/75/95%); probability of net loss; maximum bankroll drawdown; cost per funded account; failure reasons; the path fidelity and the replay notes (§4.5); and a **plan ranking** across rule sets for the same backtest.
- Feasibility flags on results: the preset's automation policy, hold-time rules, and session constraints that the backtest's trades violate.

## 7. Pages (Phase 7)

- Rule-set library: presets with status, as-of date, sources; custom rule sets; version history.
- Prop-strategy builder: the four dimensions as forms, with presets ("one conservative evaluation", "two staggered evaluations", "five-account copier").
- Backtest files: your saved runs (each ready for prop simulation) and imported trade logs, with their path fidelity; an import dialog for trade logs from other platforms.
- Simulation launch: pick a backtest file, rule sets, a prop strategy, horizon, number of paths, and seed; feasibility flags are shown before launch.
- Results: account timelines (one lane per account: evaluation, funded, payouts, failure), cash curves with bands, outcome distributions, failure reasons, the plan ranking table, the feasibility flags, and the path-fidelity badge with the replay notes.

## 8. Suggested first presets

Confirmed at the Phase 7 kickoff. Suggested: Topstep (Trading Combine → XFA), My Funded Futures (Rapid or Pro), Tradeify (Growth or Select) — all allow automated strategies with conditions — then Apex 4.0 (most popular; prohibits automation, flagged), and Breakout for crypto. The `prop-preset-refresh` skill re-reads each firm's pages and proposes a new preset version; existing versions are never edited.
