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
    keys; a run another version of the engine or of the artifacts' layout saved is left out, as
    it cannot be read, and a record whose key is not its folder's name is refused, as one copied
    or renamed by hand is, since a run's folder is named by its key."""
    runs: list[Run] = []
    for folder in saved_run_folders(runs_dir):
        try:
            run = Run.open(folder)
        except OtherEngineRunError:
            continue
        if run.hash != folder.name:
            raise ValueError(
                f"Expected the run of key {folder.name} in {folder}, got the record of run "
                f"{run.hash}: a run's folder was copied or renamed by hand; move it back under "
                "its key, or delete the copy."
            )
        runs.append(run)
    return tuple(runs)
