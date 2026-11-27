"""The `explain` job's work outside the pool (step 5.9): a replay that crashes, for a reason the
engine does not give, fails its job in words that name no folder of this PC, as a refusal's do
(D-80); the pool's own runs of the job are in `test_http_trade_review.py`."""

import os
from datetime import timedelta
from typing import NoReturn

import pytest

from fefat.backtest.runs import Run
from fefat.config import resolve_paths
from fefat_app.database.job_records import JobTables
from fefat_app.job_models import JobKind
from fefat_app.jobs import trade_explanations
from fefat_app.jobs.progress import JobProgress
from fefat_app.jobs.trade_explanations import ReplayCrashedError, run_explanation
from local_server import STARTED_AT

WORKER = 4242
RUN_KEY = "ab" * 32


def test_a_replay_that_crashes_fails_in_words_that_name_no_folder_of_this_pc(
    job_records: JobTables, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Step 5.9's code review: the worker keeps a crash's words as the job's error, which the
    # trade review shows, and a crash reading a run's file names the file's folder.
    paths = resolve_paths(os.environ)
    signals = paths.runs_dir / RUN_KEY / "signals.parquet"
    store = paths.data_dir / "synthetic" / "trades"

    def crashed(_run: Run, _trade_id: int) -> NoReturn:
        raise RuntimeError(f"Could not read {signals} beside {store} under {paths.home}.")

    monkeypatch.setattr(trade_explanations, "saved_run", lambda *_folders: None)
    monkeypatch.setattr(trade_explanations, "explain", crashed)
    payload = {"run_key": RUN_KEY, "trade_id": 7}
    queued = job_records.add(JobKind.EXPLAIN, payload, 3, STARTED_AT)
    held = job_records.start(queued.id, WORKER, STARTED_AT + timedelta(hours=1), STARTED_AT)
    assert held is not None

    with pytest.raises(ReplayCrashedError) as raised:
        run_explanation(paths, payload, JobProgress(job_records, held.id, WORKER))

    words = str(raised.value)
    assert words.startswith("RuntimeError: Could not read run abababababab")
    assert "your data folder" in words
    assert str(paths.home) not in words
