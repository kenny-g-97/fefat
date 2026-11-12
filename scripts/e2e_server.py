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
one each run. `just dev` seeds a home of its own the same way (`seed`, step 5.1). On the fixtures,
the seed also saves the breakout template as the strategy `demo` and runs it, the run the specs
call `demo-run-01`, and indexes both as `fefat db import-workspace` does (step 5.3); and writes a
year of MES's 1-minute bars, a product of the catalog, which the fixtures hold none of (step 5.4).
"""

import os
import shutil
import sys
import tempfile
import warnings
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "synthetic"
HOME_NAME = "fefat-e2e"
DEMO_WINDOW = ("2026-03-05", "2026-03-09")
"""The fixtures' trade dates the demo run spans, across their roll of 2026-03-09."""


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
    `data_dir` where one is named; keyring at its null backend; `password` set; and, on the
    fixtures, the demo strategy and its first run (`demo_run`)."""
    seeded_home(home, port)
    os.environ["FEFAT_HOME"] = str(home)
    os.environ["FEFAT_DATA_DIR"] = str(home / "data" if data_dir is None else data_dir)
    os.environ["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    # Imported once the environment is set, which keyring reads when it first picks a backend.
    from fefat.config import resolve_paths
    from fefat_app.container import opened_container

    with opened_container(resolve_paths(os.environ)) as container:
        container.logins.set_password(password)
    if data_dir is None:
        demo_run()
        year_of_mes()


def year_of_mes() -> None:
    """A year of MES's 1-minute bars from 2025-04-01 to 2026-03-31 in five quarterly contracts
    of the provider `synthetic`, written into the data folder by the tests' generator
    (`python/tests/generated_minutes.py`), unchecked: a product of the catalog for the catalog
    page's Update, and a year of 5-minute bars for the chart to scroll back through (step 5.4)."""
    tests = str(ROOT / "python" / "tests")
    sys.path.insert(0, tests)
    try:
        from generated_minutes import YEAR, write_minutes
    finally:
        sys.path.remove(tests)
    write_minutes(tuple(replace(each, contract=f"M{each.contract}") for each in YEAR), root="MES")


def demo_run() -> None:
    """The engine guide's breakout template saved as the strategy `demo`, on ES, which the
    fixtures hold, its run on the fixtures over `DEMO_WINDOW`, made through the SDK as a notebook
    makes it, and both indexed as `fefat db import-workspace` indexes them, so that the server
    starts with a run and no job (step 5.3)."""
    import fefat as ff
    from fefat_app.cli import main as fefat

    (breakout,) = [each for each in ff.strategy.templates() if each.name == "breakout"]
    code = breakout.code.replace('instrument="MES"', 'instrument="ES"')
    if code == breakout.code:
        raise SystemExit(
            "Expected the breakout template on MES, to run it on the fixtures' ES, got another "
            "instrument: seed the demo run on the template's own."
        )
    version = ff.strategy.save("demo", code, hypothesis=breakout.hypothesis)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # the fixtures' fee table and the like; the run keeps them
        ff.backtest.run(version.strategy(), *DEMO_WINDOW)
    if fefat(["db", "import-workspace"]) != 0:
        raise SystemExit(
            "Expected `fefat db import-workspace` to index the demo strategy and its run, got "
            "its refusal above: the seeded server would start without demo-run-01."
        )


def main() -> int:
    port = int(required("FEFAT_E2E_PORT"))
    password = required("FEFAT_E2E_PASSWORD")
    seed(Path(tempfile.gettempdir()) / HOME_NAME, port, password)
    from fefat_app.cli import main as fefat

    return fefat(["up"])


if __name__ == "__main__":
    sys.exit(main())
