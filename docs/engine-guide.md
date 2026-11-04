# The engine, for your strategies

How you write a signal strategy, run it, and read what the run saved, written for you as the trader using FEFAT on this PC. `notebooks/02-engine-tutorial.ipynb` runs every part of it on your own data. The rules that price every fill are in [the fill specification](spec/fill-semantics.md); the design behind the engine is in `docs/masterplan/02-engine-and-data.md` §2 to §7, and its measured speed in `docs/validation/benchmarks.md`.

## A strategy in one cell

```python
import polars as pl
import fefat as ff

close = pl.col("close")
strategy = ff.SignalStrategy(
    instrument="MES",
    timeframe="5m",
    features={"highest": close.rolling_max(12).shift(1), "atr": (pl.col("high") - pl.col("low")).rolling_mean(14)},
    long_entry=close > pl.col("highest"),
    short_entry=pl.lit(False),
    execution=ff.Execution(
        entry=ff.Market(),
        stop=ff.Stop(atr=1.5),
        targets=[ff.Target(r=2)],
        sizing=ff.Fixed(1),
    ),
)
run = ff.backtest.run(strategy, "2025-09-01", "2026-09-23", ff.backtest.RunConfig(fidelity="1m"))
run.report()
```

The strategy decides at the close of each 5-minute bar and fills on the finest data each day has, here capped at 1-minute bars. Every run saves itself under its run key, and running the same strategy on the same data again reads the saved run back instead of running it.

## The signal strategy

A `ff.SignalStrategy` holds what the strategy computes, as Polars expressions over the signal bars that `ff.market.load` returns (`docs/data-guide.md`, "Units and the columns of a load"), and how it trades.

| Field | Meaning |
| --- | --- |
| `instrument` | the root it trades, such as `MES`; a run follows the roll calendar's front contracts unless `RunConfig.contract` names one |
| `timeframe` | the signal bars whose closes decide, such as `5m`: a count, then `s`, `m`, `h`, or `d` |
| `features` | a mapping of names to expressions, each evaluated in turn over the bars and the features before it; every trade records each feature's value at its entry as `<feature>_at_entry` |
| `long_entry`, `short_entry` | the entry signals, a boolean expression each; a null counts as false |
| `long_exit`, `short_exit` | the exit signals, false by default; they close the position while `signal_exit` is on |
| `entry_price` | the price of a limit or stop entry at the column, for `Limit(column=True)` and `StopEntry(column=True)` |
| `stop_price`, `target_price` | the prices of a stop or a target at the column, for `Stop(column=True)` and `Target(column=True)` |
| `trail_ref` | the level of a trailing stop at the column, for `Trailing(column=True)` |
| `size_mult` | a multiple of the size on each bar, which must make whole lots |
| `wake` | whether a bar may enter at all, true by default; a null counts as true |
| `execution` | the execution template below |

- Prices in the columns are whole numbers of billionths of a point, like the bars' prices: `close - 4 * 250_000_000` is four MES ticks below the close.
- A feature must be prefix-invariant: its value at a bar may depend only on that bar and the bars before it. Use `shift(1)` to read the bar before; never `shift(-1)`, a centred window, a backward fill, or a rank or a normalisation over the whole sample (D-12). A feature written with `@ff.feature` takes a slot as an expression does, and the leak detector below checks it.
- A feature name may not repeat a column of the bars or of the signal frame.

## The leak detector

`ff.features.validate` checks that a feature never reads ahead: its values before any instant must not change when the data after that instant is removed. Run it on a feature with its parameters, an instrument, a timeframe, and a window of trade dates of at least two sessions, with `reads=` the features it reads, as `ff.features.compute` takes them:

```python
report = ff.features.validate(next_close(), "MES", "5m", "2026-09-09", "2026-09-23")
report.passed           # False
report.first_failure()  # the first cut that changed a value, with the row and both values
print(report.summary())
```

