"""The engine's benchmarks (step 2.15, D-68): `scripts/bench.py` builds the generated year they
run on once, reads criterion's medians, compares them with a stored baseline, and warns above a
30 % regression without failing the run; `just bench` runs it."""

import json
import os
from datetime import date
from pathlib import Path

import pytest
import yaml

import bench
from fefat.config import resolve_paths
from fefat.market.engine_cache import EngineCacheBuild

ROOT = Path(__file__).resolve().parents[2]

CRITERION_OUTPUT = """\
year: 252 trade dates, 17923456 trades, 4201234 1-second bars, 347760 1-minute bars
single_run: 69552 signal rows
single_run/with_paths: 14557 fills, 7278 trades, 523401 path points
test single_run/with_paths ... bench:   412,345,678 ns/iter (+/- 3,456,789)
single_run/without_paths: 14557 fills, 7278 trades, 0 path points
test single_run/without_paths ... bench:   301,000,000 ns/iter (+/- 2,000,000)

batch: 1000 runs over 20 trade dates on 32 threads, 1234567 fills in all
test batch/1000_runs_one_month ... bench: 1,850,000,000 ns/iter (+/- 40,000,000)
"""

MEDIANS = {
    "single_run/with_paths": 412_345_678,
    "single_run/without_paths": 301_000_000,
    "batch/1000_runs_one_month": 1_850_000_000,
}
BATCH = "batch/1000_runs_one_month"


def test_the_medians_are_read_from_criterions_bencher_lines() -> None:
    assert bench.parse_medians(CRITERION_OUTPUT) == MEDIANS


def test_output_without_a_benchmark_is_refused() -> None:
    with pytest.raises(ValueError, match="Expected cargo bench to report a benchmark"):
        bench.parse_medians("year: 252 trade dates\n")


@pytest.mark.parametrize("median", [129, 130])
def test_a_benchmark_up_to_thirty_percent_slower_than_its_baseline_does_not_warn(
    median: int,
) -> None:
    comparisons = bench.compare({BATCH: median}, {BATCH: 100})

    assert bench.regression_warnings(comparisons) == []


def test_a_benchmark_over_thirty_percent_slower_than_its_baseline_warns() -> None:
    comparisons = bench.compare({BATCH: 131}, {BATCH: 100})

    (warning,) = bench.regression_warnings(comparisons)
    assert warning.startswith(f"::warning title=Benchmark regression::{BATCH} ")
    assert "+31.0%25" in warning, "a workflow command writes % as %25"


def test_a_benchmark_without_a_baseline_is_listed_without_a_warning() -> None:
    comparisons = bench.compare(MEDIANS, {})

    assert bench.regression_warnings(comparisons) == []
    assert f"| {BATCH} | 1,850.0 ms | none |  |" in bench.render_table(comparisons)


def test_a_baseline_benchmark_that_did_not_run_is_refused() -> None:
    with pytest.raises(ValueError, match="Expected the benchmark single_run/gone in"):
        bench.compare(MEDIANS, {"single_run/gone": 1})


def test_the_table_gives_each_benchmark_its_change() -> None:
    comparisons = bench.compare(MEDIANS, {"single_run/with_paths": 400_000_000})

    table = bench.render_table(comparisons).splitlines()
    assert table[:2] == [
        "| Benchmark | Median | Baseline | Change |",
        "| --- | ---: | ---: | ---: |",
    ]
    assert "| single_run/with_paths | 412.3 ms | 400.0 ms | +3.1% |" in table


def test_the_next_baseline_holds_the_medians_and_where_they_came_from() -> None:
    run = "https://github.com/owner/fefat/actions/runs/1"

    assert bench.next_baseline(MEDIANS, date(2026, 11, 1), run) == {
        "recorded": "2026-11-01",
        "run": run,
        "ns_per_iter": MEDIANS,
    }


