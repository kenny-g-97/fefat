"""The backtest golden (step 2.10, `02` §5 and §8): a run of `ff.backtest` on the synthetic
fixtures, its run key and the hash of each artifact as written and read back, which CI asserts on
Windows and on Linux (`python/tests/test_backtest_golden.py`).

The run copies the fixtures' ES trades, 1-second, and 1-minute bars into a temporary
`FEFAT_HOME` and backtests a breakout from 2026-03-05 to 2026-03-09, across the fixtures' roll of
2026-03-09, at the default settings: a long on a 5-minute close above the highest of the 12 closes
before it, a stop of 12 ticks and a target of 24. Its features are integers, so that the signal
frame, which keys the run, is the same on every system (`02` §4).

    uv run python scripts/golden_backtest.py                     # print the golden
    uv run python scripts/golden_backtest.py --write <manifest>  # write it, as just regenerate-goldens does
"""

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import warnings
from pathlib import Path
from typing import Any

REPOSITORY = Path(__file__).resolve().parents[1]
FIXTURES = REPOSITORY / "fixtures" / "synthetic"
SCHEMAS = ("trades", "ohlcv-1s", "ohlcv-1m")
START, END = "2026-03-05", "2026-03-09"
COMMAND = "uv run python scripts/golden_backtest.py --write fixtures/goldens/backtest/MANIFEST.json"


def golden() -> dict[str, Any]:
    """The golden manifest of the run: the command, the engine's versions, the inputs, and the
    outputs, the run key and each artifact's table hash."""
    with tempfile.TemporaryDirectory(prefix="fefat-golden-backtest-") as folder:
        home = Path(folder)
        for schema in SCHEMAS:
            shutil.copytree(FIXTURES / schema, home / "data" / "synthetic" / schema)
        environment = {"FEFAT_HOME": str(home), "FEFAT_DATA_DIR": str(home / "data")}
        previous = {name: os.environ.get(name) for name in environment}
        os.environ.update(environment)
        try:
            return _golden_of_the_run()
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name)
                else:
                    os.environ[name] = value


def _golden_of_the_run() -> dict[str, Any]:
    import fefat_engine
    import polars as pl

    import fefat as ff
    from fefat.backtest import ARTIFACT_SCHEMAS

    strategy = ff.SignalStrategy(
        instrument="ES",
        timeframe="5m",
        features={"highest": pl.col("close").rolling_max(12).shift(1)},
        long_entry=pl.col("close") > pl.col("highest"),
        short_entry=pl.lit(False),
        execution=ff.Execution(
            entry=ff.Market(),
            stop=ff.Stop(ticks=12),
            targets=[ff.Target(ticks=24)],
            sizing=ff.Fixed(1),
        ),
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        run = ff.backtest.run(strategy, START, END)
    artifacts = {
        name: fefat_engine.table_hash(pl.read_parquet(run.folder / f"{name}.parquet"))
        for name in ARTIFACT_SCHEMAS
    }
    fixtures = hashlib.sha256((FIXTURES / "MANIFEST.json").read_bytes()).hexdigest()
    return {
        "command": COMMAND,
        "versions": run.record.versions.model_dump(),
        "inputs": {
            "strategy": run.record.strategy.spec,
            "features": {"highest": "the highest of the 12 closes before the bar"},
            "window": {"start": START, "end": END},
            "fixtures_manifest_sha256": fixtures,
        },
        "outputs": {"run_key": run.hash, "artifacts": artifacts},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Print or write the backtest golden.")
    parser.add_argument("--write", type=Path, help="the manifest to write the golden to")
    arguments = parser.parse_args()
    text = json.dumps(golden(), indent=2) + "\n"
    if arguments.write is None:
        print(text, end="")
        return 0
    arguments.write.parent.mkdir(parents=True, exist_ok=True)
    arguments.write.write_bytes(text.encode())
    print(f"Wrote the backtest golden to {arguments.write}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