It loads the bars the feature reads once, from its warm-up before the window to one session past it, and computes the feature over them. Then it cuts every input at many instants and computes the feature again on what is left: a bar is kept while it has closed by the cut, so a bar still in progress, of the signal bars or of a higher timeframe the feature reads, is left out, as a load holds back a bar the data has not finished. The prints a feature reads by side are cut the same way, a bucket's kept while it has closed by the cut. The cuts fall at each session's close or a holiday's halt, a nanosecond after it, inside the break or over the weekend, a nanosecond before the next open and at it, at a roll's open and the new front's first bar, inside a higher timeframe's bar and at its close, and at bars drawn from a seed the report records, so that a validation repeats. Every cut lies at or after the close of the window's first session, and one past the end of every input, which removes nothing, is left out.

- **The cuts.** The window's values before each cut must be the whole range's: integers and Booleans exactly, and floats within 1e-9 of the output's largest magnitude among the rows compared, since averages computed over different lengths can differ in their last digits. Each cut counts the values it compared. A cut before an output's first value, early in a window or before a level set on rare bars only, compares none and decides nothing alone, but an output that no cut compares a value of fails the report: a warm-up longer than the data passes nothing.
- **The start check.** The detector computes the window again from the warm-up before its middle trade date and requires the same values from that date on. A feature that remembers more than its declared warm-up, such as a running total or a slow average, fails it. The roll calendar keeps its anchor, so the prices are the same from either start. Where the data does not let the start move, as at the store's first session, the check fails: validate a window with more data before its middle.
- **The lint** reads the feature's code and warns of each line that reads ahead, with why: a negative shift or difference, a backward fill or an interpolation, a centred window or a peak, an aggregate over the whole frame (a mean, a maximum, a rank, quantile bins, the last value) or over a session (`.over("trade_date")`), a reversed column, and an as-of join forward, to the nearest row, or on `ts_open`. The cuts judge these, so a warning does not fail the report, but it shows where to look, and a report that passes with one says `PASSED WITH WARNINGS`. One finding fails the report: data a feature reads itself, with `ff.market.load`, `ff.market.roll_calendar`, `pl.read_parquet`, `open`, and the like, or holds from outside it, such as a frame an earlier notebook cell loaded, since the cuts never cut it; declare it as an input instead. The lint reads the features the validated one reads too, and each finding names its feature. The lint also warns of a helper or a constant the feature reads from outside its own code, and of a default not written as a number or a text, since the feature's hash covers neither.

A report passes when every cut and the start check agree, each output had values compared, and the feature reads no data itself. It records the seed, the numbers of stops and random cuts, and the features read, so that a validation repeats, and it is kept beside the feature's versions, `validations/<hash>.json`, the latest of each version. The tests plant twenty-five leaks and keep twenty-five clean features under `python/tests/features/leaks/`.

What the detector cannot catch:

- a wrong availability time in the data, since it cuts each record at the time the data says it became available, and bars that a later record of their trade date would build from other data;
- revised data, since it reads one vintage of the store;
- parameters chosen on the full sample, such as a threshold picked after looking at the whole history, which change no value it compares;
- a leak in rows or branches its cuts never reach, such as one on a weekday the window lacks, or in a helper the feature calls, whose code the lint does not read;
- a statistic over the whole frame or a session that the window's data settle before every cut, such as a maximum reached early, of which the lint warns;
- a memory longer than the declared warm-up but within the whole sessions every computation reads before a window, which the start check reads too.

A feature that passes is prefix-invariant on these data at these cuts, not proven so.

## The indicators

`ff.indicators` holds the common indicators as features, each giving the numbers TA-Lib gives: the moving averages `sma`, `ema`, and `wma`, `macd`, `rsi`, `stochastic`, `roc`, `momentum`, `adx` with `plus_di` and `minus_di`, `obv`, `true_range`, `atr`, `standard_deviation`, `z_score`, and `bollinger`, `donchian`, and `keltner`. `help(ff.indicators)` prints a table of each with its parameters, its outputs, and its warm-up. Each takes its parameters by name or in their order, and fills a slot of a strategy as any feature does:

```python
features={
    "rsi": ff.indicators.rsi(14),
    "atr": ff.indicators.atr(14),
    "band": ff.indicators.bollinger(n=20, deviations=2.0),
}
```

