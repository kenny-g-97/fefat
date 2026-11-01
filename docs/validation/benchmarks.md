# Engine benchmarks

Written by `just bench` on 2026-11-01 (step 2.15, `docs/masterplan/02-engine-and-data.md` §4 and §8 item 7, D-68): how fast the engine runs a signal strategy over a generated year of ES, measured on this PC, which is the reference. The Benchmarks job in CI measures the same on GitHub's runners and warns when the engine slows by more than 30 % against the runner's own baseline.

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

The run step 2.7 timed (`engine/crates/fefat-cli/benches/engine.rs`): at each 5-minute close, 69,550 of them built from the 1-minute bars, a long entry when the close is above the close 12 bars before and a short entry when it is below; a market entry of one lot with a stop 16 ticks and a target 32 ticks away, one position at a time; each trade date filled on its trades, replayed skipping what no order can act on, with 100 ms of latency, one tick of slippage, no fees, and the market open around the clock. It trades all year: 14,557 fills in 7,278 trades.

## Results

Three runs of `just bench`, each a fresh process with nothing else running; each number is criterion's median of ten samples, whose spread stayed under 1 % of it.

| Benchmark | What it runs | Median over three runs |
| --- | --- | ---: |
| `single_run/with_paths` | the year, recording each trade's path, 2,174,527 points, as every saved run does | 1.586 to 1.595 s |
| `single_run/without_paths` | the same run recording no paths, as a sweep's trials run | 0.343 s |
| `batch/1000_runs_one_month` | 1,000 runs over January's 20 trade dates, stops of 4 to 28 ticks by targets of 8 to 86, on 32 threads, as `fefat_engine.run_batch` runs a sweep | 1.314 to 1.327 s |

The batch runs one month, not the year: criterion takes at least ten samples, which would keep 1,000 runs of the year running for about three minutes here and far longer on a runner with two cores.

## Against the targets

The targets of `02-engine-and-data.md` §4 hold for a five-year run of ES, about 380 million ticks. The generated year holds 17.9 million trades, so five years of real ES are between 5 times its work, where the engine's time follows the sessions, as skipping over bars does, and 21 times, where it follows the ticks, as reading every record does. The batch's month scales to its year by 252 trade dates over 20.

| Target for five years of ES | Measured | Five years, ×5 | Five years, ×21 | Missed by |
| --- | ---: | ---: | ---: | ---: |
| A signal strategy with trade paths: under 3 s | 1.59 s | 7.9 s | 33.8 s | 2.6 to 11 times |
| The same without paths, as sweep trials: under 0.5 s | 0.343 s | 1.7 s | 7.3 s | 3.4 to 15 times |
| 1,000 runs of execution parameters: under 30 s | 1.32 s for a month, 16.6 s for the year | 83 s | 354 s | 2.8 to 12 times |

Every target is missed by more than twice even at the smaller scale. Recording paths makes the run on trades 4.6 times as long as the run without them, where on five years of 1-minute bars it added a fifth (step 2.13).

## The runner baseline

The Benchmarks job of `.github/workflows/ci.yml` runs `just bench --baseline docs/validation/benchmarks-ci-baseline.json` on `ubuntu-latest` for every pull request and every push to main: it generates the year, runs the three benchmarks, writes their medians beside the baseline's into the job's summary, and warns on a benchmark more than 30 % slower, without failing, since shared runners vary too much for a gate (`02` §8 item 7) and the numbers above decide. `docs/validation/benchmarks-ci-baseline.json` holds the medians of one runner's run, with its date and link; after a deliberate change to the engine's speed, copy the JSON block from a later run's summary into it.

## Reproduce

```text
just bench                    # generates the year first when it is missing, about 2.5 minutes
just bench --baseline docs/validation/benchmarks-ci-baseline.json
```
