import hashlib
import io
import json
import re
from itertools import takewhile
from pathlib import Path

import pytest

import guard_data
from git_repository import GitRepository

ROOT = Path(__file__).resolve().parents[2]
GUARD_COMMAND = "uv run --no-project python scripts/guard_data.py"
FIXTURE_BYTES = b"PAR1 synthetic fixture bytes PAR1"
NINJATRADER_BARS = "".join(
    f"20260305 23{minute:02d}00;5432.25;5432.50;5432.00;5432.25;{minute + 1}\n"
    for minute in range(12)
).encode()
"""Twelve 1-minute bars as NinjaTrader 8 exports them: semicolons, no header, a `.txt` file."""
TRADESTATION_BARS = (
    "Date,Time,Open,High,Low,Close,Vol,OI\n"
    + "".join(
        f"03/05/2026,17{minute:02d},5432.25,5432.5,5432,5432.25,12,0\n" for minute in range(12)
    )
).encode()
"""The same bars as TradeStation's ASCII layout writes them, under one header line."""
SMALL_CSV = b"time,close\n1772751600,5432.25\n"
NO_OBJECT = "0" * 40
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


@pytest.fixture
def repository(tmp_path: Path) -> GitRepository:
    return GitRepository.initialized(tmp_path)


def rules_by_path(
    repository: GitRepository, max_file_bytes: int = guard_data.MAX_FILE_BYTES
) -> dict[str, list[guard_data.Rule]]:
    found: dict[str, list[guard_data.Rule]] = {}
    for problem in guard_data.find_problems(repository.folder, max_file_bytes):
        found.setdefault(problem.path, []).append(problem.rule)
    return found


def manifest_listing(files: dict[str, bytes]) -> bytes:
    entries = [
        {"path": path, "sha256": hashlib.sha256(content).hexdigest()}
        for path, content in files.items()
    ]
    return json.dumps({"files": entries}).encode()


def test_a_force_staged_parquet_outside_the_fixtures_is_refused_with_a_clear_message(
    repository: GitRepository,
) -> None:
    repository.stage("data/ES.parquet", FIXTURE_BYTES)

    problems = guard_data.find_problems(repository.folder)

    assert [(problem.path, problem.rule) for problem in problems] == [
        ("data/ES.parquet", guard_data.Rule.MARKET_DATA_OUTSIDE_FIXTURES)
    ]
    message = problems[0].describe()
    assert "only under fixtures/synthetic/" in message
    assert "FEFAT_DATA_DIR" in message
    assert 'git rm --cached "data/ES.parquet"' in message


def test_a_fixture_listed_in_the_manifest_with_its_hash_passes(repository: GitRepository) -> None:
    repository.stage("fixtures/synthetic/x.parquet", FIXTURE_BYTES)
    repository.stage(
        "fixtures/synthetic/MANIFEST.json", manifest_listing({"x.parquet": FIXTURE_BYTES})
    )

    assert guard_data.find_problems(repository.folder) == []


def test_a_fixture_missing_from_the_manifest_is_refused(repository: GitRepository) -> None:
    repository.stage("fixtures/synthetic/x.parquet", FIXTURE_BYTES)
    repository.stage("fixtures/synthetic/y.parquet", FIXTURE_BYTES)
    repository.stage(
        "fixtures/synthetic/MANIFEST.json", manifest_listing({"x.parquet": FIXTURE_BYTES})
    )

    assert rules_by_path(repository) == {
        "fixtures/synthetic/y.parquet": [guard_data.Rule.FIXTURE_NOT_IN_MANIFEST]
    }


def test_a_fixture_whose_bytes_differ_from_its_manifest_hash_is_refused(
    repository: GitRepository,
) -> None:
    repository.stage("fixtures/synthetic/x.parquet", b"real market data, renamed")
    repository.stage(
        "fixtures/synthetic/MANIFEST.json", manifest_listing({"x.parquet": FIXTURE_BYTES})
    )

    assert rules_by_path(repository) == {
        "fixtures/synthetic/x.parquet": [guard_data.Rule.FIXTURE_HASH_MISMATCH]
    }