An indicator of several outputs fills a column for each, the slot's name and the output's, such as `band_upper` and `band_percent_b`. Levels, the averages, bands, and channels, are prices, and distances, ATR, the true range, and the standard deviation, are distances of price, both in the bars' units, so `ff.Stop(atr=1.5)` reads the `atr` slot as it is. A price the signal frame gives, such as a stop at the bar's low less half an ATR, must lie on the tick, and `round_down_to_tick` or `round_up_to_tick` puts it there:

```python
stop_price=ff.indicators.round_down_to_tick(pl.col("low") - pl.col("atr") / 2, "MES")
```

- **Seeding.** An exponential average, in EMA, MACD, RSI, ATR, ADX, and Keltner channels, starts from the simple average of its first values, as TA-Lib's does, so the first values are TA-Lib's too, and every output is null until TA-Lib's first value.
- **Warm-up.** The warm-up is the number of bars an indicator needs before its values mean what they say, and FEFAT reads that many before your window. An exponential average never quite forgets its first bars, so its warm-up is 13 times its period for an EMA, EMA(20)'s 260 bars, 25 times for the averages of RSI and ATR, and 50 times for ADX's: a session or two of 5-minute bars, but 2,600 sessions, ten years, for a daily EMA(200), which leaves it null on a shorter history. On daily bars take an SMA, or a shorter period.
- **Divisions by zero.** Where TA-Lib gives 0 or 50, as for the RSI of closes that have not moved or the stochastic of a flat range, these give no value, which a strategy reads as no signal.
- **OBV** is on-balance volume over the last `n` bars, the volume of the bars that closed up less that of those that closed down, since the running total charts draw depends on where your data starts.
- **Keltner channels** are the EMA of the closes with channels of ATRs, as charts draw them today.

The tests compare every indicator with TA-Lib on a random walk and on the fixtures, and every indicator passes the leak detector.

### The session's indicators

These read the trading session: `session_vwap`, `weekly_vwap`, `vwap_since`, and `distance_from_vwap`; `opening_range`, `previous_session`, `session_high_low`, `time_since_open`, and `bars_since`; `relative_volume` and `cumulative_delta`; `realised_volatility`; and `swings`. `help(ff.indicators)` lists each with its parameters, outputs, and warm-up.

```python
features={
    "vwap": ff.indicators.session_vwap(),
    "cash_vwap": ff.indicators.session_vwap(anchor="08:30"),
    "opening": ff.indicators.opening_range(minutes=30, anchor="08:30"),
    "before": ff.indicators.previous_session(),
}
```

- **Where a session starts.** By default an indicator starts at the session's open, the open every trade date and bar take: 17:00 Chicago the evening before, for CME's equity index. `anchor="08:30"` starts it at a local time of day instead, in the `time_zone` you give, `America/Chicago` by default, on the trade date's own day, as the execution template reads a time. A time of the evening falls after that day's close, so start an evening session at its open, the default.
- **What a session is.** A session is its trade date's bars on the grid, which leaves halts out, and the session before is the trade date before it in the calendar: Friday's for the Tuesday after Presidents' Day. A bar without trades holds the close before it, which no trade in it made, so the VWAPs weigh it at nothing and the levels leave it out.
- **The VWAPs** weigh each bar's own vwap by its volume, or its typical price, the mean of its high, low, and close, where your data has no vwap, as imported 1-minute bars have none. `vwap_since(flag)` starts at the last bar a Boolean column of the bars flags, such as `roll_flag`, and forgets it after the sessions you give.
- **The opening range** is the high and low of the bars that traded wholly inside its window. It appears on the first bar opening once the window has closed, never inside it.
- **Relative volume** is a bar's volume against the mean volume at the same local time of day over the sessions before it, never its own or a later one.
- **Cumulative delta** is the volume bought less the volume sold by aggressors, in each bar and in the session so far. It reads your prints' aggressor sides through the trades input: each bucket's volume bought, sold, and of no side, available at the bucket's close, as a bar is. Prints of no side, such as an opening auction's, are left out. A session whose prints carry no side, as IBKR's do, has no delta at all, never zero, and neither has a trade date without prints. With bars alone it is empty.
- **Swings.** A bar's high is a swing high when it stands above the `n` highs before it and the `n` after it, which only the `n`-th bar after it can show. The swing is flagged on that bar, with its price, and no later bar takes it back.
- **Realised volatility** is the square root of the summed squared log returns of the last `n` closes, not annualised.

