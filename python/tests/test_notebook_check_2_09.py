"""The check notebook of step 2.9 (Your checks) runs top to bottom, as Run All does: it holds a
short BTCUSDT-PERP position through the fixtures' funding times in both engines, which agree, and
works each payment out again from the position's notional and the fixture's rate; then, on a
store of synthetic 1-minute bars, it carries a long across ES's roll at the open of 2026-03-09,
where both engines give the roll's two fills on two contracts and move the bracket by the gap."""

from pathlib import Path

import pytest

from fefat.reference.event_log import EventKind
from notebook_runs import run_notebook, store_with

NOTEBOOKS = Path(__file__).resolve().parents[2] / "notebooks"


def test_the_check_notebook_pays_funding_at_the_rate_and_carries_a_long_across_the_roll(
    capsys: pytest.CaptureFixture[str],
) -> None:
    store_with("ohlcv-1m")

    check = run_notebook(NOTEBOOKS / "checks" / "2.09.ipynb")

    printed = capsys.readouterr().out
    assert "The Rust engine agrees with the reference engine on the short." in printed
    assert (
        "At 2026-03-07 08:00:00 UTC the short received 1.433459 USDT: 0.100 BTC at the mark "
        "97994.2 is 9799.42 USDT, times the rate 0.00014628 is 1.4334591576, rounded down: True."
    ) in printed
    assert (
        "At 2026-03-07 16:00:00 UTC the short paid 0.056153 USDT: 0.100 BTC at the mark 97997.7 "
        "is 9799.77 USDT, times the rate -0.00000573 is -0.0561526821, rounded down: True."
    ) in printed
    assert "Flat at 2026-03-07 00:00:00 UTC, the short paid nothing then." in printed
    warnings = [
        entry for entry in check["FUNDED"].reference.log.entries if entry.kind is EventKind.WARNING
    ]
    assert [(entry.order, entry.rule) for entry in warnings] == [(1, "F-FEE-01")]
    assert (
        "ES from synthetic: the roll from ESH2026 to ESM2026 at the open of 2026-03-09, by volume"
    ) in printed
    assert "The Rust engine agrees with the reference engine across the roll." in printed
    legs = [fill for fill in check["FILLS"] if fill.rule == "F-ROL-02"]
    assert [(leg.contract, str(leg.role)) for leg in legs] == [
        ("ESH2026", "roll_volume"),
        ("ESM2026", "roll_volume"),
    ]
    assert "sell 1 ESH2026 and buy 1 ESM2026, both roll_volume: True." in printed
    assert "The stop and the target moved by the roll's gap: True." in printed