def test_a_manifest_entry_without_its_file_in_git_is_refused(repository: GitRepository) -> None:
    repository.stage(
        "fixtures/synthetic/MANIFEST.json", manifest_listing({"x.parquet": FIXTURE_BYTES})
    )

    assert rules_by_path(repository) == {
        "fixtures/synthetic/x.parquet": [guard_data.Rule.MANIFEST_ENTRY_NOT_IN_GIT]
    }


def test_a_fixture_with_no_manifest_in_git_is_refused(repository: GitRepository) -> None:
    repository.stage("fixtures/synthetic/x.parquet", FIXTURE_BYTES)

    assert rules_by_path(repository) == {
        "fixtures/synthetic/x.parquet": [guard_data.Rule.FIXTURE_NOT_IN_MANIFEST]
    }


def test_a_manifest_that_is_not_the_expected_json_is_refused(repository: GitRepository) -> None:
    repository.stage("fixtures/synthetic/MANIFEST.json", b'{"files": "x.parquet"}')

    assert rules_by_path(repository) == {
        "fixtures/synthetic/MANIFEST.json": [guard_data.Rule.MANIFEST_UNREADABLE]
    }


@pytest.mark.parametrize(
    "path", ["data/ES.PARQUET", "raw/glbx-mdp3.dbn.zst", "exports/trades.CSV.GZ"]
)
def test_market_data_extensions_are_matched_without_regard_to_case(
    repository: GitRepository, path: str
) -> None:
    repository.stage(path, FIXTURE_BYTES)

    assert rules_by_path(repository) == {path: [guard_data.Rule.MARKET_DATA_OUTSIDE_FIXTURES]}


def test_a_file_over_the_size_limit_is_refused(repository: GitRepository) -> None:
    repository.stage("docs/big.txt", b"x" * 11)
    repository.stage("docs/small.txt", b"x" * 10)

    assert rules_by_path(repository, max_file_bytes=10) == {
        "docs/big.txt": [guard_data.Rule.FILE_TOO_LARGE]
    }


def test_the_size_limit_is_25_mb() -> None:
    assert guard_data.MAX_FILE_BYTES == 25_000_000


def test_env_files_are_refused_and_the_example_passes(repository: GitRepository) -> None:
    for path in [".env", "python/.env.local", ".envrc", "config/prod.env", ".env.example"]:
        repository.stage(path, b"FEFAT_HOME=\n")

    assert rules_by_path(repository) == {
        ".env": [guard_data.Rule.SECRET_FILE],
        "python/.env.local": [guard_data.Rule.SECRET_FILE],
        ".envrc": [guard_data.Rule.SECRET_FILE],
        "config/prod.env": [guard_data.Rule.SECRET_FILE],
    }


@pytest.mark.parametrize(
    "path", ["certs/server.pem", "certs/client.KEY", "keys/id_ed25519", "store.p12"]
)
def test_key_and_certificate_files_are_refused(repository: GitRepository, path: str) -> None:
    repository.stage(path, b"not a real key\n")

    assert rules_by_path(repository) == {path: [guard_data.Rule.SECRET_FILE]}


