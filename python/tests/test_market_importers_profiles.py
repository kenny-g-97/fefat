from pathlib import Path

import pytest
import yaml

from fefat.market.importers.file_import import FileImportRequest, preview_file
from fefat.market.importers.profiles import (
    ImportProfile,
    load_profile,
    parse_profile,
    preset_profiles,
    save_profile,
)
from fefat.market.instruments import STATIC_TABLE
from fefat.market.sources import SOURCE_GUIDE, PresetStatus

ROOT = Path(__file__).resolve().parents[2]
IBKR_SAMPLE = ROOT / "fixtures" / "synthetic" / "exports" / "ibkr" / "ESH2026-1min.csv"
PRESET_NAMES = [
    "databento-csv",
    "ibkr",
    "ninjatrader",
    "sierra-chart",
    "tradestation",
    "tradingview",
]


def test_the_presets_are_the_ones_the_guide_names_available_but_the_dbn_importer() -> None:
    available = {
        preset.id
        for source in SOURCE_GUIDE.sources
        for preset in source.presets
        if preset.status is PresetStatus.AVAILABLE
    }

    assert sorted(preset_profiles()) == PRESET_NAMES
    assert available - set(PRESET_NAMES) == {"databento"}
    assert all(profile.provider == name for name, profile in preset_profiles().items())


def a_profile_file(folder: Path, name: str = "es-tradingview-5m", **changes: object) -> Path:
    """A trader's own profile: TradingView's preset for 5-minute charts, as a YAML file."""
    profile = preset_profiles()["tradingview"].model_dump(mode="json")
    path = folder / f"{name}.yaml"
    path.write_text(yaml.safe_dump({**profile, "name": name, "timeframe": "5m", **changes}))
    return path


def test_a_profile_file_is_saved_by_its_first_import_and_found_by_its_name_afterwards(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    path = str(a_profile_file(tmp_path))

    first = load_profile(path, home)
    loading_saves_nothing = not (home / "profiles").exists()
    saved = save_profile(path, home)

    assert loading_saves_nothing and saved
    assert not save_profile(path, home)
    assert (home / "profiles" / "es-tradingview-5m.yaml").is_file()
    assert load_profile("es-tradingview-5m", home) == first
    assert str(first.timeframe) == "5m"


def test_a_different_profile_under_a_saved_name_is_refused(tmp_path: Path) -> None:
    home = tmp_path / "home"
    save_profile(str(a_profile_file(tmp_path)), home)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    other = a_profile_file(elsewhere, timeframe="15m")

    with pytest.raises(ValueError, match="as saved in"):
        load_profile(str(other), home)


def test_a_profile_may_not_take_a_presets_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="other than the presets'"):
        load_profile(str(a_profile_file(tmp_path, name="ninjatrader")), tmp_path / "home")


def test_an_unknown_profile_is_refused_with_the_known_ones(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="databento-csv, ibkr, ninjatrader"):
        load_profile("motivewave", tmp_path / "home")


@pytest.mark.parametrize(
    ("changes", "refusal"),
    [
        ({"timeframe": "ticks"}, "Expected the columns of the ticks"),
        ({"series": "continuous"}, "Expected the instrument of a continuous series"),
        ({"layout": {"delimiter": ";;", "header": True}}, "delimiter"),
        ({"timestamp": {"format": "unix_hours", "time_zone": "UTC"}}, "format"),
        ({"timestamp": {"format": "unix_s", "time_zone": "Chicago"}}, "IANA time zone"),
    ],
)
def test_a_profile_that_cannot_read_a_file_is_refused(
    changes: dict[str, object], refusal: str
) -> None:
    profile = {**preset_profiles()["tradingview"].model_dump(mode="json"), **changes}

    with pytest.raises(ValueError, match=refusal):
        parse_profile(yaml.safe_dump(profile), "a profile")


def test_a_preset_that_leaves_the_time_zone_to_the_import_refuses_an_import_without_one(
    tmp_path: Path,
) -> None:
    request = FileImportRequest(path=IBKR_SAMPLE, profile=preset_profiles()["ibkr"])

    with pytest.raises(ValueError, match="--time-zone America/New_York"):
        preview_file(request, STATIC_TABLE, tmp_path / "cache")


def test_every_preset_round_trips_through_its_yaml() -> None:
    for profile in preset_profiles().values():
        text = yaml.safe_dump(profile.model_dump(mode="json"))
        assert ImportProfile.model_validate(yaml.safe_load(text)) == profile


@pytest.mark.parametrize(
    ("pattern", "refusal"),
    [
        ("(?P<root>[A-Z]+)(?P<year>[0-9]{2})", "the group contract, or root and year with month"),
        ("(?P<root>[A-Z]+", "a regular expression"),
    ],
)
def test_a_file_name_pattern_that_finds_no_contract_is_refused(
    tmp_path: Path, pattern: str, refusal: str
) -> None:
    path = a_profile_file(tmp_path, contract_in_file_name=pattern)

    with pytest.raises(ValueError, match=refusal):
        load_profile(str(path), tmp_path / "home")


def test_a_timestamp_format_polars_cannot_read_is_refused_when_the_profile_is_read() -> None:
    # A pattern Polars refuses would fail inside the import with Polars' own error; the
    # profile says what was expected when it is parsed instead.
    fields = preset_profiles()["ninjatrader"].model_dump(mode="json")
    fields["timestamp"]["format"] = "%Q %H"

    with pytest.raises(ValueError, match="strptime pattern Polars reads"):
        ImportProfile.model_validate(fields)