def test_a_regression_warns_in_the_job_summary_and_never_fails_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    baseline = tmp_path / "baseline.json"
    stored = {"recorded": "2026-11-01", "run": None, "ns_per_iter": {BATCH: 1_000_000_000}}
    baseline.write_text(json.dumps(stored), encoding="utf-8")
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(bench, "generated_year", lambda paths: tmp_path)
    monkeypatch.setattr(bench, "run_benches", lambda contract: CRITERION_OUTPUT)

    assert bench.main(["--baseline", str(baseline)]) == 0

    output = capsys.readouterr().out
    assert f"::warning title=Benchmark regression::{BATCH} " in output
    assert '"ns_per_iter"' in output
    assert f"| {BATCH} | 1,850.0 ms | 1,000.0 ms | +85.0% |" in summary.read_text(encoding="utf-8")


def test_the_generated_year_is_built_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bench, "LAST", date(2026, 1, 5))
    paths = resolve_paths(os.environ)

    contract = bench.generated_year(paths)
    (manifest,) = paths.cache_dir.glob(
        "synthetic-es-2026-01-02-2026-01-05/data/synthetic/MANIFEST.json"
    )
    written = manifest.stat().st_mtime_ns

    assert bench.generated_year(paths) == contract
    assert manifest.stat().st_mtime_ns == written
    assert contract.name == "ESH2026"
    assert (contract / "2026-01" / "index.json").is_file()


def test_a_month_the_cache_refuses_refuses_the_benchmarks(monkeypatch: pytest.MonkeyPatch) -> None:
    refused = EngineCacheBuild(
        provider="synthetic",
        root="ES",
        year=2026,
        months=(),
        removed=(),
        refused=("ESH2026 2026-01: a layout the engine does not read",),
    )
    monkeypatch.setattr(bench.gen_fixtures, "main", lambda arguments: 0)
    monkeypatch.setattr(bench, "build_engine_cache", lambda *arguments: refused)

    with pytest.raises(RuntimeError, match="Expected every month of the year cached, got: ESH2026"):
        bench.generated_year(resolve_paths(os.environ))


@pytest.mark.parametrize(
    "stored", [{"ns_per_iter": {BATCH: 0}}, {"ns_per_iter": {BATCH: "fast"}}, {"medians": {}}, []]
)
def test_a_baseline_without_positive_nanoseconds_is_refused(tmp_path: Path, stored: object) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(stored), encoding="utf-8")

    with pytest.raises(ValueError, match="Expected ns_per_iter to give positive nanoseconds"):
        bench.stored_baseline(baseline)


def test_benchmarks_that_measure_nothing_raise_a_github_warning(
    capsys: pytest.CaptureFixture[str],
) -> None:
    bench.announce_failure(ValueError("Expected cargo bench to report a benchmark, got:\nnone"))

    assert capsys.readouterr().out == (
        "::warning title=Benchmarks did not run::The benchmarks measured nothing: "
        "Expected cargo bench to report a benchmark, got:\n"
    )


def test_just_bench_runs_the_benchmarks() -> None:
    justfile = (ROOT / "justfile").read_text(encoding="utf-8")

    assert "bench *ARGS:\n    uv run python scripts/bench.py {{ARGS}}\n" in justfile


def test_ci_runs_the_benchmarks_on_engine_changes_and_never_blocks_a_merge() -> None:
    workflow_file = ROOT / ".github/workflows/benchmarks.yml"
    workflow = yaml.safe_load(workflow_file.read_text(encoding="utf-8"))
    triggers = workflow[True]  # PyYAML reads the key `on` as true, as YAML 1.1 does
    (job,) = workflow["jobs"].values()
    (benchmark,) = [step for step in job["steps"] if "just bench" in step.get("run", "")]

    assert job["runs-on"] == "ubuntu-latest"
    assert benchmark["run"] == f"just bench --baseline {bench.CI_BASELINE}"
    assert benchmark["continue-on-error"] is True
    assert benchmark["env"]["CRITERION_HOME"].startswith("${{ runner.temp }}"), (
        "not the cached target/"
    )
    for event in ("pull_request", "push"):
        assert {"engine/**", "scripts/bench.py"} <= set(triggers[event]["paths"]), event
    assert (
        "benchmarks"
        not in yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))[
            "jobs"
        ]
    )
    assert isinstance(bench.stored_baseline(ROOT / bench.CI_BASELINE), dict)