Some indicators remember whole sessions: the session before, the week so far, relative volume. They declare a warm-up in sessions, `warmup_sessions`, beside their warm-up in bars, and FEFAT reads that many sessions before your window on any timeframe. A feature of your own does the same: `@ff.feature(warmup_sessions=1, ...)`. Its values count from where the features it reads have their first values: its whole sessions first, then its bars.

## The execution template

`ff.Execution` says how the strategy enters on its signals, how each entry leaves, and what filters entries.

| Option | Meaning | Default |
| --- | --- | --- |
| `entry` | the order an entry signal places: `Market()`, `Limit(...)`, or `StopEntry(...)` | required |
| `on_opposite_signal` | what an entry signal against the open position does: `ignore`, `close`, or `reverse` (close and enter the other way at the same decision) | `ignore` |
| `stop` | the stop-market order placed against the position when an entry fills: `Stop(...)` | none |
| `targets` | up to three limit orders placed when an entry fills, each closing a fraction of the lots still open, one OCO group with the stop: `Target(...)` | none |
| `breakeven` | when the stop moves to the entry's fill price: `Breakeven(...)`; needs a stop | none |
| `trailing` | how the stop follows the price: `Trailing(...)`; needs a stop | none |
| `time` | entry windows and time exits in local time: `TimeRules(...)` | none |
| `limits` | filters on entries: a blackout column, daily limits, a cooldown after a loss, and fresh signals: `Limits(...)` | none of them |
| `sizing` | how many units an entry trades: `Fixed(...)`, `Notional(...)`, or `RiskPerTrade(...)` | required |
| `signal_exit` | whether `long_exit` and `short_exit` close the position | `True` |

Each helper takes one choice by keyword and refuses none or two, so `Stop(ticks=12, atr=1.5)` is an error.

### Entries

