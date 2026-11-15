"""Importers: the trader's files into the canonical store (`02-engine-and-data.md` §1.8).

`databento` imports Databento's batch downloads and DBN files, decoded by `dbn` and placed by
`canonical`, and `file_import` a trader's own exports through an import profile. Both read a
whole file against what the store holds before they write (`partition_buffers`), merge its
records into the partitions it overlaps (`partition_merge`, ADR-0021), and tell the trader what
the file added (`report`). Importers write only through `fefat.market.store.Store` (ADR-0019)
and read no network (D-38).
"""
