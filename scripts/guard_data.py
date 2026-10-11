"""Refuse commits that would put market data, secrets, oversized files, or notebook outputs into git.

The pre-commit hook (.githooks/pre-commit) runs it before every commit, and
`just check` runs it with the other checks:

    uv run --no-project python scripts/guard_data.py

It reads git's index, which holds exactly what the next commit will contain:
the tracked files plus everything staged, including files forced past
.gitignore with `git add -f`. Following the test-data policy
(docs/masterplan/05-build-process.md section 5, decision D-21), it refuses:

- market-data files (.parquet, .dbn, .zip, ...) anywhere outside fixtures/synthetic/,
  and files under any other name whose first bytes are a data format (Parquet,
  Arrow, DBN, zstd, gzip, zip, SQLite, HDF5, NumPy, pickle);
- data files under fixtures/synthetic/ that its MANIFEST.json does not list with
  their exact SHA-256, so a file dropped there cannot pass for a generated
  fixture (a hand-written manifest entry is caught by the regeneration test in
  `just test`, python/tests/test_gen_fixtures.py, not here);
- files over 25 MB;
- .env files (`.env*`, `*.env`), keys, and certificates, and API keys, tokens,
  passwords, or private keys inside text files (UTF-8, or UTF-16 with a byte-order mark);
- notebooks with cell outputs, which can hold licensed data.

Exits 0 when the index is clean, 1 with every problem listed, and 2 when git's
index cannot be read; a commit stops on anything but 0. Standard library only.
"""

from __future__ import annotations

import codecs
import hashlib
import io
import json
import re
import subprocess
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath

FIXTURES = "fixtures/synthetic/"
MANIFEST = FIXTURES + "MANIFEST.json"
MAX_FILE_BYTES = 25_000_000
BINARY_SNIFF_BYTES = 8000
SUBMODULE_MODE = "160000"
POLICY = "docs/masterplan/05-build-process.md section 5"
REGENERATE = "uv run python scripts/gen_fixtures.py"

MARKET_DATA_SUFFIXES = (
    ".dbn.zst",
    ".csv.gz",
    ".duckdb.wal",
    ".dbn",
    ".zst",
    ".parquet",
    ".arrow",
    ".feather",
    ".ipc",
    ".zip",
    ".h5",
    ".hdf5",
    ".duckdb",
    ".sqlite",
    ".sqlite3",
    ".db",
)
DATA_SIGNATURES = (
    (b"PAR1", "Parquet"),
    (b"ARROW1", "Arrow"),
    *((b"DBN" + bytes([version]), "DBN") for version in (1, 2, 3)),
    (b"\x28\xb5\x2f\xfd", "zstd"),
    (b"\x1f\x8b", "gzip"),
    (b"PK\x03\x04", "zip"),
    (b"SQLite format 3\x00", "SQLite"),
    (b"\x89HDF\r\n\x1a\n", "HDF5"),
    (b"\x93NUMPY", "NumPy"),
    *((bytes([0x80, protocol]), "pickle") for protocol in (2, 3, 4, 5)),
)
KEY_SUFFIXES = (".pem", ".key", ".pfx", ".p12")
SSH_PRIVATE_KEY = re.compile(r"^id_(rsa|dsa|ecdsa|ed25519)(_sk)?$")
ENV_FILE = ".env"
ENV_EXAMPLE = ".env.example"
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
QUOTE = r"\\?['\"]"
VALUE_CHARACTER = r"[A-Za-z0-9/+_.=-]"
QUOTED_CHARACTER = r"[^\s'\"\\]"
UNQUOTED_VALUE = (
    rf"(?!{VALUE_CHARACTER}*\.\.\.)(?={VALUE_CHARACTER}*[0-9])(?={VALUE_CHARACTER}*[A-Za-z])"
    rf"{VALUE_CHARACTER}{{16,}}"
)
QUOTED_VALUE = (
    rf"{QUOTE}(?!{QUOTED_CHARACTER}*\.\.\.)(?={QUOTED_CHARACTER}*[0-9])"
    rf"(?={QUOTED_CHARACTER}*[A-Za-z]){QUOTED_CHARACTER}{{16,}}{QUOTE}"
)
SECRET_NAME = r"(?:API_?KEY|(?:SECRET|PRIVATE|ACCESS)_?KEY|SECRET|TOKEN|PASSWORD)"
ASSIGNMENT = rf"{QUOTE}?\]?(?:[ \t]*:[ \t]*[A-Za-z_][\w.\[\], |]*?)?[ \t]*[=:][ \t]*"
PLAIN_TEXT_SECRET = "a key, token, or password written in plain text"


@dataclass(frozen=True)
class SecretPattern:
    kind: str
    pattern: re.Pattern[str]


