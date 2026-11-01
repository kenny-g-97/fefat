"""`just tick-check` (step 2.16, Done means 1 to 3, `scripts/tick_check.py`) on a generated tape
standing in for the IBKR sessions, since the real ones stay out of CI: three sessions of ESH2026
under the provider `ibkr`, their prints stamped to the second as IBKR stamps them, 1-minute bars
and no 1-second bars, the last session holding one print more than its last bar, as IBKR's
2026-09-23 does, beside a `databento` copy of the bars with one minute's volume changed and one
minute left out. The command writes the report with the sessions, the bar check of each session,
the match of the reference and Rust fills, the fidelity classes with their counts, and the
hashes, and no price of the tape; a store without the sessions skips it; fills the engines do
not share and differences without a class refuse it."""

import contextlib
import io
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import pytest

import gen_fixtures
import tick_check
from fefat.backtest.fidelity_classes import CLASSIFIED_COLUMNS
from fefat.config import resolve_paths
from fefat.market.engine_units import price_text
from fefat.market.layout import Dataset
from fefat.market.schema import parse_schema_name
from fefat.market.store import Store
from fefat.reference.rust_batch import FillView
from tick_check import TickCheck
from xcheck import CrossCheckStrategy, EntryKind

ROOT = Path(__file__).resolve().parents[2]
FIRST, MIDDLE, LAST = date(2026, 3, 2), date(2026, 3, 3), date(2026, 3, 4)
SECOND = 1_000_000_000
STRATEGIES = (
    CrossCheckStrategy("market", EntryKind.MARKET, 0, None, 12, 12),
    CrossCheckStrategy("limit", EntryKind.LIMIT, 2, 1, 12, 12),
    CrossCheckStrategy("stop", EntryKind.STOP, 2, 1, 12, 12),
)
GENERATED = TickCheck(
    provider="ibkr",
    root="ES",
    contract="ESH2026",
    reference_provider="databento",
    strategies=STRATEGIES,
)


@dataclass(frozen=True)
class Checked:
    """What `main` did on the generated store: its exit code and what it printed, the report and
    where it wrote it, the facts it saved for the notebook, its work folder, and the prices of
    the tape."""

    code: int
    printed: str
    report: str
    report_path: Path
    facts: dict[str, Any]
    work: Path
    prices: frozenset[int]


def dataset(provider: str, schema: str) -> Dataset:
    return Dataset(provider=provider, schema_name=parse_schema_name(schema), root="ES")


