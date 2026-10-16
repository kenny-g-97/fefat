import pytest

from fefat.market.sources import SOURCE_GUIDE, DesktopUse, PresetStatus, parse_source_guide

ONE_SOURCE = """\
researched_on: 2026-10-12
sources:
  - id: databento
    name: "Databento"
    kind: vendor
    offers: "Every CME contract since 2010-06-06."
    cost: "Standard plan $199 a month."
    terms: "Internal purposes of the customer only."
    terms_url: "https://databento.com/legal/databento-user-agreement"
    desktop_use: check-the-terms
    desktop_use_note: "No clause forbids your own key in software on your own machine."
    licence_scope: "Internal use by the account holder; no redistribution"
    presets:
      - id: databento
        name: "Databento DBN batch download"
        reads: "DBN files with their sidecars."
        status: available
"""
CRYPTO_SOURCES = {
    "binance-vision",
    "bybit",
    "okx",
    "kraken",
    "coinbase",
    "hyperliquid",
    "tardis",
    "coinapi",
    "kaiko",
}


def test_the_guide_names_databento_first_with_the_presets_that_read_its_files() -> None:
    databento = SOURCE_GUIDE.sources[0]

    assert databento.name == "Databento"
    assert [(preset.id, preset.status) for preset in databento.presets] == [
        ("databento", PresetStatus.AVAILABLE),
        ("databento-csv", PresetStatus.PLANNED),
    ]


def test_the_guide_holds_the_importer_of_step_1_6_and_the_presets_planned_for_1_10() -> None:
    sources_of_presets = {
        preset.id: source.id for source in SOURCE_GUIDE.sources for preset in source.presets
    }

    assert sources_of_presets == {
        "databento": "databento",
        "databento-csv": "databento",
        "ibkr": "interactive-brokers",
        "binance-vision": "binance-vision",
        "ninjatrader": "ninjatrader",
        "tradingview": "tradingview",
        "sierra-chart": "sierra-chart",
        "tradestation": "tradestation",
    }


def test_the_guide_names_binance_vision_first_among_the_crypto_sources() -> None:
    crypto = [source.id for source in SOURCE_GUIDE.sources if source.id in CRYPTO_SOURCES]

    assert crypto[0] == "binance-vision"


def test_no_source_reads_as_confirmed_before_it_confirms_in_writing() -> None:
    # ADR-0018: a source without a written confirmation reads "check the terms yourself".
    verdicts = {source.desktop_use for source in SOURCE_GUIDE.sources}

    assert DesktopUse.CONFIRMED not in verdicts
    assert DesktopUse.CHECK_THE_TERMS.verdict() == "check the terms yourself"


def test_a_preset_names_the_source_whose_files_it_reads() -> None:
    assert SOURCE_GUIDE.source_of_preset("databento-csv").id == "databento"
    assert SOURCE_GUIDE.source("ninjatrader").presets[0].id == "ninjatrader"


def test_an_unknown_source_or_preset_is_refused() -> None:
    with pytest.raises(
        ValueError, match=r"Expected a source of the guide \(databento, .*\), got 'x'"
    ):
        SOURCE_GUIDE.source("x")
    with pytest.raises(
        ValueError, match=r"Expected a preset of the guide \(databento, .*\), got 'synthetic'"
    ):
        SOURCE_GUIDE.source_of_preset("synthetic")


def test_a_guide_that_names_a_source_or_preset_twice_is_refused() -> None:
    twice = ONE_SOURCE + ONE_SOURCE.split("sources:\n", 1)[1]

    with pytest.raises(
        ValueError,
        match="Expected each source and each preset named once, got the source databento and "
        "the preset databento more than once",
    ):
        parse_source_guide(twice)


@pytest.mark.parametrize(
    ("change", "refusal"),
    [
        (("check-the-terms", "probably-fine"), "Input should be 'confirmed', 'check-the-terms'"),
        (('cost: "Standard plan $199 a month."', "cost: yes"), "Input should be a valid string"),
        (("https://databento.com", "http://databento.com"), "should match pattern"),
        (("status: available", "status: soon"), "Input should be 'available' or 'planned'"),
        (("    licence_scope:", "    licence:"), "Field required"),
    ],
)
def test_a_guide_entry_outside_its_schema_is_refused(change: tuple[str, str], refusal: str) -> None:
    with pytest.raises(ValueError, match=refusal):
        parse_source_guide(ONE_SOURCE.replace(*change))


def test_a_guide_written_as_its_schema_is_read() -> None:
    guide = parse_source_guide(ONE_SOURCE)

    assert guide.source_of_preset("databento").licence_scope == (
        "Internal use by the account holder; no redistribution"
    )