SECRET_PATTERNS = (
    SecretPattern("an Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    SecretPattern("a Databento API key", re.compile(r"\bdb-[A-Za-z0-9]{24,}\b")),
    SecretPattern(
        "a GitHub token",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})"),
    ),
    SecretPattern("an AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    SecretPattern("a private key", re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----")),
    SecretPattern(
        PLAIN_TEXT_SECRET,
        re.compile(
            rf"(?<![A-Za-z0-9_])[A-Z0-9_]*{SECRET_NAME}{ASSIGNMENT}(?:{QUOTED_VALUE}|{UNQUOTED_VALUE})"
        ),
    ),
    SecretPattern(
        PLAIN_TEXT_SECRET,
        re.compile(rf"(?i)(?<![a-z0-9_])[a-z0-9_]*{SECRET_NAME}{ASSIGNMENT}{QUOTED_VALUE}"),
    ),
    SecretPattern(
        PLAIN_TEXT_SECRET,
        re.compile(rf"(?im)^[ \t]*[a-z0-9_]*{SECRET_NAME}[ \t]*:[ \t]*{UNQUOTED_VALUE}[ \t\r]*$"),
    ),
)


class Rule(StrEnum):
    MARKET_DATA_OUTSIDE_FIXTURES = "market data outside fixtures/synthetic/"
    FIXTURE_NOT_IN_MANIFEST = "fixture missing from MANIFEST.json"
    FIXTURE_HASH_MISMATCH = "fixture differs from its MANIFEST.json hash"
    MANIFEST_ENTRY_NOT_IN_GIT = "MANIFEST.json lists a file that is not in git"
    MANIFEST_UNREADABLE = "MANIFEST.json unreadable"
    FILE_TOO_LARGE = "file over 25 MB"
    SECRET_FILE = "secret file"
    SECRET_IN_TEXT = "secret in the text"
    NOTEBOOK_WITH_OUTPUTS = "notebook with outputs"
    NOTEBOOK_UNREADABLE = "notebook unreadable"


@dataclass(frozen=True)
class Problem:
    path: str
    rule: Rule
    explanation: str

    def describe(self) -> str:
        return f"{self.path}\n    {self.rule}: {self.explanation}"


@dataclass(frozen=True)
class IndexedFile:
    """One entry of git's index: its path (with forward slashes), object id, and mode."""

    path: str
    object_id: str
    mode: str

    def name(self) -> str:
        return PurePosixPath(self.path).name.lower()

    def is_submodule(self) -> bool:
        return self.mode == SUBMODULE_MODE

    def is_fixture(self) -> bool:
        return self.path.startswith(FIXTURES)

    def market_data_suffix(self) -> str | None:
        return next(
            (suffix for suffix in MARKET_DATA_SUFFIXES if self.name().endswith(suffix)), None
        )

    def is_secret_file(self) -> bool:
        name = self.name()
        if name == ENV_EXAMPLE:
            return False
        is_env_file = name.startswith(ENV_FILE) or name.endswith(ENV_FILE)
        return is_env_file or name.endswith(KEY_SUFFIXES) or SSH_PRIVATE_KEY.match(name) is not None


class GitError(Exception):
    pass


class ManifestError(Exception):
    pass


def git_output(repository: Path, arguments: Sequence[str], stdin: bytes = b"") -> bytes:
    completed = subprocess.run(
        ["git", *arguments], cwd=repository, input=stdin, capture_output=True, check=False
    )
    if completed.returncode != 0:
        stderr = completed.stderr.decode(errors="replace").strip()
        raise GitError(
            f"Expected `git {' '.join(arguments)}` to succeed in {repository}, "
            f"got exit code {completed.returncode}: {stderr}"
        )
    return completed.stdout


def indexed_files(repository: Path) -> list[IndexedFile]:
    records = git_output(repository, ["ls-files", "-z", "--stage"]).split(b"\0")
    return [parsed_index_record(record) for record in records if record]


def parsed_index_record(record: bytes) -> IndexedFile:
    metadata, path = record.split(b"\t", 1)
    mode, object_id, _stage = metadata.decode("ascii").split(" ")
    return IndexedFile(path.decode("utf-8", errors="replace"), object_id, mode)


def object_sizes(repository: Path, object_ids: Sequence[str]) -> dict[str, int]:
    request = "".join(f"{object_id}\n" for object_id in object_ids).encode()
    lines = git_output(
        repository, ["cat-file", "--batch-check=%(objectname) %(objectsize)"], request
    )
    sizes: dict[str, int] = {}
    for line in lines.decode("ascii").splitlines():
        object_id, size = line.split(" ")
        if not size.isdigit():
            raise GitError(f"Expected the size of object {object_id} in git's index, got '{size}'.")
        sizes[object_id] = int(size)
    return sizes


