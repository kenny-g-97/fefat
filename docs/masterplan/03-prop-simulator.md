# 03 — Prop-firm simulator

The simulator answers one question: _given this strategy, which prop plan and which account policy give the best expected outcome, and with what risk?_ It builds on the engine (`02-engine-and-data.md`) and on the rules research (`appendix/research-prop-firms.md`).

## 1. Rules as data

A rule set is a versioned YAML file under `python/fefat/prop/presets/<firm>/<plan>@<as-of>.yaml`, plus user-defined rule sets stored in the database with the same schema. Every preset carries source URLs, retrieval dates, and worked examples transcribed from the firm's own documentation. A preset is not `verified` until its examples pass, including one breach and one payout. Results show the preset's status (`verified`, `draft`, `stale`).

Schema shape (refined in step 7.1; types generated from Rust with `schemars`):

```text
Firm      id, timezone, account_caps{eval, funded, live, scope: user|household, overflow: queue|block},
          conduct{automation: allowed|conditions|prohibited|unknown, copy_own, hedging, min_hold_seconds}
Plan      id, firm_id, version{as_of, applies_to_purchases_from}, size, currency,
          fees{model: one_time|monthly, price, activation, reset, funded_monthly, data}, stages[]
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

## 2. Account state machine

States: `EvalActive`, `EvalPassed`, `FundedActive`, `Live`, `LockedUntil(t)`, `PayoutPending`, `Failed`, `Expired`.

Events: `Mark` (intrabar equity), `EpisodeEnd` (trade closed), `DayAnchor` (firm day boundary, for crypto-style snapshots), `SessionEnd` (end-of-day high-water mark, minimum-day tally, consistency, target check), `FlatBy`, `PayoutRequest`, `PayoutApproved`, `FeeDue`, `Expiry`, `Reset`.

Each rule is a pure function from `(state, event)` to `(state, actions)` in integer money. The same state machine runs in exact mode and in fast replay, and the Python reference implementation (`fefat/ref/prop.py`) is the oracle for the Rust one.

### Drawdown types, precisely

| Type | High-water mark tracks | Floor updates | Breach test |
| --- | --- | --- | --- |
| Static | initial balance | never | equity (incl. open P&L, fees) ≤ floor at any instant |
| EOD trailing (futures) | highest closing balance (flat-by rules make this realized balance) | once per day at the firm's close, effective next session | real-time equity, intraday |
| EOD trailing (24h markets) | highest balance at the firm's snapshot time, open positions excluded | daily | equity |
| Intraday trailing | peak equity including unrealized, tick by tick | continuous | equity |
| Balance trailing | highest realized balance | on each trade close | equity |

Daily loss limits in futures firms count unrealized losses; a soft breach flattens, cancels orders, and locks until the next session; liquidation fills can go past the limit. Consistency: ratio = best day ÷ denominator; "raise target" means required total = max(target, best ÷ θ); windows reset on payout approval and usually exclude the request day. See the research appendix §3 for per-firm anchors and boundaries.

## 3. Two modes

### 3.1 Exact mode

A `PropAccount` implements the engine's `AccountModel` trait. The strategy runs with the account rules enforced inside the loop: forced liquidation at a breach, flat-by times, contract limits, daily-loss lockouts, session rules. One strategy instance per account runs in one engine pass; rolling start dates are supported, bootstrap is not. Exact mode is the oracle for replay.

Exact mode is **required** when strategy logic reads account state, when re-entry after a forced flatten matters, when per-account stops, targets, or mid-episode size changes are used, when positions overlap with different multipliers, or when fills depend on size.

### 3.2 Fast replay

The base backtest (one unit, no account state read) exports, per flat-to-flat episode, a compact **equity envelope**: the sequence of running-max increases, a record for each new low since the last peak, and a mark plus reset at every minute boundary, all in price points with contract sides kept separate (so firm commissions and the mini/micro choice apply at replay). A per-episode summary (final, MAE, MFE, maximum drawdown from peak) proves "no rule event" for most episodes, so records are rarely scanned.

A design review simulated 3,000–4,000 randomised multi-day accounts per rule type: with minute marks and new-low records the replay reproduced tick-by-tick results in every trial, including forced liquidation and soft lockouts. (The simpler envelope without new-low records found breaches but reproduced full histories only without price gaps.)

The engine tags each run `replayable`; the flag blocks replay when its conditions do not hold, and exact mode is the fallback. A test requires replay to equal exact mode on the same inputs.

## 4. Policy layer (the macro-strategy)

A declarative `PolicySpec` compiled to Rust for Monte Carlo speed:

- **Accounts over time:** plans to buy, maximum evaluation and funded accounts, start schedule and stagger, actions on fail, pass, and expiry, all conditioned on bankroll.
- **Sizing per stage:** fixed, risk-based, or a ladder on drawdown cushion, per stage; firm contract limits enforced.
- **Payouts and reinvestment:** when to request, minimum amount, buffer kept, share recycled into new evaluations.
- **Allocation:** copy all, rotate, by session, by firm, staggered start; optional per-account noise.

Correlation between accounts is structural, not a parameter: all accounts consume the same trade stream, so a bad day hits every copied account. The cash ledger holds real money only (fees, resets, activations, payouts after split); simulated balances are separate. Python policy hooks are a backlog item for cases the declarative spec cannot express.

## 5. Monte Carlo and reports

- Every historical start date, plus a stationary bootstrap of whole session-days shared by all accounts in a path (mean block length by Politis–White), plus stress (ticks haircut, skipped trades).
- Inputs default to out-of-sample trades when a walk-forward study exists; intervals state the effective sample size.
- Reports: pass probability and time to pass; probability and time of first payout; net cash at the horizon (mean, median, 5/25/75/95%); probability of net loss; maximum bankroll drawdown; cost per funded account; failure reasons; and a **plan ranking** across presets for the same strategy.
- Feasibility flags on results: the preset's automation policy, hold-time rules, and session constraints that the strategy violates.

## 6. Pages (Phase 7)

- Rule-set library: presets with status, as-of date, sources; custom rule sets; version history.
- Policy builder: the four dimensions as forms, with presets ("one conservative evaluation", "two staggered evaluations", "five-account copier").
- Simulation launch: pick runs (or a strategy version to run in exact mode), rule sets, policy, horizon, number of paths, seed.
- Results: account timelines (one lane per account: evaluation, funded, payouts, failure), cash curves with bands, outcome distributions, failure reasons, plan ranking table, and the feasibility flags.

## 7. Suggested first presets

Confirmed at the Phase 7 kickoff. Suggested: Topstep (Trading Combine → XFA), My Funded Futures (Rapid or Pro), Tradeify (Growth or Select) — all allow automated strategies with conditions — then Apex 4.0 (most popular; prohibits automation, flagged), and Breakout for crypto. The `prop-preset-refresh` skill re-reads each firm's pages and proposes a new preset version; existing versions are never edited.
