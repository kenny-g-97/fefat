"""The cross-check of FEFAT's engine against NautilusTrader and NinjaTrader 8 (step 2.14, `02` §8
item 5, D-59): the Nautilus side of the comparison, the matching of the engines' trades, the
classes every difference falls into, and the report `just xcheck` writes.

The FEFAT side runs in the workspace environment (`scripts/xcheck.py`), which calls this package
through its own environment: `uv run --project python/tests/external python -m fefat_xcheck`.
"""