def object_contents(repository: Path, object_ids: Sequence[str]) -> dict[str, bytes]:
    request = "".join(f"{object_id}\n" for object_id in object_ids).encode()
    output = git_output(repository, ["cat-file", "--batch"], request)
    contents: dict[str, bytes] = {}
    position = 0
    while position < len(output):
        header_end = output.index(b"\n", position)
        header = output[position:header_end].decode("ascii").split(" ")
        if len(header) != 3:
            raise GitError(f"Expected '<id> <type> <size>' from git cat-file, got {header}.")
        start = header_end + 1
        contents[header[0]] = output[start : start + int(header[2])]
        position = start + int(header[2]) + 1
    return contents


def market_data_outside_fixtures(file: IndexedFile, found: str) -> Problem:
    return Problem(
        file.path,
        Rule.MARKET_DATA_OUTSIDE_FIXTURES,
        f"expected market-data files only under {FIXTURES}, got {found} outside it. "
        "Licensed data stays outside the repository under FEFAT_DATA_DIR and is referenced by "
        f'path. Take it out of the commit (your copy stays on disk): git rm --cached "{file.path}"',
    )


def path_problems(file: IndexedFile) -> Iterator[Problem]:
    suffix = file.market_data_suffix()
    if suffix is not None and not file.is_fixture():
        yield market_data_outside_fixtures(file, f"this {suffix} file")
    if file.is_secret_file():
        yield Problem(
            file.path,
            Rule.SECRET_FILE,
            "expected no .env files, keys, or certificates in git, got this one. Keys live in the "
            "operating system's credential store. Take it out of the commit (your copy stays on "
            f'disk): git rm --cached "{file.path}"',
        )


def notebook_problems(file: IndexedFile, content: bytes) -> Iterator[Problem]:
    try:
        notebook = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        yield Problem(
            file.path, Rule.NOTEBOOK_UNREADABLE, f"expected a notebook in JSON, got {error}."
        )
        return
    cells = notebook.get("cells") if isinstance(notebook, dict) else None
    if not isinstance(cells, list):
        yield Problem(
            file.path,
            Rule.NOTEBOOK_UNREADABLE,
            f"expected a notebook with a list of cells, got {type(cells).__name__}.",
        )
        return
    with_outputs = [cell for cell in cells if isinstance(cell, dict) and cell.get("outputs")]
    if with_outputs:
        yield Problem(
            file.path,
            Rule.NOTEBOOK_WITH_OUTPUTS,
            f"expected no cell outputs (they can hold licensed data), got outputs in "
            f"{len(with_outputs)} of {len(cells)} cells. Clear them with `just strip-notebooks`, "
            f'then stage the notebook again: git add "{file.path}"',
        )


def secret_kinds(text: str) -> list[str]:
    found = [secret.kind for secret in SECRET_PATTERNS if secret.pattern.search(text)]
    return list(dict.fromkeys(found))


def readable_text(content: bytes) -> str | None:
    """The text of a file, or None when it is binary; UTF-16 text is read through its byte-order mark."""
    if content.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return content.decode("utf-16", errors="replace")
    if b"\0" in content[:BINARY_SNIFF_BYTES]:
        return None
    return content.decode("utf-8", errors="replace")


def data_format(content: bytes) -> str | None:
    return next(
        (name for signature, name in DATA_SIGNATURES if content.startswith(signature)), None
    )


def content_problems(file: IndexedFile, content: bytes) -> Iterator[Problem]:
    found_format = data_format(content)
    if found_format is not None and not file.is_fixture() and file.market_data_suffix() is None:
        yield market_data_outside_fixtures(file, f"{found_format} data under another name")
    if file.name().endswith(".ipynb"):
        yield from notebook_problems(file, content)
    text = readable_text(content)
    if text is None:
        return
    kinds = secret_kinds(text)
    if kinds:
        yield Problem(
            file.path,
            Rule.SECRET_IN_TEXT,
            f"expected no keys or tokens in files, got {' and '.join(kinds)}. Keys live in the "
            "operating system's credential store and are read at run time; revoke this one if it "
            "was ever real.",
        )


def listed_hashes(content: bytes) -> dict[str, str]:
    """Parse MANIFEST.json into {path under fixtures/synthetic/: sha256}."""
    try:
        manifest = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ManifestError(f"expected JSON, got {error}.") from error
    entries = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(entries, list):
        raise ManifestError(
            f'expected {{"files": [...]}}, got {type(entries).__name__} under "files".'
        )
    listing: dict[str, str] = {}
    for entry in entries:
        path = entry.get("path") if isinstance(entry, dict) else None
        sha256 = entry.get("sha256") if isinstance(entry, dict) else None
        if not isinstance(path, str) or not isinstance(sha256, str) or not SHA256_HEX.match(sha256):
            raise ManifestError(
                f"expected each entry to carry a path and a lowercase SHA-256, got {entry!r}."
            )
        listing[path] = sha256
    return listing


