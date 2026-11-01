# Engine benchmarks

Written by `just bench` on 2026-11-01 (step 2.15, `docs/masterplan/02-engine-and-data.md` §4 and §8 item 7, D-68): how fast the engine runs a signal strategy over a generated year of ES, measured on this PC, which is the reference. The targets were missed by more than twice, so the step profiled the engine and, with your approval, fixed three hot spots that change no output; both sets of numbers are below. The Benchmarks job in CI measures the same on GitHub's runners and warns when the engine slows by more than 30 % against the runner's own baseline.

## Machine

- AMD Ryzen 9 9950X, 16 cores and 32 threads, 4.3 GHz base clock.
- 61.7 GB of memory visible to Windows 11 Pro 10.0.26200.
- `FEFAT_HOME`, and with it the generated year and its engine cache, on an SSD over USB; every benchmark first runs once untimed, so its cache files are read from memory.
- Rust 1.99.1 (`engine/rust-toolchain.toml`) in cargo's `bench` profile, an optimised build; criterion 0.8.2 (D-68).

## The dataset

The generated year of step 2.7, generated again for this step so that this PC and CI measure the same year (the copy from 2026-10-27 held 260 weekdays, holidays included):

```text
uv run python scripts/gen_fixtures.py --out <FEFAT_HOME>/cache/synthetic-es-2026-01-02-2026-12-31/data/synthetic --dates 2026-01-02..2026-12-31 --contracts ESH2026 --planted-gaps 3
```

`just bench` runs this, with the default seed 20260308, when the year is missing, and builds its engine cache with `build_engine_cache`, both under `FEFAT_HOME`, never in the repository (D-51). Every session holds trades, 1-second bars, and 1-minute bars, about 71,000 trades a session, with three quiet stretches and three price jumps each.

| What | Count |
| --- | ---: |
| Trade dates, CME's equity index calendar from 2026-01-02 to 2026-12-31 | 252 |
| Trades | 17,864,735 |
| 1-second bars | 7,699,099 |
| 1-minute bars | 346,149 |
| Parquet files | 451.7 MB |
| Engine cache | 928.4 MB |

## The strategy

The run step 2.7 timed (`engine/crates/fefat-cli/benches/engine.rs`): at each 5-minute close, 69,550 of them built from the 1-minute bars, a long entry when the close is above the close 12 bars before and a short entry when it is below; a market entry of one lot with a stop 16 ticks and a target 32 ticks away, one position at a time; each trade date filled on its trades, replayed skipping what no order can act on, with 100 ms of latency, one tick of slippage, no fees, and the market open around the clock. It trades all year: 14,557 fills in 7,278 trades, the same before and after the fixes.

## Results

Three runs of `just bench` before the fixes and three after, each a fresh process with nothing else running; each number is criterion's median of ten samples, whose spread stayed under 2 % of it.

| Benchmark | What it runs | Before the fixes | After the fixes |
| --- | --- | ---: | ---: |
| `single_run/with_paths` | the year, recording each trade's path, 2,174,527 points, as every saved run does | 1.586 to 1.595 s | 0.809 to 0.835 s |
| `single_run/without_paths` | the same run recording no paths, as a sweep's trials run | 0.343 s | 0.207 to 0.216 s |
| `batch/1000_runs_one_month` | 1,000 runs over January's 20 trade dates, stops of 4 to 28 ticks by targets of 8 to 86, on 32 threads, as `fefat_engine.run_batch` runs a sweep | 1.314 to 1.327 s | 0.851 to 0.864 s |

The batch runs one month, not the year: criterion takes at least ten samples, which would keep 1,000 runs of the year running for about three minutes here and far longer on a runner with two cores.

## Against the targets

The targets of `02-engine-and-data.md` §4 hold for a five-year run of ES, about 380 million ticks. The generated year holds 17.9 million trades, so five years of real ES are between 5 times its work, where the engine's time follows the sessions, as skipping over bars does, and 21 times, where it follows the ticks, as reading every record does. The batch's month scales to its year by 252 trade dates over 20. Each cell gives five years at both scales, from the medians.

| Target for five years of ES | Before the fixes | After the fixes | Missed by, after |
| --- | ---: | ---: | ---: |
| A signal strategy with trade paths: under 3 s | 8.0 to 33.9 s | 4.2 to 17.7 s | 1.4 to 5.9 times |
| The same without paths, as sweep trials: under 0.5 s | 1.7 to 7.3 s | 1.1 to 4.5 s | 2.1 to 9.0 times |
| 1,000 runs of execution parameters: under 30 s | 83 to 352 s | 54 to 231 s | 1.8 to 7.7 times |

