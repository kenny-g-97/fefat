"""A throwaway git repository for the tests of the data guard and the pre-commit hook."""

from __future__ import annotations

import subprocess
from pathlib import Path

TEST_IDENTITY = ("-c", "user.name=FEFAT tests", "-c", "user.email=tests@fefat.invalid")


class GitRepository:
    def __init__(self, folder: Path) -> None:
        self.folder = folder

    @classmethod
    def initialized(cls, folder: Path) -> GitRepository:
        repository = cls(folder)
        created = repository.git("init", "--quiet", "--initial-branch=main")
        if created.returncode != 0:
            raise RuntimeError(f"Expected git init to succeed in {folder}, got: {created.stderr}")
        return repository

    def git(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *arguments], cwd=self.folder, capture_output=True, text=True, check=False
        )

    def write(self, relative: str, content: bytes) -> None:
        path = self.folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def stage(self, relative: str, content: bytes) -> None:
        self.write(relative, content)
        added = self.git("add", "--force", "--", relative)
        if added.returncode != 0:
            raise RuntimeError(f"Expected git add to stage {relative}, got: {added.stderr}")

    def commit(self, message: str) -> subprocess.CompletedProcess[str]:
        return self.git(
            *TEST_IDENTITY,
            "-c",
            "core.hooksPath=.githooks",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "--quiet",
            "--message",
            message,
        )
