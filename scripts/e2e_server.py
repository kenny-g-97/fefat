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
call `demo-run-01`, and indexes both as `fefat db import-workspace` does (step 5.3); writes a
year of MES's 1-minute bars, a product of the catalog, which the fixtures hold none of (step 5.4);
and writes two NinjaTrader exports of a product FEFAT does not know beside the home, under the
import root its `config.toml` names, for the import wizard's spec (step 5.12).
"""

import os
import shutil
import sys
import tempfile
import warnings
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import polars as pl

    from fefat.market.calendar import SessionTable

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "synthetic"
HOME_NAME = "fefat-e2e"
DEMO_WINDOW = ("2026-03-05", "2026-03-09")
"""The fixtures' trade dates the demo run spans, across their roll of 2026-03-09."""
XES_FIRST = ("2026-02-02", "2026-02-06")
XES_SECOND = ("2026-02-05", "2026-02-11")
"""The trade dates of the import spec's two exports, which share two sessions (step 5.12)."""
XES_EXPORT_NAME = "XES 03-26.Last.txt"
"""The name NinjaTrader gives an export of XES March 2026, from which its preset reads the
contract."""
XES_MORE_NAMES = ("XES 06-26.Last.txt", "XES 09-26.Last.txt")
"""The names of the two more contracts of `XES_FIRST`'s dates, for a round of several files
(D-102)."""
XES_WITH_A_BREAK = ("XES 12-26.Last.txt", "XES 03-27.Last.txt", "XES 06-27.Last.txt")
XES_WITHOUT_A_BREAK = "XES 09-27.Last.txt"
"""The names of the exports of the folder `breaks`, `XES_FIRST`'s dates of four more
contracts, the first three with bars in the break after `XES_BREAK_AFTER`, for the
correction the import spec approves for one file and in a round (step 5.15)."""
XES_BREAK_AFTER = "2026-02-03"
"""The trade date after whose session the break holds bars in its last nine minutes, the
last closing at the next session's open, as a platform's stretch stamped early does."""


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
        xes_exports(home)


def xes_exports(home: Path) -> None:
    """Three NinjaTrader exports of XES, a product FEFAT does not know, in a folder beside `home`
    that its `config.toml` then names as its import root: XESH2026's 1-minute bars of the trade
    dates `XES_FIRST`, of `XES_SECOND`, which overlaps the first by two sessions, and the first
    again, revised, its last bar one lot more, as an export made before that bar closed differs
    from a later one; each in a folder of its own under the name NinjaTrader gives, stamped at
    their close in UTC from the tests' generator (`python/tests/generated_minutes.py`); and in
    the folder `more`, the first's bars as XESM2026 and XESU2026, ten lots each, so that XESH2026
    keeps the lead of the roll, for a round of several files (D-102); the import spec's files
    (step 5.12)."""
    import polars as pl

    from fefat.config import resolve_paths
    from fefat.market import instruments
    from fefat.market.calendar import sessions_of

    exports = home.parent / f"{home.name}-exports"
    if exports.exists():
        shutil.rmtree(exports)
    tests = str(ROOT / "python" / "tests")
    sys.path.insert(0, tests)
    try:
        from generated_minutes import listing, minutes_of, ninjatrader_lines
    finally:
        sys.path.remove(tests)
    days = (XES_FIRST[0], XES_SECOND[1])
    sessions = sessions_of(
        instruments.get("ES").session_calendar(), resolve_paths(os.environ).cache_dir
    )
    bars = minutes_of(
        listing("XESH2026", 4001, days, days), sessions.between(*map(date.fromisoformat, days))
    )
    written: dict[str, list[str]] = {}
    for folder, (first, last) in (("first", XES_FIRST), ("second", XES_SECOND)):
        held = bars.filter(
            pl.col("trade_date").is_between(date.fromisoformat(first), date.fromisoformat(last))
        )
        written[folder] = [f"{line}\n" for line in ninjatrader_lines(held)]
    *kept, last_bar = written["first"]
    stamp, *prices, volume = last_bar.rstrip("\n").split(";")
    written["revised"] = [*kept, ";".join([stamp, *prices, str(int(volume) + 1)]) + "\n"]
    for folder, lines in written.items():
        (exports / folder).mkdir(parents=True)
        (exports / folder / XES_EXPORT_NAME).write_text(
            "".join(lines), encoding="utf-8", newline="\n"
        )
    ten_lots = [line.rsplit(";", 1)[0] + ";10\n" for line in written["first"]]
    (exports / "more").mkdir()
    for name in XES_MORE_NAMES:
        (exports / "more" / name).write_text("".join(ten_lots), encoding="utf-8", newline="\n")
    breaks = with_bars_in_a_break(bars, sessions)
    (exports / "breaks").mkdir()
    for name in (*XES_WITH_A_BREAK, XES_WITHOUT_A_BREAK):
        held = breaks if name in XES_WITH_A_BREAK else breaks.filter("in_session")
        lines = ninjatrader_lines(held.with_columns(volume=pl.lit(10, dtype=pl.UInt64)))
        (exports / "breaks" / name).write_text(
            "".join(f"{line}\n" for line in lines), encoding="utf-8", newline="\n"
        )
    with (home / "config.toml").open("a", encoding="utf-8") as config:
        config.write(f'import_roots = ["{exports.as_posix()}"]\n')


