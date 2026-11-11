"""Serve the app on a seeded temporary home for the Playwright harness (step 4.3): `just e2e`
starts it through `web/playwright.config.ts`, waits for `/v1/healthz`, and stops it when the
specs end.

    uv run python scripts/e2e_server.py

It reads FEFAT_E2E_PORT and FEFAT_E2E_PASSWORD, which the configuration sets; makes the home
`fefat-e2e` in the system's temporary folder afresh, outside every git working tree as
`fefat.config` requires, with a `config.toml` at that port and the synthetic fixtures as its
data; keeps keyring at its null backend, so that no secret of this machine is read or written;
sets the password, since `fefat up` would ask for it at a console that a harness has not (from
`BACKLOG.md`); and runs `fefat up` until it is stopped. Playwright stops it with taskkill on
Windows, which runs no cleanup, so the home is one folder wiped at each start rather than a new
one each run. `just dev` seeds a home of its own the same way (`seed`, step 5.1).
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "synthetic"
HOME_NAME = "fefat-e2e"


def required(name: str) -> str:
    """The environment's `name`, which the harness's configuration sets."""
    value = os.environ.get(name)
    if not value:
        raise SystemExit(
            f"Expected {name} in the environment, as web/playwright.config.ts sets it, got none."
        )
    return value


def seeded_home(home: Path, port: int) -> None:
    """`home` made afresh, with a `config.toml` at `port` and the synthetic fixtures as the
    provider `synthetic` of its data folder; refused where the old home cannot be wiped."""
    if home.exists():
        try:
            shutil.rmtree(home)
        except OSError as held:
            raise SystemExit(
                f"Expected to wipe {home} for a fresh home, got {held}: is the server of an "
                "earlier `just e2e` still running?"
            ) from held
    home.mkdir(parents=True)
    (home / "config.toml").write_text(f"port = {port}\n", encoding="utf-8")
    shutil.copytree(FIXTURES, home / "data" / "synthetic")


def seed(home: Path, port: int, password: str, data_dir: Path | None = None) -> None:
    """`home` seeded (`seeded_home`) and named FEAT's home in this process's environment, which
    the server it starts inherits, with its copy of the fixtures as the data folder, or
    `data_dir` where one is named; keyring at its null backend; and `password` set."""
    seeded_home(home, port)
    os.environ["FEFAT_HOME"] = str(home)
    os.environ["FEFAT_DATA_DIR"] = str(home / "data" if data_dir is None else data_dir)
    os.environ["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    # Imported once the environment is set, which keyring reads when it first picks a backend.
    from fefat.config import resolve_paths
    from fefat_app.container import opened_container

    with opened_container(resolve_paths(os.environ)) as container:
        container.logins.set_password(password)


def main() -> int:
    port = int(required("FEFAT_E2E_PORT"))
    password = required("FEFAT_E2E_PASSWORD")
    seed(Path(tempfile.gettempdir()) / HOME_NAME, port, password)
    from fefat_app.cli import main as fefat

    return fefat(["up"])


if __name__ == "__main__":
    sys.exit(main())