- `Market()`: a market order, active the run's latency after the decision, filled at the next price plus the slippage ticks ([F-MKT](spec/fill-semantics.md#5-market-orders-f-mkt)).
- `Limit(offset_ticks=n)`: a limit `n` ticks from the signal bar's close, below it for a buy; `Limit(column=True)` at the row's `entry_price`. It fills only when the market trades through it, at its own price, never better ([F-LMT](spec/fill-semantics.md#7-limit-orders-f-lmt)).
- `StopEntry(offset_ticks=n)` or `StopEntry(column=True)`: a stop-market order, above the close for a buy ([F-STP](spec/fill-semantics.md#6-stop-market-orders-f-stp)).
- `time_to_live_bars`: a limit or stop entry still working at that many decisions after its own is cancelled; without it, it works until it fills or a time rule cancels it.
- With a limit or stop entry, a bar that gives both entry signals places a buy and a sell as one OCO group; with a market entry such a bar is refused.

### Stops

`Stop(...)` places one stop-market order for all the entry's lots ([F-PLN](spec/fill-semantics.md#22-exit-plans-f-pln)):

- `ticks`: that many ticks from the fill price;
- `percent`: that percentage of the fill price from it, `0.5` being 0.5 %;
- `atr`: that multiple of the entry bar's `feature` (by default the feature named `atr`) from the fill;
- `column`: at the entry row's `stop_price`.

Computed distances are rounded to whole ticks, at least one, down for a stop so that it never lies farther than asked ([F-RND](spec/fill-semantics.md#21-rounding-f-rnd)).

### Targets

`Target(...)` places one limit order, at most three of them:

- `ticks`, `atr` (with its `feature`), or `column` as for the stop, in the position's favour, rounded up so that a target never lies nearer than asked;
- `r`: that multiple of the trade's initial risk, the ticks from its fill to its first stop, which needs a stop;
- `fraction`: the share of the lots still open that it closes, `1.0` (the rest) by default. Three lots under fractions 0.5, 0.5, and 1 make targets of one lot each.

When a target fills, the stop is cut to the lots still open; when the stop fills, the targets are cancelled.

### Breakeven

`Breakeven(...)` moves the stop to the entry's fill price, `offset_ticks` beyond it (below zero, short of it), once the trade first reaches `ticks` ticks of profit, `r` times its initial risk, or once target `after_target` (counted from 1) fills ([F-BRK](spec/fill-semantics.md#23-breakeven-f-brk)). A stop only ever moves in the position's favour, and never to or past the market.

### Trailing stops

`Trailing(...)` keeps the stop `ticks` ticks, or `atr` times the signal bars' `feature`, behind the best price since its activation, or at each row's `trail_ref` with `column` ([F-TRL](spec/fill-semantics.md#24-trailing-stops-f-trl)):

- `step_ticks`: moves the stop in whole steps of that many ticks, every tick without it;
- `activation`: from when it works, the entry's fill without it; it takes a trigger from `ff.strategy`: `TicksTrigger(ticks=8)`, `RMultipleTrigger(multiple=1)`, or `AfterTargetTrigger(target=1)`;
- `update`: `intrabar`, moving at every price the engine marks, or `bar_close`, moving at decisions alone, which a trailing stop by the column needs and gets by default.

### Sizing

- `Fixed(units)`: the same units on every entry, contracts for futures, times the row's `size_mult` where the frame has one ([F-SIZ](spec/fill-semantics.md#28-sizing-f-siz)).
- `Notional(amount)`: the whole lots whose value at the entry is at most `amount` in the account's currency.
- `RiskPerTrade(amount=...)` or `RiskPerTrade(percent=...)`: the whole lots that lose at most that amount, or that percentage of equity, at the stop; it needs a stop.

### Time rules

`TimeRules(...)` works in the local time of `tz`, such as `America/Chicago`, through the session table, so that a clock change moves the instants and never the local times ([F-TIM](spec/fill-semantics.md#26-time-rules-f-tim)):

- `windows`: entry windows, each an `EntryWindow(start, end, weekdays)` or a `("08:35", "14:30")` pair; an entry is placed only at a decision from `start` to just before `end`, on one of its `weekdays` (every day without them); a window whose `end` comes before its `start` runs past midnight;
- `flat_by`: from this local time each trade date, the position is closed, working orders are cancelled, and no entry is placed;
- `max_bars`, `max_minutes`: the position is closed at that many decisions, or at the first decision that many minutes, after its entry's fill;
- `no_overnight`: closes the position before each stop of trading, a session's close or a holiday's halt;
- `no_weekend`: closes it before each weekend's break.

### Entry limits

`Limits(...)` filters entries ([F-LIM](spec/fill-semantics.md#27-entry-limits-f-lim)):

- `blackout`: the name of a boolean feature; a row where it is true places no entry;
- `max_trades_per_day`, `max_losses_per_day`: no entry once a trade date's entries, or its losing trades, reach that count;
- `daily_loss_stop`, `profit_lock`: no entry once that trade date's closed trades have lost, or made, that amount in the account's currency;
- `cooldown_after_loss`: no entry for a while after a losing trade, `BarsCooldown(bars=n)` decisions or `MinutesCooldown(minutes=n)` minutes, both from `ff.strategy`;
- `fresh_signal`: an entry signal counts only on a row where it was false on the row before, so that a signal still true after an exit does not enter again.

### Rules that need a stop

A specification is refused before it runs when a breakeven, a trailing stop, a target in R, or a risk size comes without a stop, since each counts from the stop's distance; when `after_target` names a target the specification does not have; and when a trailing stop by the column moves `intrabar`. `strategy.to_spec().document_json()` prints the document the engine reads, the same one `run.json` keeps under `strategy`.

## Run settings

`ff.backtest.RunConfig` holds how a run fills. A setting left out takes its default, and the run's record writes every value in, so that a run always says what it ran under.

| Setting | Meaning | Default |
| --- | --- | --- |
| `fidelity` | the finest data the run fills on, `trades`, `tbbo`, or bars such as `1m`; each trade date fills on its finest level at or coarser than this (D-58) | the finest the store holds |
| `latency_ms` | from a decision to its orders' activation ([F-ACT](spec/fill-semantics.md#4-activation-f-act)); exit plans placed at a fill take none | `100` |
| `slippage_ticks` | whole ticks against you on market and stop fills, `SlippageTicks(market=1, stop=1)` from `fefat.reference.settings` ([F-SLP](spec/fill-semantics.md#12-slippage-f-slp)) | one each on trades and bars, none on TBBO |
| `limit_fill` | `through`: a limit fills when the market trades past it; `touch`: a price at the limit is enough, the optimistic bound | `through` |
| `roll_handling` | at a futures roll, `transfer` the position to the new front with two market orders, or `flatten` it ([F-ROL](spec/fill-semantics.md#29-rolls-f-rol)) | `transfer` |
| `fee_table` | `retail-default`, `prop-topstep`, or `binance-default` ([F-FEE](spec/fill-semantics.md#14-fees-funding-and-money-f-fee-f-fnd)) | `retail-default` for futures, `binance-default` for crypto |
| `capital` | the starting cash, in the instrument's currency | `50000` |
| `replay` | `skipping`, which passes over records no order can act on, or `full`; both give the same fills | `skipping` |
| `provider` | whose datasets the run reads, as `load` takes it | the catalog's recommended source |
| `contract` | one contract of the root, read unspliced, so that the run crosses no roll | the roll calendar's fronts |

Every run is also rerun at one more tick of slippage, which `run.metrics.pnl_at_plus_one_tick` reports, and, where its trade dates are finer than a minute, at one second and at one minute: `run.metrics.fidelity_check`, or `ff.backtest.fidelity_check(run)`, compares those reruns with the run.

## The fill rules in brief

Fills follow [the fill specification](spec/fill-semantics.md), which the Python reference engine implements rule by rule and the Rust engine matches exactly. In brief:

- **Decisions at bar closes.** The strategy decides at each signal bar's close, and its orders become active the latency later. Nothing acts on a record before it was received ([F-CLK](spec/fill-semantics.md#3-clock-and-order-of-events-f-clk), [F-ACT](spec/fill-semantics.md#4-activation-f-act)).
- **The finest data, day by day.** Each trade date fills on its finest level at or coarser than the run's fidelity: trades, TBBO, 1-second, or 1-minute bars ([order type by fidelity](spec/fill-semantics.md#17-order-type-by-fidelity)). The run records each date's level as its fidelity eras.
- **Market orders** fill at the next price after their activation, plus the slippage ticks ([F-MKT](spec/fill-semantics.md#5-market-orders-f-mkt)).
- **Stops** trigger when the market trades at or through them, and fill at the stop plus the slippage ticks, or at the first price past it after a gap, whichever is worse ([F-STP](spec/fill-semantics.md#6-stop-market-orders-f-stp), [gaps](spec/fill-semantics.md#9-gaps)).
- **Limits** fill when the market trades through them, at their own price, never better ([F-LMT](spec/fill-semantics.md#7-limit-orders-f-lmt)).
- **Bars** replay as their open, the extreme against the open position, the extreme in its favour, and their close; a bar whose other order would fill differently flags its fills `ambiguous` ([F-BAR](spec/fill-semantics.md#8-replaying-bars-f-bar)).
- **Exit plans** are placed the moment their entry fills, with no latency, and when one record reaches both the stop and a target, the stop fills ([F-OCO](spec/fill-semantics.md#11-brackets-and-oco-groups-f-oco)).
- **Orders fill whole**, and a fill larger than its record's size is flagged `size_exceeded` ([F-QTY](spec/fill-semantics.md#13-quantities-f-qty)).
- **Costs and marks.** Fees come from the run's fee table by trade date, funding applies to perpetuals, and an open position is marked at the last trade seen ([F-FEE, F-FND](spec/fill-semantics.md#14-fees-funding-and-money-f-fee-f-fnd), [F-MRK](spec/fill-semantics.md#15-marking-open-positions-f-mrk)).
- **The template's own rules**: [decisions and entries](spec/fill-semantics.md#25-decisions-and-entries-f-ent), [exit plans](spec/fill-semantics.md#22-exit-plans-f-pln), [rounding](spec/fill-semantics.md#21-rounding-f-rnd), and [rolls](spec/fill-semantics.md#29-rolls-f-rol).

Every fill records the rule that priced it, which `run.explain` prints.

## Reading a run folder

Each run is saved in `%LOCALAPPDATA%\FEFAT\workspaces\default\artifacts\runs\<run key>\`, under `FEFAT_HOME` wherever you moved it. The folder's name is the run key, a hash of the strategy's document, its signal frame, the snapshots of the data it read, its settings, and the engine's versions, so a change to any of them makes a new run and a repeated run reads the old one. A run saved by another version of the engine is refused by name; delete its folder to run it again. `ff.backtest.Run.open(folder)` opens a saved run.

The units are the store's: prices in billionths of a point, money in millionths of the account's currency, and instants in nanoseconds since 1970-01-01, UTC.

| File | Holds | From Python |
| --- | --- | --- |
| `run.json` | the run's record: `run_id`, `run_key`, the engine's `versions`, the `strategy` document and its features, the `window`, the `instrument`, the `datasets` read with their snapshots, the `signal_frame_hash`, the `signal_bar_eras`, the level each era of its signal bars' trade dates was built from, every setting in `config`, the `fee_table`, the `rolls`, the `engine_config`, the `fidelity_eras`, the `path_fidelities`, its `warnings`, the `summary`, and the `metrics` | `run.record`, `run.metrics`, `run.report()` |
| `fills.parquet` | each fill: its order and role (`entry`, `stop`, `target_1`, an exit reason, or a roll's leg), side, lots, time, price, the rule that priced it, its fidelity, maker or taker, its slippage ticks, its flags, its fee, the cash it moved, its contract, and its trade date | `run.fills` |
| `orders.parquet` | every order in its last state: its kind, price, lots, role, when it was placed and became active, its OCO group, the entry it belongs to, and its state | `run.orders` |
| `log.parquet` | the event log: each placement, activation, move, cancellation, and fill, with its order and its rule | `run.log` |
| `costs.parquet` | each fee and funding payment, paid amounts positive | `run.costs` |
| `trades.parquet` | a row per trade, flat to flat: entry and exit, their contracts, the exit reason, the rolls crossed, gross and net profit and loss, fees, funding, the initial risk and the R multiple, the excursions against and for it (`mae_ticks`, `mfe_ticks`), its deepest fall from its peak, its path's fidelity, and each feature at its entry | `run.trades` |
| `trade_paths.parquet` | a row per point of each trade's price path, below | `run.trade_paths` |
| `equity.parquet` | the account after each decision: cash, position, mark, and equity | `run.equity(strategy.timeframe)` |
| `equity_daily.parquet` | the account at each trade date's last decision, with the day's profit and loss | `run.equity("1d")` |
| `signals.parquet` | the signal frame the engine read, the features among its columns | `run.signals` |

`python/fefat/src/fefat/backtest/schemas.py` lists every column of every file. Polars reads any of them without FEFAT, for example `pl.read_parquet(folder / "trades.parquet")`.

### Trade paths

`trade_paths.parquet` keeps each trade's compact price path, what a prop firm's trailing drawdown needs (`docs/masterplan/03-prop-simulator.md` §4.2):

- `trade`: the trade's row in `trades.parquet`, counted from 0, so `run.trades.with_row_index("trade")` joins the two;
- `ts` and `price`: the point's instant and its price, in the trade's entry contract's prices, so a path stays continuous across a roll;
- `kind`: `fill` for each of the trade's fills, at its own price; `favourable` for each new best price; `adverse` for each new worst price since the last best; `minute` for the mark at each whole minute; and `possible_adverse` for a bar in which the price could have fallen further than its replay shows, since a bar does not say which of its extremes came first;
- `order`: a fill's order, empty for every other point.

The `path_fidelity` of each trade in `trades.parquet` is the coarsest data its path's points came from, and `run.json` counts the trades of each path fidelity. Points in ticks from the entry are `(price - entry_price) / (tick_size * 1e9)`, which the tutorial plots.

### Explaining a trade

`run.explain(entry_order)` takes a trade's `entry_order` from `trades.parquet` and replays it through the reference engine on the run's own records: it prints each event with its rule, each fill with its rule and slippage, and the bar that priced a fill on bars, and it raises an error if the two engines disagree.
