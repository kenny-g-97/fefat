"""The specifications of the products a trader brings that FEFAT does not know (step 1.10,
`02-engine-and-data.md` §1.8): an import profile that names a new instrument saves it once, as
`<FEFAT_DATA_DIR>/instruments/<root>.json`, beside the data it describes, and every reader of
the store looks a root up in the static table and these files together.

    table = instrument_table(Store(paths.data_dir).folder)
    table.get("FDAX").session_calendar()
"""

from pathlib import Path

from pydantic import ValidationError

from fefat.market.instruments import STATIC_TABLE, Instrument, InstrumentTable
from fefat.market.layout import INSTRUMENTS_FOLDER_NAME
from fefat.market.store_files import write_atomically


def instrument_table(data_dir: Path) -> InstrumentTable:
    """The static table and the instruments saved in `data_dir`; a saved file that holds no
    instrument, or another root than its name, is refused with its path."""
    folder = data_dir / INSTRUMENTS_FOLDER_NAME
    if not folder.is_dir():
        return STATIC_TABLE
    saved = tuple(_saved(path) for path in sorted(folder.glob("*.json")))
    return InstrumentTable(versions=(*STATIC_TABLE.versions, *saved))


def save_instrument(data_dir: Path, instrument: Instrument) -> bool:
    """Save a new product's specification in `data_dir`: True when it was written, False when
    it is saved already as it is. A root of the static table is refused, since its
    specification is FEFAT's, and so is a second, different specification of a saved root."""
    if instrument.root in STATIC_TABLE.roots():
        raise ValueError(
            f"Expected a new product, got {instrument.root}, an instrument FEAT knows: name it "
            "in the profile as `instrument: <root>` instead of giving its specification."
        )
    path = data_dir / INSTRUMENTS_FOLDER_NAME / f"{instrument.root}.json"
    if path.is_file():
        saved = _saved(path)
        if saved != instrument:
            raise ValueError(
                f"Expected the specification of {instrument.root} saved in {path}, got another: "
                "a product keeps the specification its first import saved."
            )
        return False
    content = instrument.model_dump_json(indent=2).encode() + b"\n"
    write_atomically(path, lambda temporary: temporary.write_bytes(content))
    return True


def _saved(path: Path) -> Instrument:
    try:
        instrument = Instrument.model_validate_json(path.read_bytes())
    except ValidationError as error:
        raise ValueError(f"Expected {path} to hold an instrument, got: {error}") from error
    if path.stem != instrument.root:
        raise ValueError(
            f"Expected {path} to hold the instrument {path.stem}, got {instrument.root}."
        )
    return instrument