Before the fixes every target was missed by more than twice even at the smaller scale; after them, two of the three come within twice at that scale. The rest of the gap is mostly the trade paths' descents below.

## Where the time went

The profile is two recordings of 20 seconds each, the year with paths and without, made with cargo-flamegraph 0.6.14 on the benchmark built with debug information (`CARGO_PROFILE_BENCH_DEBUG=true`), from an administrator terminal, since its Windows recorder needs one. samply was the first choice, but it records through the Windows Performance Toolkit, and Microsoft's server serves a documentation file that matches neither release of the kit that holds it (D-68). Shares of each run's time, before the fixes:

| Where | With paths | Without paths |
| --- | ---: | ---: |
| The skip check, `TickRun::skippable` | 34 % | 32 % |
| Skipping blocks, `TickRun::skip` | 22 % | 31 % |
| Reading records one by one, `TickRun::receive` | 24 % | 16 % |
| Picking the next event, `TickRun::next_event` | 19 % | 17 % |
| A new list of order ids at every record, `Book::ids_in` | 17 % | 16 % |
| Recording the path itself, `PathRecorder` | under 1 % | none |

Recording paths costs almost nothing in itself: it makes the engine read far more trades one by one, because with a trade open its path restarts at every whole minute and nearly every minute's first block can set a new high or low of it. Each record read one by one then paid three overheads, which the three fixes removed, each measured by one run of `just bench`:

| Fix | With paths | Without paths | Batch |
| --- | ---: | ---: | ---: |
| None | 1.591 s | 0.343 s | 1.314 s |
| One reused list of order ids, where every loop over live orders allocated a new one | 1.263 s | 0.286 s | 1.103 s |
| The next event picked by comparing the three candidates' keys, without building them | 1.073 s | 0.250 s | 0.965 s |
| A level's refusal to skip kept for its block while nothing it read changes | 0.824 s | 0.211 s | 0.851 s |

No output changed: the determinism digest, the backtest golden, the scenarios through both engines, and the differential and skip-equals-full tests all pass, and the generated year run in full replay and skipping gives the same tables, with paths and without. So no version moved.

## What is left

- With paths, the year still takes about four times as long as without them, because a recorded path makes the engine descend to the trades wherever a block can add a point to it. A path that takes a skipped block's extremes from its bar where their order cannot matter would change the artifacts, which the prop simulator reads; `BACKLOG.md` gives it to step 13.5.
- Through the SDK, the tutorial's five-year run of MES on 1-minute bars takes about 9 s once the engine's cache is built (9.2 to 9.3 s over three fresh processes), of which the engine is under a second. A Python profile puts more than half of it in checking that the cache's 61 months still match the store, each month listing the dataset's partition files again; `BACKLOG.md` gives it to step 13.5 too.

## The runner baseline

The Benchmarks job of `.github/workflows/ci.yml` runs `just bench --baseline docs/validation/benchmarks-ci-baseline.json` on `ubuntu-latest` for every pull request and every push to main: it generates the year, runs the three benchmarks, writes their medians beside the baseline's into the job's summary, and warns on a benchmark more than 30 % slower, without failing, since shared runners vary too much for a gate (`02` §8 item 7) and the numbers on this PC decide. `docs/validation/benchmarks-ci-baseline.json` holds the medians of one runner's run, with its date and link; after a deliberate change to the engine's speed, copy the JSON block from a later run's summary into it.

## Reproduce

```text
just bench                    # generates the year first when it is missing, about 2.5 minutes
just bench --baseline docs/validation/benchmarks-ci-baseline.json
```

To profile, build the benchmark with debug information and record it from an administrator terminal, with `FEFAT_BENCH_CONTRACT` naming the year's ESH2026 cache folder, `<FEFAT_HOME>/cache/synthetic-es-2026-01-02-2026-12-31/cache/engine/synthetic/ES/ESH2026`:

```text
CARGO_PROFILE_BENCH_DEBUG=true cargo bench -p fefat-cli --bench engine --no-run
flamegraph -o paths.svg -- <the benchmark executable cargo printed> --bench --profile-time 20 single_run/with_paths
```
