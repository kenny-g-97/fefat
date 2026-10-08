# 00 — Product specification

FEFAT ("feature engineering for algorithmic trading") is a local-first research platform for discretionary and algorithmic futures and crypto traders. It runs on the trader's own PC, is used from the browser and from the phone, and is later packaged as a desktop app. Its four pillars come straight from `raw_app_idea.txt`.

## 1. Who it is for

- **Now:** one trader (you) who is comfortable with Python and notebooks, trades CME futures and crypto, develops intraday and swing strategies, and evaluates prop-firm accounts.
- **Later:** other traders like you, running FEFAT on their own machines with their own market data and their own Claude API key. Nothing in FEFAT is hosted for them; that is a deliberate product and licensing decision (see `DECISIONS.md`, D-02).

## 2. The four pillars

### 2.1 Feature lab and strategy workspace

- A **feature** is a named, versioned Python function that turns market data (and optionally alternative data or other features) into one or more time series aligned to bar closes. Features declare their parameters, inputs, and warm-up.
- The **feature library** keeps every version of every feature, with its code, parameters, dependencies, and validation results (including the look-ahead check).
- The **feature lab** is an editor with an instant preview: run the feature on a chosen instrument and date range, see it under the price chart, see its statistics (coverage, distribution, forward-return relationship), and save a new version.
- **Combining** features produces new features (arithmetic, logic, crosses, normalisation, resampling across timeframes, spreads across instruments).
- A **strategy** turns features into trading decisions. In the first release every strategy is rule-based, in one of two forms:
  - a **signal strategy**, assembled in a no-code builder or written as a short Python definition: entry and exit conditions over features plus an execution template (stop, targets, trailing, time exits, session filters, sizing). The builder generates the Python definition, which is always viewable and can be edited by hand ("eject").
  - an **event strategy** (added in Phase 9): a Python class with an `on_bar` callback and an order API for path-dependent logic.
- **Alternative data** (files or URLs) is imported, turned into datasets with publication timestamps, and used as feature inputs. The agent writes the ingestion code; you approve it.
- The **in-app agent** (Claude) helps write features and strategies, analyses backtests, and proposes changes. Every change it proposes is a diff you accept or reject.

### 2.2 Backtesting

- FEFAT has its **own engine** (Rust core, Python interface). It is deterministic: the same inputs always produce identical results.
- **Strategy versions are immutable.** Every backtest run pins the strategy version, its parameters, the feature versions it uses, the data snapshot, and the engine version. A run can always be reproduced, and every run stays linked to its strategy version forever.
- **Accuracy:** signals are decided at bar close; orders, stops, targets, and account rules are simulated on the finest data available inside each bar (ticks, else 1-second bars, else 1-minute bars). Every fill carries a fidelity tag. Fill rules are written down in plain language and enforced by tests.
- **Analysis:** metrics, equity curves, distributions, a trade table, and a trade review chart that shows entries, exits, stops, targets, and the indicators the strategy used. Any trade can be "explained": replayed event by event through the readable reference engine.
- **Comparison:** runs can be compared side by side, and strategy versions can be diffed.
- The agent can analyse a run with you, propose an edit, and (after your approval) create a new version and start the next backtest.

### 2.3 Prop-firm simulator

- **Rule sets** describe a prop firm's plan as data: stages (evaluation, funded, live), drawdown type and lock, daily loss, consistency, minimum days, session rules, position limits and scaling, payout rules and caps, fees, lifecycle transitions. Presets are dated, sourced, and tested against the firm's own worked examples. Custom rule sets are supported.
- **Exact mode** runs a strategy with the account rules enforced inside the engine, including forced liquidation at a breach and flat-by times.
- **Fast replay** re-uses a compact record of each trade's equity path to evaluate account rules for any size multiplier, start date, and policy without re-running the strategy.
- A **macro-strategy** (policy) decides how many evaluation and funded accounts to run and when to start, reset, or replace them; how to size per account stage; when to request payouts and how much to reinvest; and how to allocate trades across accounts and firms.
- **Monte Carlo** runs over every historical start date and over reshuffled trading days, with a real-money cash ledger (fees, resets, activation, payouts after split). Outputs: pass probability and time to pass, probability and time of first payout, net cash distribution, probability of net loss, bankroll drawdown, cost per funded account, failure reasons — and a ranking of plans for a given strategy by median net cash and by probability of net loss.

### 2.4 Phone

- The same web app, installed to the phone's home screen, reaches your PC over Tailscale. Everything works: features, strategies, backtests, prop simulations, the agent, notifications when a job finishes.
- The phone is **agent-first**: typing code is possible but never required.

## 3. Research tools (added capabilities)

