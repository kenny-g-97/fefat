import json
from itertools import takewhile
from pathlib import Path

import pytest

import guard_data
import strip_notebooks
from git_repository import GitRepository

ROOT = Path(__file__).resolve().parents[2]
STRIP_COMMAND = "uv run python scripts/strip_notebooks.py"
NOTEBOOK_WITH_OUTPUTS = {
    "cells": [
        {
            "cell_type": "code",
            "execution_count": 1,
            "metadata": {},
            "outputs": [{"name": "stdout", "output_type": "stream", "text": ["6850.25\n"]}],
            "source": ["print(close)"],
        }
    ],
    "metadata": {},
    "nbformat": 4,
    "nbformat_minor": 5,
}


def notebook_bytes() -> bytes:
    return json.dumps(NOTEBOOK_WITH_OUTPUTS).encode()


def test_a_staged_notebook_with_outputs_passes_after_strip_notebooks_and_git_add(
    tmp_path: Path,
) -> None:
    repository = GitRepository.initialized(tmp_path)
    repository.stage("notebooks/demo.ipynb", notebook_bytes())
    refused = guard_data.find_problems(tmp_path)

    stripped = strip_notebooks.strip(tmp_path)
    repository.git("add", "notebooks/demo.ipynb")

    assert [problem.rule for problem in refused] == [guard_data.Rule.NOTEBOOK_WITH_OUTPUTS]
    assert stripped == [Path("notebooks/demo.ipynb")]
    assert guard_data.find_problems(tmp_path) == []
    cell = json.loads((tmp_path / "notebooks" / "demo.ipynb").read_text(encoding="utf-8"))["cells"][
        0
    ]
    assert cell["outputs"] == []
    assert cell["source"] == ["print(close)"]


def test_untracked_notebooks_are_stripped_and_ignored_ones_are_left_alone(tmp_path: Path) -> None:
    repository = GitRepository.initialized(tmp_path)
    repository.write(".gitignore", b".ipynb_checkpoints/\n")
    repository.write("notebooks/draft.ipynb", notebook_bytes())
    repository.write("notebooks/.ipynb_checkpoints/draft-checkpoint.ipynb", notebook_bytes())

    stripped = strip_notebooks.strip(tmp_path)

    assert stripped == [Path("notebooks/draft.ipynb")]
    checkpoint = tmp_path / "notebooks" / ".ipynb_checkpoints" / "draft-checkpoint.ipynb"
    assert checkpoint.read_bytes() == notebook_bytes()


def test_a_notebook_with_a_non_ascii_name_is_stripped(tmp_path: Path) -> None:
    repository = GitRepository.initialized(tmp_path)
    repository.stage("notebooks/análisis.ipynb", notebook_bytes())

    stripped = strip_notebooks.strip(tmp_path)

    assert stripped == [Path("notebooks/análisis.ipynb")]
    assert not strip_notebooks.has_outputs(tmp_path / "notebooks" / "análisis.ipynb")


def test_outputs_that_nbstripout_keeps_on_purpose_are_reported(tmp_path: Path) -> None:
    repository = GitRepository.initialized(tmp_path)
    cell = {**NOTEBOOK_WITH_OUTPUTS["cells"][0], "metadata": {"keep_output": True}}
    kept = json.dumps({**NOTEBOOK_WITH_OUTPUTS, "cells": [cell]}).encode()
    repository.write("notebooks/kept.ipynb", kept)

    with pytest.raises(strip_notebooks.StripError, match="keep_output"):
        strip_notebooks.strip(tmp_path)


def test_a_notebook_marked_keep_output_as_a_whole_is_reported_by_where_the_mark_is(
    tmp_path: Path,
) -> None:
    repository = GitRepository.initialized(tmp_path)
    kept = {**NOTEBOOK_WITH_OUTPUTS, "metadata": {"keep_output": True}}
    repository.write("notebooks/kept.ipynb", json.dumps(kept).encode())

    with pytest.raises(strip_notebooks.StripError, match="notebook's own metadata"):
        strip_notebooks.strip(tmp_path)


def test_init_cells_are_stripped_too(tmp_path: Path) -> None:
    repository = GitRepository.initialized(tmp_path)
    cell = {**NOTEBOOK_WITH_OUTPUTS["cells"][0], "metadata": {"init_cell": True}}
    repository.write(
        "notebooks/init.ipynb", json.dumps({**NOTEBOOK_WITH_OUTPUTS, "cells": [cell]}).encode()
    )

    assert strip_notebooks.strip(tmp_path) == [Path("notebooks/init.ipynb")]
    assert not strip_notebooks.has_outputs(tmp_path / "notebooks" / "init.ipynb")


def test_a_notebook_whose_name_starts_with_a_dash_is_stripped(tmp_path: Path) -> None:
    repository = GitRepository.initialized(tmp_path)
    repository.write("-draft.ipynb", notebook_bytes())

    assert strip_notebooks.strip(tmp_path) == [Path("-draft.ipynb")]
    assert not strip_notebooks.has_outputs(tmp_path / "-draft.ipynb")


def test_an_nbformat_3_notebook_stops_with_a_message_instead_of_a_crash(tmp_path: Path) -> None:
    repository = GitRepository.initialized(tmp_path)
    old_cell = {
        "cell_type": "code",
        "input": ["print(close)"],
        "language": "python",
        "metadata": {},
        "outputs": [{"output_type": "stream", "stream": "stdout", "text": ["6850.25\n"]}],
        "prompt_number": 1,
    }
    old_notebook = {
        "metadata": {},
        "nbformat": 3,
        "nbformat_minor": 0,
        "worksheets": [{"cells": [old_cell], "metadata": {}}],
    }
    repository.write("notebooks/old.ipynb", json.dumps(old_notebook).encode())

    with pytest.raises(strip_notebooks.StripError, match="nbformat 4"):
        strip_notebooks.strip(tmp_path)


def test_a_repository_without_notebooks_strips_nothing(tmp_path: Path) -> None:
    GitRepository.initialized(tmp_path)

    assert strip_notebooks.strip(tmp_path) == []


def test_just_strip_notebooks_runs_the_strip_script() -> None:
    lines = (ROOT / "justfile").read_text(encoding="utf-8").splitlines()
    recipe = takewhile(
        lambda line: line.startswith("    "), lines[lines.index("strip-notebooks:") + 1 :]
    )

    assert [line.strip() for line in recipe] == [STRIP_COMMAND]