@pytest.mark.parametrize(
    "secret_line",
    [
        "client = Anthropic(api_key='" + "sk-ant-" + "api03-" + "Q" * 40 + "')",
        "databento.Historical('" + "db-" + "a1B2" * 8 + "')",
        "token: " + "ghp" + "_" + "Z9" * 20,
        "aws_access_key_id = " + "AKIA" + "ABCDEFGHIJKLMNOP",
        "-----BEGIN " + "OPENSSH PRIVATE KEY-----",
        "DATABENTO" + "_API_KEY=" + "q7" * 16,
        "API" + "_KEY=" + "a1b2" * 5,
        "PASS" + "WORD=" + "Hunter2" * 3,
        "DATABENTO" + "_API_KEY: " + "x9" * 10,
        '{"API' + '_KEY": "' + "k3" * 10 + '"}',
        "api" + "_key = '" + "abcd1234" * 3 + "'",
        "SECRET" + '_KEY = "' + "a1b2c3d4e5" * 2 + '"',
        "AWS_SECRET" + "_ACCESS_KEY=" + "wJalrXUtnFEMI/K7MDENG/" + "bPxRfiCYEXAMPLEKEY",
        "secret" + 'Key: "' + "Zz9" * 7 + '"',
        "webpush(info, payload, vapid_private" + '_key="' + "Xk2b" * 6 + '")',
        'os.environ["PUSH' + '_TOKEN"] = "' + "azGD9" * 5 + '"',
        "PUSH" + '_TOKEN: Final = "' + "azGD9" * 5 + '"',
        "api" + '_token: str = "' + "azGD9" * 5 + '"',
        "PASS" + 'WORD="' + "Tr4d3r!Pass#" + "2026xyz" + '"',
        "pass" + "word = '" + "S3cure@Fefat#" + "2026!" + "'",
        "pushover" + "_token: " + "azGDORePK8gMaC0Q" + "OYAMyEEuzJnyUi",
        "  pass" + "word: " + "S3cure2026" + "Password",
    ],
)
def test_a_secret_in_a_text_file_is_refused(repository: GitRepository, secret_line: str) -> None:
    repository.stage("notes/setup.md", f"# Setup\n\n{secret_line}\n".encode())

    assert rules_by_path(repository) == {"notes/setup.md": [guard_data.Rule.SECRET_IN_TEXT]}


def test_a_key_in_a_utf_16_text_file_is_refused(repository: GitRepository) -> None:
    text = "ANTHROPIC = '" + "sk-ant-" + "Q" * 40 + "'\r\n"
    repository.stage("notes/powershell-output.txt", text.encode("utf-16"))

    assert rules_by_path(repository) == {
        "notes/powershell-output.txt": [guard_data.Rule.SECRET_IN_TEXT]
    }


@pytest.mark.parametrize(
    "line",
    [
        'DATABENTO_API_KEY = "databento-api-key"',
        "token = credential_store.read_token()",
        "GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}",
        'password = "<your password here>"',
        "ANTHROPIC_API_KEY=",
        "ANTHROPIC_API_KEY=sk-ant-api03-...",
        'CACHE_KEY = "features/v1/ES/2024"',
        "MAX_TOKENS = 16000",
        "token: credential_store.read_token()",
        "password: <your password here>",
    ],
)
def test_names_and_placeholders_that_only_look_like_secrets_pass(
    repository: GitRepository, line: str
) -> None:
    repository.stage("notes/setup.md", f"# Setup\n\n{line}\n".encode())

    assert guard_data.find_problems(repository.folder) == []


def test_a_key_in_a_notebook_cell_is_refused_though_json_escapes_its_quotes(
    repository: GitRepository,
) -> None:
    source = "PUSHOVER" + '_TOKEN = "' + "azGDORePK8gMaC0Q" + "OYAMyEEuzJnyUi" + '"\n'
    cell = {**NOTEBOOK_WITH_OUTPUTS["cells"][0], "outputs": [], "source": [source]}
    notebook = {**NOTEBOOK_WITH_OUTPUTS, "cells": [cell]}
    repository.stage("notebooks/keys.ipynb", json.dumps(notebook).encode())

    assert rules_by_path(repository) == {"notebooks/keys.ipynb": [guard_data.Rule.SECRET_IN_TEXT]}


def test_a_line_that_matches_several_patterns_names_its_kind_once(
    repository: GitRepository,
) -> None:
    repository.stage("config/settings.json", ('{"API' + '_KEY": "' + "k3" * 10 + '"}\n').encode())

    problems = guard_data.find_problems(repository.folder)

    assert len(problems) == 1
    assert problems[0].describe().count(guard_data.PLAIN_TEXT_SECRET) == 1


