import shutil
import subprocess
from pathlib import Path

from git_repository import GitRepository

ROOT = Path(__file__).resolve().parents[2]
BARS = b"time,close\n1772751600,5432.25\n"


def clone_with_the_push_guard(folder: Path) -> GitRepository:
    """A repository whose `origin` is a bare repository beside it, with the pre-push hook and
    the data guard committed and `main` pushed; the pre-commit hook is left out, so that a test
    can commit what the push must refuse."""
    remote = folder / "remote.git"
    created = subprocess.run(
        ["git", "init", "--bare", "--quiet", str(remote)], capture_output=True, check=False
    )
    assert created.returncode == 0, created.stderr
    (folder / "clone").mkdir()
    repository = GitRepository.initialized(folder / "clone")
    for relative in [".gitignore", ".githooks/pre-push", "scripts/guard_data.py"]:
        (repository.folder / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, repository.folder / relative)
        repository.git("add", "--", relative)
    committed(repository, "Add the push guard")
    assert repository.git("remote", "add", "origin", str(remote)).returncode == 0
    first = pushed(repository, "main")
    assert first.returncode == 0, first.stdout + first.stderr
    return repository


def committed(repository: GitRepository, message: str) -> str:
    done = repository.commit(message)
    assert done.returncode == 0, done.stdout + done.stderr
    return repository.git("rev-parse", "HEAD").stdout.strip()


def pushed(repository: GitRepository, branch: str) -> subprocess.CompletedProcess[str]:
    return repository.git(
        "-c", "core.hooksPath=.githooks", "push", "--quiet", "origin", f"HEAD:refs/heads/{branch}"
    )


def test_a_push_is_refused_while_a_commit_of_the_branch_holds_market_data(
    tmp_path: Path,
) -> None:
    repository = clone_with_the_push_guard(tmp_path)
    clean = repository.git("rev-parse", "HEAD").stdout.strip()
    repository.stage("data/bars.csv", BARS)
    committed(repository, "Add the bars")

    refused = pushed(repository, "notes")

    assert refused.returncode != 0
    assert "data/bars.csv" in refused.stdout + refused.stderr
    assert repository.git("rm", "--quiet", "data/bars.csv").returncode == 0
    committed(repository, "Remove the bars")
    assert pushed(repository, "notes").returncode != 0

    assert repository.git("reset", "--hard", "--quiet", clean).returncode == 0
    repository.stage("notes.md", b"# Notes\n")
    committed(repository, "Add the notes")
    accepted = pushed(repository, "notes")

    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    remote_branch = repository.git("ls-remote", "--heads", "origin", "notes").stdout
    assert remote_branch.startswith(repository.git("rev-parse", "HEAD").stdout.strip())
