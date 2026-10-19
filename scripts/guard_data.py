"""Refuse commits and pushes that would put market data, secrets, oversized files, or notebook
outputs into git.

The pre-commit hook (.githooks/pre-commit) runs it before every commit, and
`just check` runs it with the other checks:

    uv run --no-project python scripts/guard_data.py

It reads git's index, which holds exactly what the next commit will contain:
the tracked files plus everything staged, including files forced past
.gitignore with `git add -f`. Following the test-data policy
(docs/masterplan/05-build-process.md section 5, decisions D-21 and D-48), it refuses:

- market-data files by name (.parquet, .dbn, .csv, .tsv, .xls, .zip, .gz, .7z,
  NinjaTrader's .ncd, ...) anywhere outside fixtures/synthetic/; files under any
  other name whose first bytes are a data format (Parquet, Arrow, Feather, Sierra
  Chart intraday, DBN, zstd, gzip, zip, 7z, xz, bzip2, lz4, tar, SQLite, DuckDB,
  HDF5, OLE2, NumPy, pickle); and text exports (.txt, .prn, .asc, .dat, .itxt,
  .dly, or no suffix) whose first lines are a table of numbers, such as a
  NinjaTrader or TradeStation export;
- data files under fixtures/synthetic/ that its MANIFEST.json does not list with
  their exact SHA-256, so a file dropped there cannot pass for a generated
  fixture (a hand-written manifest entry is caught by the regeneration test in
  `just test`, python/tests/test_gen_fixtures.py, not here);
- files over 25 MB;
- .env files (`.env*`, `*.env`), keys, and certificates, and API keys, tokens,
  passwords, or private keys inside text files (UTF-8, or UTF-16 with a byte-order mark);
- notebooks with cell outputs, which can hold licensed data.

A file that one commit adds and a later one removes stays in the history that a
push sends, so two more modes check every commit's own files: CI checks a pull
request's commits, and the pre-push hook (.githooks/pre-push) what a push sends,
from the ref lines git writes to its standard input:

    uv run --no-project python scripts/guard_data.py --commits origin/main..HEAD
    uv run --no-project python scripts/guard_data.py --pushed origin

Exits 0 when the index (or every commit) is clean, 1 with every problem listed,
and 2 when git cannot be read; a commit or a push stops on anything but 0.
Standard library only.
"""

from __future__ import annotations

import argparse
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
    ".arrows",
    ".feather",
    ".ipc",
    ".zip",
    ".h5",
    ".hdf5",
    ".duckdb",
    ".sqlite",
    ".sqlite3",
    ".db",
    ".csv",
    ".tsv",
    ".jsonl",
    ".ndjson",
    ".xls",
    ".xlsx",
    ".gz",
    ".tar",
    ".7z",
    ".xz",
    ".bz2",
    ".lz4",
    ".ncd",
    ".scid",
)
DATA_SIGNATURES = (
    (0, b"PAR1", "Parquet"),
    (0, b"ARROW1", "Arrow"),
    (0, b"FEA1", "Feather"),
    (0, b"SCID" + bytes([56, 0, 0, 0]), "Sierra Chart intraday"),
    *((0, b"DBN" + bytes([version]), "DBN") for version in (1, 2, 3)),
    (0, b"\x28\xb5\x2f\xfd", "zstd"),
    (0, b"\x1f\x8b", "gzip"),
    (0, b"PK\x03\x04", "zip"),
    (0, b"7z\xbc\xaf\x27\x1c", "7z"),
    (0, b"\xfd7zXZ\x00", "xz"),
    (4, b"1AY&SY", "bzip2"),
    (0, b"\x04\x22\x4d\x18", "lz4"),
    (257, b"ustar\x0000", "tar"),
    (257, b"ustar  \x00", "tar"),
    (0, b"SQLite format 3\x00", "SQLite"),
    (8, b"DUCK", "DuckDB"),
    (0, b"\x89HDF\r\n\x1a\n", "HDF5"),
    (0, b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "OLE2 (.xls)"),
    (0, b"\x93NUMPY", "NumPy"),
    *((0, bytes([0x80, protocol]), "pickle") for protocol in (2, 3, 4, 5)),
)
"""Where a data format's signature sits (its offset), the signature, and the format's name."""
PRICE_TABLE = "tabular price"
PRICE_TABLE_ROWS = 10
"""How many of a text file's first 20 lines (after at most one header line) must be rows of
numbers for the file to be a table of prices, such as an export saved as .txt or .prn."""
TEXT_EXPORT_SUFFIXES = (".txt", ".prn", ".asc", ".dat", ".itxt", ".dly")
"""The names platforms save bar and tick exports under as plain text (NinjaTrader, TradeStation,
Sierra Chart, MultiCharts), which are checked for a table of prices, as are names without a
suffix; Markdown, JSON, YAML, and source files are not, so a scenario table in Markdown passes."""
NUMERIC_FIELD = re.compile(r"[+\-]?[0-9][0-9.:/+\-TZ]*")
"""A number, date, or time as an export writes one: 5432.25, 20260305, 23:01:00, 03/05/2026."""
FIELD_SEPARATORS = re.compile(r"[,;|\s]+")
CLOCK_WORDS = frozenset({"am", "pm"})
NO_OBJECT = re.compile(r"0+")
"""The object id git writes for a branch a push deletes, or one the remote does not have."""
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

    def may_be_a_text_export(self) -> bool:
        name = self.name()
        return name.endswith(TEXT_EXPORT_SUFFIXES) or "." not in name.lstrip(".")

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