def test_a_staged_notebook_with_outputs_is_refused(repository: GitRepository) -> None:
    repository.stage("notebooks/demo.ipynb", json.dumps(NOTEBOOK_WITH_OUTPUTS).encode())

    problems = guard_data.find_problems(repository.folder)

    assert [(problem.path, problem.rule) for problem in problems] == [
        ("notebooks/demo.ipynb", guard_data.Rule.NOTEBOOK_WITH_OUTPUTS)
    ]
    assert "just strip-notebooks" in problems[0].describe()


def test_a_notebook_without_outputs_passes(repository: GitRepository) -> None:
    cell = {**NOTEBOOK_WITH_OUTPUTS["cells"][0], "outputs": [], "execution_count": None}
    repository.stage(
        "notebooks/demo.ipynb", json.dumps({**NOTEBOOK_WITH_OUTPUTS, "cells": [cell]}).encode()
    )

    assert guard_data.find_problems(repository.folder) == []


def test_ordinary_files_pass(repository: GitRepository) -> None:
    repository.stage(
        "README.md", b"# FEFAT\n\nReal data lives under FEFAT_DATA_DIR; see .env.example.\n"
    )
    repository.stage("python/fefat/src/fefat/__init__.py", b'__version__ = "0.0.1"\n')
    repository.stage("web/public/logo.png", b"\x89PNG\r\n\x1a\n" + bytes(16))

    assert guard_data.find_problems(repository.folder) == []


@pytest.mark.parametrize(
    ("path", "content"),
    [
        ("data/es_1m.pq", FIXTURE_BYTES),
        ("data/es", FIXTURE_BYTES),
        ("notebooks/cache.pkl", b"\x80\x05\x95" + bytes(16)),
        ("data/es.npy", b"\x93NUMPY\x01\x00" + bytes(16)),
        ("data/es.npz", b"PK\x03\x04" + bytes(16)),
        ("data/trades.json.gz", b"\x1f\x8b\x08" + bytes(16)),
        ("data/es.dat", b"DBN\x02" + bytes(16)),
        ("backups/store-7z.bin", b"7z\xbc\xaf\x27\x1c" + bytes(16)),
        ("backups/store-xz.bin", b"\xfd7zXZ\x00" + bytes(16)),
        ("backups/store-bzip2.bin", b"BZh91AY&SY" + bytes(16)),
        ("backups/store-lz4.bin", b"\x04\x22\x4d\x18" + bytes(16)),
        ("backups/posix-tar.bin", bytes(257) + b"ustar\x0000" + bytes(16)),
        ("backups/gnu-tar.bin", bytes(257) + b"ustar  \x00" + bytes(16)),
        ("data/bars-xls.bin", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + bytes(16)),
        ("data/bars-feather.bin", b"FEA1" + bytes(16)),
        ("data/bars-arrow-stream.bin", b"\xff\xff\xff\xff\x10\x01\x00\x00" + bytes(16)),
        ("data/store-duckdb.bin", bytes(8) + b"DUCK" + bytes(16)),
    ],
)
def test_data_under_another_name_is_refused_by_its_first_bytes(
    repository: GitRepository, path: str, content: bytes
) -> None:
    repository.stage(path, content)

    assert rules_by_path(repository) == {path: [guard_data.Rule.MARKET_DATA_OUTSIDE_FIXTURES]}


def test_main_refuses_with_exit_2_when_git_cannot_be_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    monkeypatch.chdir(tmp_path)

    assert guard_data.main([]) == 2
    assert "could not read git's index" in capsys.readouterr().err


