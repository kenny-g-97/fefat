# Mutation testing of the engine

Written at the Phase 2 exit on 2026-11-02 (`docs/masterplan/02-engine-and-data.md` §8 item 7, D-68, D-70): how many deliberate small faults in `fefat-engine`, the tick and bar loop, the order book, the exit plans, the execution template, and the rules, the tests notice. A fault the tests do not notice, a missed mutant, marks code whose behaviour no test pins.

## How it was measured

1. `cargo mutants --package fefat-engine -j 8` (cargo-mutants 27.1.0, `just mutants -j 8`) on `origin/main` at `7b0c250`, in a clean worktree on this PC (AMD Ryzen 9 9950X), with the crate's own Rust tests: 995 mutants in 25 minutes, 207 that do not compile (unviable), 788 viable.
2. The engine's own tests do not run the scenario tables, which pytest holds both engines to (`python/tests/test_rust_engine_scenarios.py`, 252 scenarios under both replays). So each mutant the crate's tests missed was applied again at the span cargo-mutants recorded, `fefat-cli` rebuilt in release, and the scenario tables run through it, stopping at the first scenario that fails: about 9 seconds a mutant. One missed mutant was checked by hand: the mutated engine compiled, the binary was rebuilt, and all 302 scenario runs passed, so the verdicts are the mutated engine's.

A mutant that made a test run past its time limit (14) counts as caught.

## Results

| Code | Viable mutants | Caught by the engine's tests | Caught by the scenarios as well | Missed by both | Caught |
| --- | ---: | ---: | ---: | ---: | ---: |
| The fill code: `tick_run/` fills, bars, records, descent, rolls, timers, execution, outcomes; `book/`; `exit_plan/`; `rules.rs` | 380 | 327 | 29 | 24 | 93.7 % |
| The execution template, `template/` | 139 | 57 | 64 | 18 | 87.1 % |
| The rest of the crate: the strategy context, trades, paths, the tick loop's core, hours, the event log, settings, decimals | 269 | 227 | 16 | 26 | 90.3 % |
| The whole crate | 788 | 611 | 109 | 68 | 91.4 % |

The fill code reaches the 90 % that `02` §8 item 7 sets when the scenario tables count, and 86.1 % on the engine's own tests; the whole crate 91.4 % and 77.5 %. Every mutant of `tick_run/fills.rs` that step 2.15 found missed (`tradeable`'s negations, `limit_on_record`'s `!traded` guard, `record_on`'s `&&`) fails a scenario.

## What is still missed, and why

The 68 mutants that pass both, by kind:

- **Work saved, outputs alike (7).** `Book::give_back_ids` made a no-op, the reused list of order ids of step 2.15; four mutants of `tick_run/descent.rs` (`skippable`, `beyond`) and two of `PathRecorder::can_skip` that change where the skipping replay descends, which skip-equals-full holds to the full replay's outputs. Likely equivalent; not proven.
- **A case no instrument has (5).** `next_timer`'s order between a funding time and a roll at one instant: perpetuals pay funding and never roll, futures roll and pay none.
- **Text no test reads (2).** `event_log.rs`'s `described`, a log line's wording.
- **Tables the scenarios do not hold (12).** Nine mutants of `tick_run/trades.rs` (a reversing fill's split, `is_open`, a count's lots) and three of `tick_run/paths.rs` (`marked`, `reach`, `keeps_every_mark`): the trades and trade-path tables, which the scenario tables do not compare and the backtest golden and differential do, outside this measurement.
- **Rules no test reaches (42).** An entry stop triggered on TBBO and still on its way at a later decision (`Book::is_entering`, `DecisionContext::is_entering`, 5); `Book::on_its_way_out`'s `&&`; the exit plans' `trailing_at_decision`, `held_short`, `waiting_triggers`, `ExitPlan::shift_by`, and `f_trl_03`; `TradingHours::is_open_throughout` (3); `f_bar_07` (2); `judge_leg`'s limit guard; `next_event`'s decision guard; `are_bars`; `ExactDecimal::over`; in the strategy context, `require_flat` (2), `enter`, and `cancel_entries_placed_by`; and in the template (18), `f_ent_04`, `f_lim_03`, `f_lim_04`, `count`, `f_tim_02`'s bound, the order of `on_decision`'s checks, `require_trade_dates`, and `sizing.rs`'s `stop_for`, `lots_within`, and its two `lots >= 1` guards.

`docs/masterplan/BACKLOG.md` lists the rules no test reaches for scenarios or Rust tests, in the step that next changes each rule. The full list, as cargo-mutants names each mutant:

```text
book/mod.rs:192:54: replace && with || in Book::on_its_way_out
book/mod.rs:296:9: replace Book::give_back_ids with ()
book/mod.rs:404:9: replace Book::is_entering -> bool with false
book/mod.rs:405:30: replace == with != in Book::is_entering
book/mod.rs:405:50: replace && with || in Book::is_entering
book/mod.rs:405:65: replace == with != in Book::is_entering
event_log.rs:338:5: replace described -> String with "xyzzy".into()
event_log.rs:338:5: replace described -> String with String::new()
exact_decimal.rs:66:22: replace > with >= in ExactDecimal::over
exit_plan/live.rs:254:34: replace && with || in LivePlan::trailing_at_decision
exit_plan/live.rs:365:34: replace && with || in LivePlan::held_short
exit_plan/live.rs:420:25: delete ! in LivePlan::waiting_triggers
exit_plan/mod.rs:141:9: replace ExitPlan::shift_by -> Result<(), Overflow> with Ok(())
exit_plan/mod.rs:341:40: replace * with + in f_trl_03
hours.rs:75:83: replace < with <= in TradingHours::is_open_throughout
hours.rs:75:83: replace < with == in TradingHours::is_open_throughout
hours.rs:80:15: replace < with <= in TradingHours::is_open_throughout
rules.rs:256:18: replace > with >= in f_bar_07
rules.rs:256:5: replace f_bar_07 -> bool with true
strategy/mod.rs:164:9: replace DecisionContext<'run>::is_entering -> bool with false
strategy/mod.rs:210:53: replace > with >= in DecisionContext<'run>::enter
strategy/mod.rs:233:66: replace && with || in DecisionContext<'run>::cancel_entries_placed_by
strategy/mod.rs:249:46: replace || with && in DecisionContext<'run>::require_flat
strategy/mod.rs:249:9: replace DecisionContext<'run>::require_flat -> Result<(), DecisionError> with Ok(())
template/entries.rs:84:44: replace && with || in f_ent_04
template/limits.rs:156:62: replace < with <= in EntryLimits::f_lim_03
template/limits.rs:177:41: delete ! in f_lim_04
template/limits.rs:177:9: delete field short_entry from struct SignalRow expression in f_lim_04
template/limits.rs:94:28: replace < with <= in EntryLimits::count
template/mod.rs:119:66: replace < with <= in TemplateStrategy::f_tim_02
template/mod.rs:266:33: replace || with && in <impl Strategy for TemplateStrategy>::on_decision
template/mod.rs:270:35: replace != with == in <impl Strategy for TemplateStrategy>::on_decision
template/mod.rs:270:53: replace || with && in <impl Strategy for TemplateStrategy>::on_decision
template/rows.rs:175:9: replace || with && in require_trade_dates
template/rows.rs:176:9: replace || with && in require_trade_dates
template/sizing.rs:101:23: replace match guard lots >= 1 with true in f_siz_01
template/sizing.rs:212:27: replace < with <= in stop_for
template/sizing.rs:213:28: replace > with < in stop_for
template/sizing.rs:213:28: replace > with == in stop_for
template/sizing.rs:213:28: replace > with >= in stop_for
template/sizing.rs:232:44: replace > with >= in lots_within
template/sizing.rs:245:23: replace match guard lots >= 1 with true in fixed_lots
tick_run/bars.rs:379:43: replace match guard rules::limit_past(self.settings, side, limit, point) with false in BarReplay<'replay>::judge_leg
tick_run/descent.rs:116:52: replace < with <= in TickRun<'_, R>::skippable
tick_run/descent.rs:128:36: replace > with >= in TickRun<'_, R>::skippable
tick_run/descent.rs:201:37: replace match guard of_bars with false in beyond
tick_run/descent.rs:202:9: delete match arm (OrderState::Waiting, _) in beyond
tick_run/mod.rs:277:34: replace match guard first == decision_key with true in TickRun<'run, R>::next_event
tick_run/paths.rs:182:63: replace > with >= in PathRecorder::marked
tick_run/paths.rs:214:15: replace != with == in PathRecorder::reach
tick_run/paths.rs:233:67: replace < with <= in PathRecorder::can_skip
tick_run/paths.rs:236:60: replace < with <= in PathRecorder::can_skip
tick_run/paths.rs:288:9: replace PathRecorder::keeps_every_mark -> bool with false
tick_run/records.rs:141:9: replace DayRecords<'run>::are_bars -> bool with false
tick_run/timers.rs:75:44: replace match guard funding.at() < roll.at() with false in TickRun<'_, R>::next_timer
tick_run/timers.rs:75:44: replace match guard funding.at() < roll.at() with true in TickRun<'_, R>::next_timer
tick_run/timers.rs:75:57: replace < with <= in TickRun<'_, R>::next_timer
tick_run/timers.rs:75:57: replace < with == in TickRun<'_, R>::next_timer
tick_run/timers.rs:75:57: replace < with > in TickRun<'_, R>::next_timer
tick_run/trades.rs:201:53: replace > with >= in TradeBook::filled
tick_run/trades.rs:201:72: replace > with >= in TradeBook::filled
tick_run/trades.rs:246:13: delete field lots from struct Fill expression in TradeBook::reversed
tick_run/trades.rs:247:13: delete field fee from struct Fill expression in TradeBook::reversed
tick_run/trades.rs:252:13: delete field fee from struct Fill expression in TradeBook::reversed
tick_run/trades.rs:256:13: delete field fill from struct TradedFill expression in TradeBook::reversed
tick_run/trades.rs:258:13: delete field flat_after from struct TradedFill expression in TradeBook::reversed
tick_run/trades.rs:342:9: replace TradeBook::is_open -> bool with true
tick_run/trades.rs:399:55: replace * with / in OpenTrade::count
```

## Running it again

`just mutants -j 8` repeats step 1 in about 25 minutes, and `just mutants -f crates/fefat-engine/src/tick_run/fills.rs -j 4` one file in about two. Step 2 was a scratch script of the exit; the backlog's item on these mutants asks for it as a recipe before the next phase whose exit runs it.
