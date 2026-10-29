"""The backtest golden (step 2.10, Done means 2): a synthetic run's key and the hash of each of
its artifacts are those `fixtures/goldens/backtest/MANIFEST.json` records, which CI asserts on
Windows and on Linux, so that both systems give one run the same key and the same artifacts.
`just regenerate-goldens` writes the manifest, only with the builder's approval (the
`engine-golden` skill)."""

import json
from pathlib import Path

from golden_backtest import golden

MANIFEST = (
    Path(__file__).resolve().parents[2] / "fixtures" / "goldens" / "backtest" / "MANIFEST.json"
)


def test_a_synthetic_run_has_the_golden_key_and_artifacts_on_every_system() -> None:
    committed = json.loads(MANIFEST.read_text(encoding="utf-8"))

    produced = golden()

    assert produced["versions"] == committed["versions"]
    assert produced["inputs"] == committed["inputs"]
    assert produced["outputs"] == committed["outputs"]