def test_main_lists_every_problem_and_exits_1(
    repository: GitRepository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repository.stage("data/ES.parquet", FIXTURE_BYTES)
    repository.stage(".env", b"FEFAT_HOME=\n")
    monkeypatch.chdir(repository.folder)

    assert guard_data.main([]) == 1

    output = capsys.readouterr().out
    assert "data/ES.parquet" in output
    assert ".env" in output
    assert "2 problems" in output


def test_this_repository_passes_the_guard() -> None:
    assert guard_data.find_problems(ROOT) == []


def test_just_check_runs_the_guard() -> None:
    lines = (ROOT / "justfile").read_text(encoding="utf-8").splitlines()
    recipe = takewhile(lambda line: line.startswith("    "), lines[lines.index("check:") + 1 :])

    assert GUARD_COMMAND in [line.strip() for line in recipe]


def test_the_guard_and_the_claude_code_file_guard_know_the_same_market_data_extensions() -> None:
    source = (ROOT / ".claude" / "hooks" / "guard-file-paths.mjs").read_text(encoding="utf-8")
    declaration = re.search(r"const MARKET_DATA_SUFFIXES = \[(.*?)\];", source, re.DOTALL)
    assert declaration is not None

    assert set(guard_data.MARKET_DATA_SUFFIXES) == set(
        re.findall(r'"([^"]+)"', declaration.group(1))
    )


def test_data_under_another_name_in_the_fixtures_needs_its_manifest_entry(
    repository: GitRepository,
) -> None:
    repository.stage("fixtures/synthetic/es_notes.bin", FIXTURE_BYTES)
    repository.stage("fixtures/synthetic/MANIFEST.json", manifest_listing({}))

    assert rules_by_path(repository) == {
        "fixtures/synthetic/es_notes.bin": [guard_data.Rule.FIXTURE_NOT_IN_MANIFEST]
    }


@pytest.mark.parametrize(
    "path",
    [
        "exports/ES 03-26.csv",
        "exports/es_bars.TSV",
        "data/trades.jsonl",
        "data/trades.ndjson",
        "data/bars.xls",
        "data/bars.xlsx",
        "data/bars.gz",
        "backups/store.tar",
        "backups/store.7z",
        "data/bars.xz",
        "data/bars.bz2",
        "data/bars.lz4",
        "data/bars.arrows",
    ],
)
def test_text_tables_spreadsheets_and_archives_are_refused_by_name(
    repository: GitRepository, path: str
) -> None:
    repository.stage(path, SMALL_CSV)

    assert rules_by_path(repository) == {path: [guard_data.Rule.MARKET_DATA_OUTSIDE_FIXTURES]}


def test_a_table_of_prices_in_a_text_file_is_refused_outside_the_fixtures(
    repository: GitRepository,
) -> None:
    repository.stage("exports/ES 03-26.Last.txt", NINJATRADER_BARS)
    repository.stage("exports/ESH26.prn", TRADESTATION_BARS)

    problems = guard_data.find_problems(repository.folder)

    assert [(problem.path, problem.rule) for problem in problems] == [
        ("exports/ES 03-26.Last.txt", guard_data.Rule.MARKET_DATA_OUTSIDE_FIXTURES),
        ("exports/ESH26.prn", guard_data.Rule.MARKET_DATA_OUTSIDE_FIXTURES),
    ]
    assert "tabular price data under another name" in problems[0].describe()


def test_prose_requirements_and_a_few_rows_of_numbers_in_text_files_pass(
    repository: GitRepository,
) -> None:
    repository.stage(
        "notes/measurements.txt",
        b"Load times on 2026-10-15:\n- MES 5m, 2024 Q1: 1.2 s warm\n- four reports: 17 s\n",
    )
    repository.stage("requirements.txt", b"polars==2.0.0\npyyaml>=6.0.3,<7\n")
    repository.stage("notes/five-bars.txt", b"".join(NINJATRADER_BARS.splitlines(True)[:5]))

    assert guard_data.find_problems(repository.folder) == []


def test_a_table_of_numbers_in_markdown_passes(repository: GitRepository) -> None:
    # Scenario tables and goldens are specifications written by hand, not exports.
    rows = "".join(f"| 09:30:{second:02d} | 5432.25 | 2 |\n" for second in range(12))
    repository.stage("fixtures/scenarios/stop-gap.md", f"# A gap\n\n{rows}".encode())

    assert guard_data.find_problems(repository.folder) == []


@pytest.mark.parametrize(
    ("path", "content"),
    [
        ("fixtures/synthetic/exports/tradingview/ESH2026.csv", SMALL_CSV),
        ("fixtures/synthetic/exports/ninjatrader/ES 03-26.Last.txt", NINJATRADER_BARS),
    ],
)
def test_a_text_table_in_the_fixtures_needs_its_manifest_entry(
    repository: GitRepository, path: str, content: bytes
) -> None:
    repository.stage(path, content)
    repository.stage("fixtures/synthetic/MANIFEST.json", manifest_listing({}))

    assert rules_by_path(repository) == {path: [guard_data.Rule.FIXTURE_NOT_IN_MANIFEST]}


def committed(repository: GitRepository, message: str) -> str:
    """Commit what is staged, without the commit gate, and return the commit's id."""
    done = repository.commit(message)
    assert done.returncode == 0, done.stdout + done.stderr
    return repository.git("rev-parse", "HEAD").stdout.strip()


def a_branch_that_adds_and_removes_bars(repository: GitRepository) -> tuple[str, str]:
    """A first commit, one that adds `data/bars.csv`, and one that removes it: the first
    commit's id and the last's."""
    repository.stage("README.md", b"# Notes\n")
    first = committed(repository, "Start the notes")
    repository.stage("data/bars.csv", SMALL_CSV)
    committed(repository, "Add the bars")
    assert repository.git("rm", "--quiet", "data/bars.csv").returncode == 0
    return first, committed(repository, "Remove the bars")


def test_every_commit_of_a_range_is_checked_not_only_its_last(
    repository: GitRepository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    first, _ = a_branch_that_adds_and_removes_bars(repository)
    monkeypatch.chdir(repository.folder)

    assert guard_data.find_problems(repository.folder) == []
    assert guard_data.main(["--commits", f"{first}..HEAD"]) == 1

    output = capsys.readouterr().out
    assert "1 problem in 1 of 2 commits" in output
    assert "Add the bars" in output
    assert "data/bars.csv" in output
    assert "Remove the bars" not in output


def test_a_range_without_commits_passes(
    repository: GitRepository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repository.stage("README.md", b"# Notes\n")
    committed(repository, "Start the notes")
    monkeypatch.chdir(repository.folder)

    assert guard_data.main(["--commits", "HEAD..HEAD"]) == 0
    assert "no commits to check" in capsys.readouterr().out


@pytest.mark.parametrize("remote_object", ["first", NO_OBJECT])
def test_a_push_checks_each_commit_the_remote_does_not_have(
    repository: GitRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    remote_object: str,
) -> None:
    first, last = a_branch_that_adds_and_removes_bars(repository)
    repository.git("update-ref", "refs/remotes/origin/main", first)
    remote = first if remote_object == "first" else NO_OBJECT
    pushed = f"refs/heads/notes {last} refs/heads/notes {remote}\n"
    monkeypatch.setattr("sys.stdin", io.StringIO(pushed))
    monkeypatch.chdir(repository.folder)

    assert guard_data.main(["--pushed", "origin"]) == 1

    output = capsys.readouterr().out
    assert "1 problem in 1 of 2 commits" in output
    assert "Add the bars" in output


def test_a_push_that_only_deletes_a_branch_has_no_commits_to_check(
    repository: GitRepository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    first, _ = a_branch_that_adds_and_removes_bars(repository)
    monkeypatch.setattr(
        "sys.stdin", io.StringIO(f"(delete) {NO_OBJECT} refs/heads/old-notes {first}\n")
    )
    monkeypatch.chdir(repository.folder)

    assert guard_data.main(["--pushed", "origin"]) == 0
    assert "no commits to check" in capsys.readouterr().out


def test_a_push_line_git_would_not_write_is_refused(
    repository: GitRepository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repository.stage("README.md", b"# Notes\n")
    committed(repository, "Start the notes")
    monkeypatch.setattr("sys.stdin", io.StringIO("refs/heads/notes\n"))
    monkeypatch.chdir(repository.folder)

    assert guard_data.main(["--pushed", "origin"]) == 2
    assert "Expected" in capsys.readouterr().err
