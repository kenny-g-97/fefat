"""Importers: the trader's files into the canonical store (`02-engine-and-data.md` §1.8).

`databento` imports Databento's batch downloads and DBN files, decoded by `dbn` and written as
partitions by `canonical`; `report` is what an import tells the trader. Importers write only
through `fefat.market.store.Store` (ADR-0019) and read no network (D-38).
"""