def tree_files(repository: Path, commit: str) -> list[IndexedFile]:
    """The files of a commit's tree, as `git ls-tree` lists them; a submodule keeps its mode."""
    listing = git_output(repository, ["ls-tree", "-r", "-z", "--full-tree", commit])
    return [parsed_tree_record(record) for record in listing.split(b"\0") if record]


def parsed_tree_record(record: bytes) -> IndexedFile:
    metadata, path = record.split(b"\t", 1)
    mode, _kind, object_id = metadata.decode("ascii").split(" ")
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


def data_format(file: IndexedFile, content: bytes) -> str | None:
    """The data format a file's first bytes name, `tabular price` for a text export that begins
    with a table of numbers, or None."""
    signed = next(
        (
            name
            for offset, signature, name in DATA_SIGNATURES
            if content.startswith(signature, offset)
        ),
        None,
    )
    if signed is not None or not file.may_be_a_text_export():
        return signed
    text = readable_text(content[:BINARY_SNIFF_BYTES])
    return PRICE_TABLE if text is not None and is_price_table(text) else None


def is_price_table(text: str) -> bool:
    """Whether at least `PRICE_TABLE_ROWS` of the text's first 20 non-empty lines, after at most
    one header line, are rows of three or more numbers, dates, or times."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines and not is_numeric_row(lines[0]):
        lines = lines[1:]
    rows = lines[: 2 * PRICE_TABLE_ROWS]
    return sum(is_numeric_row(line) for line in rows) >= PRICE_TABLE_ROWS


def is_numeric_row(line: str) -> bool:
    """Whether a line holds three or more numbers, dates, or times, quoted or not, beside at
    most one other field such as a symbol; `AM` and `PM` belong to their time."""
    fields = [field.strip("\"'") for field in FIELD_SEPARATORS.split(line)]
    kept = [field for field in fields if field and field.lower() not in CLOCK_WORDS]
    numbers = sum(NUMERIC_FIELD.fullmatch(field) is not None for field in kept)
    return numbers >= 3 and len(kept) - numbers <= 1


def content_problems(file: IndexedFile, content: bytes) -> Iterator[Problem]:
    found_format = data_format(file, content)
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
            or data_format(file, contents.get(file.object_id, b"")) is not None
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


def find_problems(
    repository: Path, max_file_bytes: int = MAX_FILE_BYTES, commit: str | None = None
) -> list[Problem]:
    """Every way the files in the repository's index, or in `commit`'s tree, break the data
    policy, sorted by path."""
    listed = indexed_files(repository) if commit is None else tree_files(repository, commit)
    files = [file for file in listed if not file.is_submodule()]
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


def counted(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")


def report(problems: Sequence[Problem]) -> str:
    listed = "\n\n".join(problem.describe() for problem in problems)
    return (
        f"Data guard: {counted(len(problems), 'problem')} in git's index (what the next commit "
        f"would contain).\n\n{listed}\n\nThe data policy: {POLICY}."
    )


PUSH_REMEDY = (
    "Nothing was pushed. A file that a later commit removes stays in the commit that added it, "
    "and a push sends that commit too: rewrite the commits the remote does not have yet so that "
    "none holds the file, for example with `git reset --soft origin/main` on a branch you have "
    "not pushed before, or `git reset --soft origin/<branch>` on one you have, then commit again "
    "and push."
)
PULL_REQUEST_REMEDY = (
    "These commits are on GitHub already, and GitHub keeps a pull request's commits even after "
    "its branch changes: close the pull request without merging it, push the work again on a new "
    "branch whose commits never held the file, and if the file is licensed data, ask GitHub "
    "Support to remove the closed pull request's commits."
)


@dataclass(frozen=True)
class CommitProblems:
    """A commit and the problems it brings: those its own files show that no earlier commit of
    the check showed, so a file one commit adds is reported there and not again after it."""

    commit: str
    subject: str
    problems: Sequence[Problem]


def commits_report(
    found: Sequence[CommitProblems], checked: int, described: str, remedy: str
) -> str:
    total = sum(len(commit.problems) for commit in found)
    blocks = "\n\n".join(
        f"{commit.commit[:12]} {commit.subject}\n\n"
        + "\n\n".join(problem.describe() for problem in commit.problems)
        for commit in found
    )
    return (
        f"Data guard: {counted(total, 'problem')} in {len(found)} of "
        f"{counted(checked, 'commit')} ({described}).\n\n{blocks}\n\n{remedy} "
        f"The data policy: {POLICY}."
    )


def repository_root() -> Path:
    return Path(git_output(Path.cwd(), ["rev-parse", "--show-toplevel"]).decode().strip())


def pushed_revisions(ref_lines: str, remote: str) -> list[str]:
    """The `git rev-list` arguments for what a push sends, from the lines git writes to the
    pre-push hook (`<local ref> <local object> <remote ref> <remote object>`): each pushed
    commit that no branch of `remote` already has; a push that only deletes sends none."""
    tips: list[str] = []
    for line in ref_lines.splitlines():
        fields = line.split()
        if len(fields) != 4:
            raise GitError(
                "Expected the pre-push lines '<local ref> <local object> <remote ref> "
                f"<remote object>' on standard input, got {line!r}."
            )
        if NO_OBJECT.fullmatch(fields[1]) is None:
            tips.append(fields[1])
    return [*tips, "--not", f"--remotes={remote}"] if tips else []


def check_index() -> int:
    try:
        problems = find_problems(repository_root())
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


def problems_by_commit(repository: Path, commits: Sequence[str]) -> list[CommitProblems]:
    """The problems each commit brings, oldest first, each reported at the first commit that
    shows it."""
    seen: set[tuple[str, Rule]] = set()
    found: list[CommitProblems] = []
    for commit in commits:
        # shortcut: each commit's whole tree is read again, about 0.4 s a commit in 2026-10;
        # cache blobs by object id when a push of a usual branch takes over 30 s.
        problems = find_problems(repository, commit=commit)
        new = [problem for problem in problems if (problem.path, problem.rule) not in seen]
        seen.update((problem.path, problem.rule) for problem in new)
        if new:
            found.append(CommitProblems(commit, subject_of(repository, commit), new))
    return found


def check_commits(revisions: Sequence[str], described: str, remedy: str) -> int:
    """Check each commit `git rev-list <revisions>` names, oldest first."""
    try:
        repository = repository_root()
        listed = git_output(repository, ["rev-list", "--reverse", *revisions]) if revisions else b""
        commits = listed.decode("ascii").split()
        found = problems_by_commit(repository, commits)
    except GitError as error:
        print(f"Data guard: could not read the commits of {described}. {error}", file=sys.stderr)
        return 2
    if found:
        print(commits_report(found, len(commits), described, remedy))
        return 1
    if not commits:
        print(f"Data guard: no commits to check in {described}.")
        return 0
    print(
        f"Data guard: the {counted(len(commits), 'commit')} of {described} hold no market data "
        "outside fixtures/synthetic/, no secrets, no files over 25 MB, and no notebook outputs."
    )
    return 0


def subject_of(repository: Path, commit: str) -> str:
    return git_output(repository, ["show", "-s", "--format=%s", commit]).decode().strip()


def parsed_arguments(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refuse market data, secrets, files over 25 MB, and notebook outputs in "
        "git's index (by default), in each commit of a range, or in what a push sends."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--commits",
        metavar="RANGE",
        help="check each commit of a revision range, such as origin/main..HEAD",
    )
    mode.add_argument(
        "--pushed",
        metavar="REMOTE",
        help="check what a push to REMOTE sends, from the ref lines git writes to the pre-push "
        "hook's standard input",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(errors="replace")
    arguments = parsed_arguments(argv)
    if arguments.commits is not None:
        range_only = ["--end-of-options", arguments.commits]
        return check_commits(range_only, arguments.commits, PULL_REQUEST_REMEDY)
    if arguments.pushed is None:
        return check_index()
    described = f"the push to {arguments.pushed}"
    try:
        revisions = pushed_revisions(sys.stdin.read(), arguments.pushed)
    except GitError as error:
        print(f"Data guard: could not read {described}. {error}", file=sys.stderr)
        return 2
    return check_commits(revisions, described, PUSH_REMEDY)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
