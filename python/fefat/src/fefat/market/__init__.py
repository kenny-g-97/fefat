"""Market data: the canonical store, its schemas, and its layout (ADR-0019); instrument
specifications, contract identity, and fee tables; session calendars and trade dates; the
quality report of each dataset; the data API, `load`, `datasets`, and `roll_calendar`
(`fefat.market.api`); and
the know-how FEFAT ships instead of data (D-37), the product catalog (`CATALOG`,
`fefat.market.catalog`) and the source guide (`SOURCE_GUIDE`, `fefat.market.sources`)."""

from fefat.market.api import DATASETS_COLUMNS, SIGNAL_BAR_COLUMNS, datasets, load, roll_calendar
from fefat.market.calendar import Session, SessionTable, sessions_of
from fefat.market.calendar_check import CalendarReport, validate_calendar
from fefat.market.calendar_definition import (
    Calendar,
    CalendarId,
    EarlyClose,
    FormerClose,
    FullClose,
    Halt,
    SessionHours,
    Weekday,
)
from fefat.market.catalog import CATALOG
from fefat.market.contracts import Contract, ContractResolver, IdentitySource, is_outright
from fefat.market.fees import CryptoFee, FeeSchedule, FeeTable, FuturesFee
from fefat.market.fidelity import Fidelity, TickFidelity, parse_fidelity
from fefat.market.instruments import Currency, Instrument, InstrumentKind, InstrumentTable
from fefat.market.layout import (
    Dataset,
    DatasetMetadata,
    DatasetOrigin,
    Partition,
    PartitionRequest,
    SizeUnit,
    YearMonth,
)
from fefat.market.quality import assess_quality
from fefat.market.quality_report import QualityReport, QualityStatus, write_quality_report
from fefat.market.raw_manifest import BatchJob
from fefat.market.schema import parse_schema_name, polars_schema
from fefat.market.snapshot import Snapshot
from fefat.market.sources import SOURCE_GUIDE
from fefat.market.status import CoverageStatus, dataset_status, product_status
from fefat.market.store import Store

__all__ = [
    "CATALOG",
    "DATASETS_COLUMNS",
    "SIGNAL_BAR_COLUMNS",
    "SOURCE_GUIDE",
    "BatchJob",
    "Calendar",
    "CalendarId",
    "CalendarReport",
    "Contract",
    "ContractResolver",
    "CoverageStatus",
    "CryptoFee",
    "Currency",
    "Dataset",
    "DatasetMetadata",
    "DatasetOrigin",
    "EarlyClose",
    "FeeSchedule",
    "FeeTable",
    "Fidelity",
    "FormerClose",
    "FullClose",
    "FuturesFee",
    "Halt",
    "IdentitySource",
    "Instrument",
    "InstrumentKind",
    "InstrumentTable",
    "Partition",
    "PartitionRequest",
    "QualityReport",
    "QualityStatus",
    "Session",
    "SessionHours",
    "SessionTable",
    "SizeUnit",
    "Snapshot",
    "Store",
    "TickFidelity",
    "Weekday",
    "YearMonth",
    "assess_quality",
    "dataset_status",
    "datasets",
    "is_outright",
    "load",
    "parse_fidelity",
    "parse_schema_name",
    "polars_schema",
    "product_status",
    "roll_calendar",
    "sessions_of",
    "validate_calendar",
    "write_quality_report",
]
