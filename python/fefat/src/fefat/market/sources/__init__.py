"""The source guide (`02-engine-and-data.md` §1.8, D-37, D-38): the well-known sources of market
data, each with what it offers, what it costs, the terms a trader accepts for personal use,
whether a desktop app on the trader's machine may use the trader's own account or files, and
the import presets that read its files. FEFAT connects to none of them (D-38): the trader brings
the files, through the Databento importer of step 1.6 or the presets of step 1.10.

The guide is `sources.yaml` beside this module, written from
`docs/masterplan/appendix/research-data-sources.md`, and `fefat data sources` prints it:

    from fefat.market.sources import SOURCE_GUIDE
    SOURCE_GUIDE.source("databento").cost
    SOURCE_GUIDE.source_of_preset("databento").licence_scope
"""

from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Self

import yaml
from pydantic import Field, model_validator

from fefat.market.layout import FolderName
from fefat.market.schema import FrozenModel

GUIDE_FILE_NAME = "sources.yaml"


class SourceKind(StrEnum):
    """What a source is: a data vendor, an exchange's own archive, or a trading platform whose
    exports a preset reads."""

    VENDOR = "vendor"
    EXCHANGE_ARCHIVE = "exchange-archive"
    PLATFORM = "platform"


class DesktopUse(StrEnum):
    """Whether a desktop app on the trader's machine may use the trader's own account or files:
    confirmed by the source in writing (none is yet: the confirmations are a Phase 14 kickoff
    decision, ADR-0018), to be checked against its terms, or forbidden by them."""

    CONFIRMED = "confirmed"
    CHECK_THE_TERMS = "check-the-terms"
    FORBIDDEN = "forbidden"

    def verdict(self) -> str:
        """The verdict as the guide prints it (ADR-0018)."""
        return {
            DesktopUse.CONFIRMED: "confirmed by the source in writing",
            DesktopUse.CHECK_THE_TERMS: "check the terms yourself",
            DesktopUse.FORBIDDEN: "forbidden by its terms",
        }[self]


class PresetStatus(StrEnum):
    """Whether FEFAT reads a preset's files yet: the Databento importer of step 1.6 does, and
    the presets of step 1.10 are planned."""

    AVAILABLE = "available"
    PLANNED = "planned"


class Preset(FrozenModel):
    """A file layout FEFAT imports; its id is the provider its datasets are stored under."""

    id: FolderName
    name: str = Field(min_length=1)
    reads: str = Field(min_length=1)
    status: PresetStatus


class Source(FrozenModel):
    """A source of market data as the guide describes it; `licence_scope` is copied into every
    dataset imported from it."""

    id: FolderName
    name: str = Field(min_length=1)
    kind: SourceKind
    offers: str = Field(min_length=1)
    cost: str = Field(min_length=1)
    terms: str = Field(min_length=1)
    terms_url: str = Field(pattern=r"^https://\S+$")
    desktop_use: DesktopUse
    desktop_use_note: str = Field(min_length=1)
    licence_scope: str = Field(min_length=1)
    presets: tuple[Preset, ...]


class SourceGuide(FrozenModel):
    """Every known source in the order the guide prints them, as read on `researched_on`."""

    researched_on: date
    sources: tuple[Source, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _names_each_source_and_preset_once(self) -> Self:
        sources = [source.id for source in self.sources]
        presets = [preset.id for source in self.sources for preset in source.presets]
        repeated = [
            f"the {kind} {name}"
            for kind, names in (("source", sources), ("preset", presets))
            for name in sorted({name for name in names if names.count(name) > 1})
        ]
        if repeated:
            raise ValueError(
                "Expected each source and each preset named once, got "
                f"{' and '.join(repeated)} more than once."
            )
        return self

    def source(self, source_id: str) -> Source:
        """The source with this id; an unknown id is refused."""
        found = [source for source in self.sources if source.id == source_id]
        if not found:
            known = ", ".join(source.id for source in self.sources)
            raise ValueError(f"Expected a source of the guide ({known}), got {source_id!r}.")
        return found[0]

    def source_of_preset(self, preset_id: str) -> Source:
        """The source whose files the preset reads; an unknown preset is refused."""
        found = [
            source
            for source in self.sources
            if any(preset.id == preset_id for preset in source.presets)
        ]
        if not found:
            known = ", ".join(preset.id for source in self.sources for preset in source.presets)
            raise ValueError(f"Expected a preset of the guide ({known}), got {preset_id!r}.")
        return found[0]


def parse_source_guide(text: str) -> SourceGuide:
    """The source guide written as YAML in `text`, validated."""
    return SourceGuide.model_validate(yaml.safe_load(text))


SOURCE_GUIDE = parse_source_guide(
    Path(__file__).with_name(GUIDE_FILE_NAME).read_text(encoding="utf-8")
)
"""The source guide FEFAT ships, read from `sources.yaml` beside this module."""
