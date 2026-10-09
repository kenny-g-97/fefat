import hashlib
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

    assert guard_data.find_problems(repository.folder) == []


def test_main_refuses_with_exit_2_when_git_cannot_be_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    monkeypatch.chdir(tmp_path)

    assert guard_data.main() == 2
    assert "could not read git's index" in capsys.readouterr().err


def test_main_lists_every_problem_and_exits_1(
    repository: GitRepository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repository.stage("data/ES.parquet", FIXTURE_BYTES)
    repository.stage(".env", b"FEFAT_HOME=\n")
    monkeypatch.chdir(repository.folder)

    assert guard_data.main() == 1

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