def stamped_to_the_second(store: Store) -> None:
    """The generated prints as IBKR stamps them, to the second, and one print more in the last
    session's last minute than its bar holds, which the engine cache then leaves out."""
    for file in store.list_partitions(dataset("ibkr", "trades")):
        prints = store.scan_partition(file.partition).collect()
        stamped = prints.with_columns(
            (pl.col("ts_recv") // SECOND * SECOND).alias("ts_recv"),
            (pl.col("ts_event") // SECOND * SECOND).alias("ts_event"),
        )
        if file.partition.key == LAST:
            extra = stamped.tail(1).with_columns(
                pl.lit(1, dtype=pl.UInt32).alias("size"), pl.col("sequence") + 1
            )
            stamped = pl.concat([stamped, extra])
        store.write_partition(file.partition, stamped)


def databento_bars(store: Store) -> tuple[int, int]:
    """A copy of the bars as another provider's: the volume of a minute of FIRST changed and a
    minute of MIDDLE left out, whose closes it returns."""
    shutil.copytree(store.folder / "ibkr" / "ohlcv-1m", store.folder / "databento" / "ohlcv-1m")
    (file,) = store.list_partitions(dataset("databento", "ohlcv-1m"))
    bars = store.scan_partition(file.partition).collect()
    changed = bars.filter(pl.col("trade_date") == FIRST).item(100, "ts_close")
    dropped = bars.filter(pl.col("trade_date") == MIDDLE).item(200, "ts_close")
    volume = pl.when(pl.col("ts_close") == changed).then(pl.col("volume") + 3)
    other = bars.with_columns(volume.otherwise(pl.col("volume")).alias("volume"))
    store.write_partition(file.partition, other.filter(pl.col("ts_close") != dropped))
    return changed, dropped


def generated_ibkr_store(data_dir: Path) -> frozenset[int]:
    """The generated sessions in `data_dir` as the module docstring says; the prices of the
    tape, its prints' and its bars'."""
    out = data_dir / "ibkr"
    dates = ["--dates", f"{FIRST}..{LAST}", "--contracts", "ESH2026"]
    assert gen_fixtures.main(["--out", str(out), *dates]) == 0
    shutil.rmtree(out / "ohlcv-1s")
    store = Store(data_dir)
    stamped_to_the_second(store)
    databento_bars(store)
    prints = pl.concat(
        store.scan_partition(file.partition).collect()
        for file in store.list_partitions(dataset("ibkr", "trades"))
    )
    (bars_file,) = store.list_partitions(dataset("ibkr", "ohlcv-1m"))
    bars = store.scan_partition(bars_file.partition).collect()
    prices = pl.concat(
        [prints["price"], *(bars[column] for column in ("open", "high", "low", "close"))]
    )
    return frozenset(prices.unique().to_list())


@pytest.fixture(name="checked", scope="module")
def fixture_checked(tmp_path_factory: pytest.TempPathFactory) -> Checked:
    home = tmp_path_factory.mktemp("tick-check")
    report = home / "ibkr-tick-check.md"
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("FEFAT_HOME", str(home / "home"))
        patch.setenv("FEFAT_DATA_DIR", str(home / "data"))
        prices = generated_ibkr_store(home / "data")
        patch.setattr(tick_check, "CHECK", GENERATED)
        patch.setattr(tick_check, "REPORT", report)
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            code = tick_check.main()
        work = resolve_paths(os.environ).workspace_dir / tick_check.WORK_FOLDER
    facts = json.loads((work / "facts.json").read_text(encoding="utf-8"))
    text = report.read_text(encoding="utf-8")
    return Checked(code, printed.getvalue(), text, report, facts, work, prices)


def strategy_facts(checked: Checked, name: str) -> dict[str, Any]:
    (found,) = [facts for facts in checked.facts["strategies"] if facts["name"] == name]
    return found


def test_the_report_names_the_sessions_and_the_level_each_filled_on(checked: Checked) -> None:
    assert checked.code == 0
    assert "## Versions and data" in checked.report
    sessions = {session["trade_date"]: session for session in checked.facts["sessions"]}
    assert list(sessions) == [str(FIRST), str(MIDDLE), str(LAST)]
    for day in (FIRST, MIDDLE):
        prints = sessions[str(day)]["prints"]
        assert f"- {day}: {prints:,} prints, filled on trade prints." in checked.report
    held_back = re.search(
        rf"- {LAST}: [\d,]+ prints, filled on 1-minute bars: the engine cache leaves its "
        r"prints out, since its records in the 1m bar opening at \S+ add up to (\d+) lots, "
        r"not the bar's (\d+)\.",
        checked.report,
    )
    assert held_back is not None
    assert int(held_back[1]) == int(held_back[2]) + 1
    assert f"Wrote {checked.report_path}" in checked.printed


def test_the_bars_rebuilt_from_the_prints_equal_the_providers_but_the_last_minute(
    checked: Checked,
) -> None:
    bars = {row["trade_date"]: row for row in checked.facts["bars"]}
    for day in (FIRST, MIDDLE):
        rebuilt = bars[str(day)]["rebuilt"]
        assert rebuilt["compared"] > 1_000
        assert rebuilt["differences"] == 0
        assert f"| {day} | {rebuilt['compared']:,} | 0 | none |" in checked.report
    last = bars[str(LAST)]["rebuilt"]
    assert last["differences"] == 2
    assert last["columns"] == ["trade_count", "volume"]
    assert f"| {LAST} | {last['compared']:,} | 2 | trade_count, volume at " in checked.report


def test_the_providers_bars_are_counted_against_the_other_providers(checked: Checked) -> None:
    bars = {row["trade_date"]: row["reference"] for row in checked.facts["bars"]}
    assert (bars[str(FIRST)]["volume_differs"], bars[str(FIRST)]["alone"]) == (1, 0)
    assert (bars[str(MIDDLE)]["volume_differs"], bars[str(MIDDLE)]["alone"]) == (0, 1)
    assert bars[str(MIDDLE)]["reference_alone"] == 0
    assert bars[str(LAST)]["price_differs"] == 0
    both = bars[str(FIRST)]["both"]
    assert f"| {FIRST} | {both:,} | 0 | 0 | 1 | 0 |" in checked.report


def test_the_reference_engine_fills_every_session_as_the_rust_engine(checked: Checked) -> None:
    for definition in STRATEGIES:
        differential = strategy_facts(checked, definition.name)["differential"]
        fills = differential["rust_fills"]
        assert fills > 0
        assert differential["reference_fills"] == differential["identical"] == fills
        assert differential["minute_identical"] == differential["minute_fills"] > 0
        assert differential["bar_sessions"] == [str(FIRST), str(MIDDLE), str(LAST)]
        assert differential["ticks_on_bars"]["sessions"] == [str(LAST)]
        assert differential["ticks_on_bars"]["fills"] > 0
        row = f"| {definition.name} | {FIRST} to {MIDDLE} | {differential['prints']:,} |"
        assert row in checked.report
        assert f"| {fills:,} | {fills:,} | {fills:,} |" in checked.report
    assert f"bars, {FIRST} to {LAST}, and their fills are identical" in checked.report


def test_every_difference_between_ticks_and_minutes_has_a_class(checked: Checked) -> None:
    for definition in STRATEGIES:
        fidelity = strategy_facts(checked, definition.name)["fidelity"]
        assert fidelity["unknown"] == 0
        assert fidelity["matched"] > 0
        classified = pl.read_parquet(checked.work / f"classified_{definition.name}.parquet")
        assert classified.schema == CLASSIFIED_COLUMNS
        assert (
            classified.height
            == fidelity["tick_trades"] + fidelity["minute_trades"] - (fidelity["matched"])
        )
        assert "unknown" not in classified["outcome"].to_list()
        assert fidelity["restamped"]["unknown"] == 0
    market = strategy_facts(checked, "market")["fidelity"]
    assert market["trades_by_class"]["bar_boundary"] > 0
    assert "Differences without a class, unknown: 0." in checked.report
    assert "| Strategy | Ticks | Minutes | Matched |" in checked.report
    assert "| Strategy | Trades apart | bar_path | entry_bar_path |" in checked.report


def test_each_runs_hashes_hold_on_a_second_run_and_on_a_prefix(checked: Checked) -> None:
    for definition in STRATEGIES:
        determinism = strategy_facts(checked, definition.name)["determinism"]
        assert determinism["key_again"] == determinism["run_key"]
        assert determinism["second_fills_hash"] == determinism["fills_hash"]
        assert determinism["saved_fills_hash"] == determinism["fills_hash"]
        assert [prefix["through"] for prefix in determinism["prefixes"]] == [
            str(FIRST),
            str(MIDDLE),
        ]
        assert all(prefix["equal"] for prefix in determinism["prefixes"])
        assert f"`{determinism['fills_hash'][:16]}`" in checked.report
        shared = determinism["shared_seconds"]
        assert 0 < shared["fills_in_shared_seconds"] <= shared["fills"]


def test_the_report_holds_no_price_of_the_tape(checked: Checked) -> None:
    written = set(re.findall(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])", checked.report))
    prices = {text for price in checked.prices for text in (price_text(price), str(price))}

    assert written & prices == set()


def test_the_notebooks_tables_are_left_in_the_work_folder(checked: Checked) -> None:
    for definition in STRATEGIES:
        for fidelity in ("ticks", "minutes"):
            trades = pl.read_parquet(checked.work / f"trades_{definition.name}_{fidelity}.parquet")
            assert trades.height > 0
    assert checked.facts["check"]["contract"] == "ESH2026"


def test_a_store_without_the_sessions_skips_the_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(tick_check, "REPORT", tmp_path / "ibkr-tick-check.md")

    assert tick_check.main() == 0

    assert "No ibkr trades of MNQZ2026 in the store: the tick check is skipped." in (
        capsys.readouterr().out
    )
    assert not (tmp_path / "ibkr-tick-check.md").exists()


def test_a_difference_without_a_class_refuses_the_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = tmp_path / "ibkr-tick-check.md"

    assert tick_check.published("# The report\n", 2, report) == 1

    assert not report.exists()
    assert "2 differences without a class: the report is not written" in capsys.readouterr().out


def test_fills_the_engines_do_not_share_are_refused() -> None:
    fill = FillView(
        5,
        100,
        4_000_250_000_000,
        "F-MKT-02",
        (),
        "taker",
        0,
        1,
        "buy",
        "entry",
        "trades",
        -1,
        0,
        "ESH2026",
    )
    moved = fill._replace(price=fill.price + 250_000_000)

    with pytest.raises(ValueError, match=r"fills of market on 2026-03-02 to be the Rust engine's"):
        tick_check.require_identical((fill,), (moved,), "market on 2026-03-02", 250_000_000)


def test_just_tick_check_runs_the_check() -> None:
    justfile = (ROOT / "justfile").read_text(encoding="utf-8")

    assert "tick-check:\n    uv run python scripts/tick_check.py\n" in justfile
