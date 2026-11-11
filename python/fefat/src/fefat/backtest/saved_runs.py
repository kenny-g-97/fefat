"""The saved runs (step 5.3, D-84): each folder of the runs' folder named by its run key that holds
`run.json`, which the app's index of runs and `fefat db import-workspace` read, the folders being
the record. The requests kept beside the runs (`fefat.backtest.requests`) and the folders a writer
is still writing, `<key>.<random>.partial` (`fefat.backtest.artifacts.write_run`), are passed over.

    ff.backtest.saved_runs_in(resolve_paths(os.environ).runs_dir)
"""

import re
from pathlib import Path

from fefat.backtest.artifacts import RECORD_FILE, OtherEngineRunError
from fefat.backtest.runs import Run

_RUN_KEY = re.compile(r"[0-9a-f]{64}")


def saved_run_folders(runs_dir: Path) -> tuple[Path, ...]:
    """The folders of `runs_dir` named by a run key, 64 hexadecimal digits, that hold
    `run.json`, in the order of their names; none where `runs_dir` is missing."""
    if not runs_dir.is_dir():
        return ()
    return tuple(
        folder
        for folder in sorted(runs_dir.iterdir())
        if _RUN_KEY.fullmatch(folder.name) and (folder / RECORD_FILE).is_file()
    )


def saved_runs_in(runs_dir: Path) -> tuple[Run, ...]:
    """Each run saved in `runs_dir` (`saved_run_folders`) by this engine, in the order of their
    keys (`saved_run`); a run another version of the engine or of the artifacts' layout saved is
    left out, as it cannot be read."""
    runs: list[Run] = []
    for folder in saved_run_folders(runs_dir):
        try:
            runs.append(saved_run(runs_dir, folder.name))
        except OtherEngineRunError:
            continue
    return tuple(runs)


def saved_run(runs_dir: Path, run_key: str) -> Run:
    """The run saved under `run_key` in `runs_dir`, refused unless the key is a run key, so that
    no text reaches outside the folder, and unless its folder's record is that run's, as one
    copied or renamed by hand is not, since a run's folder is named by its key."""
    if _RUN_KEY.fullmatch(run_key) is None:
        raise ValueError(f"Expected a run key, 64 hexadecimal digits, got {run_key!r}.")
    folder = runs_dir / run_key
    run = Run.open(folder)
    if run.hash != run_key:
        raise ValueError(
            f"Expected the run of key {run_key} in {folder}, got the record of run {run.hash}: "
            "a run's folder was copied or renamed by hand; move it back under its key, or "
            "delete the copy."
        )
    return run