- Parameter optimization (grid, random, Bayesian) with heatmaps and overfitting diagnostics.
- Walk-forward analysis with a stitched out-of-sample equity curve.
- Monte Carlo robustness (day-block bootstrap, trade skipping, cost and parameter stress).
- Feature analytics (forward-return studies, information coefficient and its decay, correlations between features, event studies).

## 4. Scope of the first release (Phases 0–8)

| In | Later (phase) | Not planned |
| --- | --- | --- |
| CME futures (ES, NQ, CL, GC and micros) and crypto (spot and perpetuals) | Event strategies (P9), alternative data (P10), research tools (P11), phone polish (P12), hardening (P13), desktop packaging (P14) | Live or paper trading, broker connections |
| Signal strategies, backtests, feature lab, strategy builder, prop simulator, in-app agent | Cloud sync for phone access while the PC is off (backlog) | Hosting market data or compute for other users |
| One user, one PC, phone over Tailscale | Machine-learning models on features (backlog) | Order-book (L2) strategies, tick-reactive scalping |
| Databento and Binance archives as data sources | More data vendors, more prop firms | Social features, strategy marketplace |

## 5. Non-goals and constraints

- FEFAT never ships, hosts, or redistributes market data. Licensed data lives under `FEFAT_DATA_DIR` on the user's machine and never enters the repository.
- FEFAT never executes the agent's edits without an explicit decision by the user.
- FEFAT never silently changes a saved result: versions and runs are immutable; a changed fill rule is a new engine version.
- No cloud dependency for core use. The only network calls in normal use are to Anthropic's API (agent, optional), data vendors (imports), and the push-notification services.

## 6. Key journeys (first release)

1. **Import data.** Point FEFAT at your Databento files (or pull with your API key after a cost preview), download the Binance archive for the pairs you trade, and see the catalog with coverage and quality reports.
2. **Build a feature.** Write ten lines of Python (or ask the agent), preview it on ES 5-minute bars for 2024, read its statistics and leak check, save version 1.
3. **Build a strategy.** Pick two features, set conditions, choose stop and targets and session window in the builder, look at the generated code, run a backtest on 2021–2025 with tick fills, inspect trades on the chart.
4. **Iterate with the agent.** Ask why March lost money; the agent queries the trades, suggests a filter, proposes the edit; you accept; version 2 is created and backtested; compare versions.
5. **Choose a prop plan.** Run the strategy through Topstep, My Funded Futures, and Tradeify presets with a policy of two staggered evaluations and conservative sizing when funded; read the pass probability, expected payouts, cost, and the plan ranking.
6. **From the phone.** Start a backtest from the train, get a notification when it finishes, review the equity curve and the agent's summary, approve a proposal.

## 7. Glossary

| Term | Meaning |
| --- | --- |
| Bar | A time bucket of trades (1-second, 1-minute, 5-minute, daily). Signals are decided at bar close. |
| Tick | One trade print (or trade with the prior best bid/ask, "TBBO"). Fills are simulated on ticks when available. |
| Fidelity | The finest data used to fill an order on a given day: `tick`, `1s`, or `1m`. |
| Feature | A versioned function from data to aligned time series. |
| Signal frame | The table of boolean/number columns a signal strategy produces for every bar (`long_entry`, `stop_price`, …). |
| Execution template | The declarative part of a signal strategy: order types, stops, targets, trailing, time rules, filters, sizing. |
| Strategy version | An immutable snapshot of a strategy's code, builder spec, parameter schema, and pinned feature versions. |
| Run | One backtest: a strategy version plus parameters, data snapshot, engine version, and configuration, with its artifacts. |
| Data snapshot | A content-hashed manifest of the exact data partitions a run used. |
| Leak (look-ahead) | A feature value at time t that depends on information available only after t. |
| Rule set | A prop firm plan expressed as data. |
| Policy (macro-strategy) | Account-level decisions over time: accounts, sizing, payouts, allocation. |
| Proposal | A change suggested by the agent, pending your accept or reject. |
| Workspace | A folder holding your features, strategies, runs, and uploads. One workspace in the first release. |
| Step | One unit of the masterplan: one Claude Code session, one pull request. |
| Block bootstrap | Resampling whole trading days (in blocks, to keep streaks) to build many plausible histories from one; used by the robustness and prop Monte Carlo tools. |
| PBO | Probability of backtest overfitting: how often the parameters that looked best in one half of the data underperform in the other half. |
| Deflated Sharpe | A Sharpe ratio corrected for the number of things you tried; more trials, more deflation. |
| Keyset pagination | Paging a long table by "continue after the last row seen" instead of page numbers; stays fast on large tables. |
| Downsampling | Reducing a long series to fewer points for a chart while keeping its highs and lows. |
| VAPID | The key pair that identifies your server to the browsers' push-notification services. |
| Job Object (Windows) | The operating-system mechanism FEFAT uses to cap a subprocess's memory and kill it on timeout. |
