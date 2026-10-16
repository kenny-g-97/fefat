"""Market data: the canonical store, its schemas, and its layout (ADR-0019); instrument
specifications, contract identity, and fee tables; session calendars and trade dates; the
quality report of each dataset; the data API, `load` and `catalog` (`fefat.market.api`); and
the know-how FEFAT ships instead of data (D-37), the product catalog (`CATALOG`,
`fefat.market.catalog`) and the source guide (`SOURCE_GUIDE`, `fefat.market.sources`)."""

from fefat.market.api import CATALOG_COLUMNS, SIGNAL_BAR_COLUMNS, Fidelity, catalog, load
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
from fefat.market.store import Store

__all__ = [
    "CATALOG",
    "CATALOG_COLUMNS",
    "SIGNAL_BAR_COLUMNS",
    "SOURCE_GUIDE",
    "BatchJob",
    "Calendar",
    "CalendarId",
    "CalendarReport",
    "Contract",
    "ContractResolver",
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
    "Weekday",
    "YearMonth",
    "assess_quality",
    "catalog",
    "is_outright",
    "load",
    "parse_schema_name",
    "polars_schema",
    "sessions_of",
    "validate_calendar",
    "write_quality_report",
]