def fixture_problem(
    file: IndexedFile, listing: dict[str, str], contents: dict[str, bytes]
) -> Problem | None:
    listed = listing.get(file.path.removeprefix(FIXTURES))
    if listed is None:
        return Problem(
            file.path,
            Rule.FIXTURE_NOT_IN_MANIFEST,
            f"expected every data file under {FIXTURES} listed in {MANIFEST} with its SHA-256, got no "
            f"entry for this one. Fixtures come from the generator, which writes the manifest: {REGENERATE}",
        )
    if file.object_id not in contents:
        return None
    actual = hashlib.sha256(contents[file.object_id]).hexdigest()
    if actual == listed:
        return None
    return Problem(
        file.path,
        Rule.FIXTURE_HASH_MISMATCH,
        f"expected SHA-256 {listed} from {MANIFEST}, got {actual}. Only files the generator wrote may "
        f"live here: {REGENERATE}, then stage the result.",
    )


def manifest_problems(files: Sequence[IndexedFile], contents: dict[str, bytes]) -> list[Problem]:
    data_files = [
        file
        for file in files
        if file.is_fixture()
        and (
            file.market_data_suffix() is not None
            or data_format(contents.get(file.object_id, b"")) is not None
        )
    ]
    manifest = next((file for file in files if file.path == MANIFEST), None)
    if manifest is None or manifest.object_id not in contents:
        missing = "no manifest in git" if manifest is None else "a manifest over the size limit"
        return [
            Problem(
                file.path,
                Rule.FIXTURE_NOT_IN_MANIFEST,
                f"expected it listed in {MANIFEST}, got {missing}. Regenerate the fixtures: {REGENERATE}",
            )
            for file in data_files
        ]
    try:
        listing = listed_hashes(contents[manifest.object_id])
    except ManifestError as error:
        return [Problem(MANIFEST, Rule.MANIFEST_UNREADABLE, str(error))]
    problems = [fixture_problem(file, listing, contents) for file in data_files]
    in_git = {file.path.removeprefix(FIXTURES) for file in files if file.is_fixture()}
    unstaged = [
        Problem(
            FIXTURES + listed_path,
            Rule.MANIFEST_ENTRY_NOT_IN_GIT,
            f"expected each file {MANIFEST} lists to be in git, got no such file in the index. Stage it "
            f'(git add "{FIXTURES + listed_path}") or regenerate: {REGENERATE}',
        )
        for listed_path in sorted(set(listing) - in_git)
    ]
    return [problem for problem in problems if problem is not None] + unstaged


def find_problems(repository: Path, max_file_bytes: int = MAX_FILE_BYTES) -> list[Problem]:
    """Every way the files in the repository's index break the data policy, sorted by path."""
    files = [file for file in indexed_files(repository) if not file.is_submodule()]
    object_ids = sorted({file.object_id for file in files})
    sizes = object_sizes(repository, object_ids)
    readable_ids = [object_id for object_id in object_ids if sizes[object_id] <= max_file_bytes]
    contents = object_contents(repository, readable_ids)
    problems = [problem for file in files for problem in path_problems(file)]
    problems += [
        Problem(
            file.path,
            Rule.FILE_TOO_LARGE,
            f"expected at most {max_file_bytes:,} bytes per file, got {sizes[file.object_id]:,}. "
            "Large files stay outside the repository.",
        )
        for file in files
        if sizes[file.object_id] > max_file_bytes
    ]
    problems += [
        problem
        for file in files
        if file.object_id in contents
        for problem in content_problems(file, contents[file.object_id])
    ]
    problems += manifest_problems(files, contents)
    return sorted(problems, key=lambda problem: (problem.path, problem.rule))


def report(problems: Sequence[Problem]) -> str:
    count = f"{len(problems)} problem" + ("" if len(problems) == 1 else "s")
    listed = "\n\n".join(problem.describe() for problem in problems)
    return (
        f"Data guard: {count} in git's index (what the next commit would contain).\n\n"
        f"{listed}\n\nThe data policy: {POLICY}."
    )


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="replace")
    try:
        repository = Path(git_output(Path.cwd(), ["rev-parse", "--show-toplevel"]).decode().strip())
        problems = find_problems(repository)
    except GitError as error:
        print(f"Data guard: could not read git's index. {error}", file=sys.stderr)
        return 2
    if problems:
        print(report(problems))
        return 1
    print(
        "Data guard: git's index holds no market data outside fixtures/synthetic/, "
        "no secrets, no files over 25 MB, and no notebook outputs."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
