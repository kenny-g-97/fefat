"""Clear the outputs of every notebook in the repository, because outputs can hold licensed data.

Run it in the project environment, since it drives nbstripout (a development tool):

    just strip-notebooks
    uv run python scripts/strip_notebooks.py

It strips the notebooks git knows about: tracked ones, and untracked ones that
.gitignore does not exclude (so `.ipynb_checkpoints/` copies stay as they are).
A commit takes the staged copy, so stage each stripped notebook again with
`git add` before committing; the data guard (scripts/guard_data.py) refuses
staged notebooks with outputs (docs/masterplan/05-build-process.md section 5).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


class StripError(Exception):
    pass


def git_output(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments], cwd=repository, capture_output=True, encoding="utf-8", check=False
    )
    if completed.returncode != 0:
        raise StripError(
            f"Expected `git {' '.join(arguments)}` to succeed in {repository}, "
            f"got exit code {completed.returncode}: {completed.stderr.strip()}"
        )
    return completed.stdout


def notebooks(repository: Path) -> list[Path]:
    """The notebooks on disk that git tracks or would track, relative to the repository."""
    listed = git_output(
        repository, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "*.ipynb"
    )
    paths = {Path(entry) for entry in listed.split("\0") if entry}
    return sorted(path for path in paths if (repository / path).is_file())


def strip(repository: Path) -> list[Path]:
    """Clear the outputs of the repository's notebooks in place and return their paths."""
    paths = notebooks(repository)
    if not paths:
        return []
    command = [sys.executable, "-m", "nbstripout", "--", *(str(path) for path in paths)]
    completed = subprocess.run(
        command,
        cwd=repository,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise StripError(
            f"Expected nbstripout to clear {len(paths)} notebooks, got exit code "
            f"{completed.returncode}: {completed.stderr.strip()} {completed.stdout.strip()}"
        )
    kept = [path.as_posix() for path in paths if has_outputs(repository / path)]
    if kept:
        raise StripError(
            f"Expected no outputs after nbstripout, got outputs still in {', '.join(kept)}. "
            "nbstripout keeps cells marked `keep_output` (in the cell's metadata or tags), and the "
            "commit guard refuses any output: remove that mark, then run `just strip-notebooks` again."
        )
    return paths


def has_outputs(notebook: Path) -> bool:
    cells = json.loads(notebook.read_text(encoding="utf-8"))["cells"]
    return any(cell.get("outputs") for cell in cells)


def main() -> int:
    try:
        repository = Path(git_output(Path.cwd(), "rev-parse", "--show-toplevel").strip())
        stripped = strip(repository)
    except StripError as error:
        print(f"strip-notebooks: {error}", file=sys.stderr)
        return 1
    if not stripped:
        print("No notebooks to strip.")
        return 0
    listed = "\n".join(f"  {path.as_posix()}" for path in stripped)
    print(f"Cleared the outputs of {len(stripped)} notebooks:\n{listed}")
    print("Stage them again with `git add` before committing: a commit takes the staged copy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