def with_bars_in_a_break(bars: "pl.DataFrame", sessions: "SessionTable") -> "pl.DataFrame":
    """`XES_FIRST`'s `bars` and nine more in the last minutes of the break after
    `XES_BREAK_AFTER`, priced as that session's last bar, the last closing at the next
    session's open; `in_session` tells the bars of the sessions apart (step 5.15)."""
    import polars as pl

    first, last = map(date.fromisoformat, XES_FIRST)
    held = bars.filter(pl.col("trade_date").is_between(first, last))
    day = date.fromisoformat(XES_BREAK_AFTER)
    minute = 60_000_000_000
    next_open = sessions.following(day).open
    last_bar = held.filter(pl.col("trade_date") == day).tail(1)
    added = [
        last_bar.with_columns(ts_open=pl.lit(opened), ts_close=pl.lit(opened + minute))
        for opened in range(next_open - 9 * minute, next_open, minute)
    ]
    return pl.concat(
        [
            held.with_columns(in_session=True),
            *(each.with_columns(in_session=False) for each in added),
        ]
    ).sort("ts_open")


def year_of_mes() -> None:
    """A year of MES's 1-minute bars from 2025-04-01 to 2026-03-31 in five quarterly contracts
    of the provider `synthetic`, written into the data folder by the tests' generator
    (`python/tests/generated_minutes.py`), unchecked: a product of the catalog for its dataset
    page's Check quality, and a year of 5-minute bars for the chart to scroll back through (step
    5.4)."""
    tests = str(ROOT / "python" / "tests")
    sys.path.insert(0, tests)
    try:
        from generated_minutes import YEAR, write_minutes
    finally:
        sys.path.remove(tests)
    write_minutes(tuple(replace(each, contract=f"M{each.contract}") for each in YEAR), root="MES")


TEMPLATE_STOP = "stop_atr: float = 1.5"
"""The breakout template's stop in ATRs, as its code writes its default."""
WIDER_STOP = "stop_atr: float = 2.0"
"""The stop of the demo's version 2, which the version diff highlights (step 5.10)."""


def demo_run() -> None:
    """The engine guide's breakout template saved as the strategy `demo`, on ES, which the
    fixtures hold, its run on the fixtures over `DEMO_WINDOW`, made through the SDK as a notebook
    makes it, and both indexed as `fefat db import-workspace` indexes them, so that the server
    starts with a run and no job (step 5.3); and, for the comparison and the version diff of step
    5.10, its version 2 with a wider stop, `WIDER_STOP`, and its run, saved after the first, so
    that `demo-run-01` stays the oldest run of `demo`."""
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
    wider = code.replace(TEMPLATE_STOP, WIDER_STOP)
    if wider == code:
        raise SystemExit(
            f"Expected the breakout template's stop to read {TEMPLATE_STOP!r}, got another: seed "
            "the second version on the template's own."
        )
    second = ff.strategy.save("demo", wider, hypothesis=breakout.hypothesis, changelog="Wider stop")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # the fixtures' fee table and the like; the run keeps them
        ff.backtest.run(version.strategy(), *DEMO_WINDOW)
        ff.backtest.run(second.strategy(), *DEMO_WINDOW)
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
