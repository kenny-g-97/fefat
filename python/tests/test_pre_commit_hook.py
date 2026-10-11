import hashlib
import json
import shutil
from itertools import takewhile
from pathlib import Path

from git_repository import GitRepository

ROOT = Path(__file__).resolve().parents[2]
A_FIXTURE = (
    ROOT
    / "fixtures"
    / "synthetic"
    / "ohlcv-1m"
    / "root=ES"
    / "contract=ESH6"
    / "month=2026-03"
    / "part.parquet"
)


def repository_with_the_commit_guard(folder: Path) -> GitRepository:
    repository = GitRepository.initialized(folder)
    for relative in [".gitignore", ".githooks/pre-commit", "scripts/guard_data.py"]:
        (folder / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, folder / relative)
        repository.git("add", "--", relative)
    first = repository.commit("Add the commit guard")
    assert first.returncode == 0, first.stdout + first.stderr
    return repository


def test_the_commit_refuses_force_staged_market_data_and_accepts_listed_fixtures(
    tmp_path: Path,
) -> None:
    repository = repository_with_the_commit_guard(tmp_path)
    fixture = A_FIXTURE.read_bytes()

    repository.write("data/ES.parquet", fixture)
    assert repository.git("add", "data/ES.parquet").returncode != 0
    assert repository.git("add", "--force", "data/ES.parquet").returncode == 0
    refused = repository.commit("Add market data")

    assert refused.returncode != 0
    assert "data/ES.parquet" in refused.stdout + refused.stderr
    assert "only under fixtures/synthetic/" in refused.stdout + refused.stderr
    assert repository.git("rev-list", "--count", "HEAD").stdout.strip() == "1"

    assert repository.git("rm", "--cached", "--quiet", "data/ES.parquet").returncode == 0
    listing = {"files": [{"path": "x.parquet", "sha256": hashlib.sha256(fixture).hexdigest()}]}
    repository.stage("fixtures/synthetic/x.parquet", fixture)
    repository.stage("fixtures/synthetic/MANIFEST.json", json.dumps(listing).encode())
    accepted = repository.commit("Add a synthetic fixture")

    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    assert repository.git("rev-list", "--count", "HEAD").stdout.strip() == "2"


def test_just_setup_points_git_at_the_commit_gate() -> None:
    lines = (ROOT / "justfile").read_text(encoding="utf-8").splitlines()
    recipe = takewhile(lambda line: line.startswith("    "), lines[lines.index("setup:") + 1 :])

    assert "git config core.hooksPath .githooks" in [line.strip() for line in recipe]
