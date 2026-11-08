---
paths:
  - "python/**"
  - "scripts/**"
---

# Python rules

From `docs/masterplan/08-code-design.md` §1, §3.1, §3.3, and §6.

- **uv only.** Run Python as `uv run python …` (standard-library scripts: `uv run --no-project python …`); add dependencies with `uv add`, and a new dependency needs an ADR line. Never bare `python` or `pip`.
- **Checks.** ruff (lint and format) and pyright pass: strict for `fefat_app`, standard elsewhere. `just check` also runs the import-linter contracts.
- **Dependency rule.** The SDK (`fefat`) never imports the app (`fefat_app`). `fefat_app.services` never imports FastAPI or SQLAlchemy; routers in `fefat_app.http` hold no business logic.
- **Boundaries.** Frozen Pydantic models at every boundary: API, files, configuration, executor results. Parse and validate there, then trust the types.
- **States.** `StrEnum` and discriminated unions for every state and kind (job status, run origin, proposal status, fidelity, dataset source, strategy kind); never free strings or combinations of optional fields.
- **Ports.** Seams are `typing.Protocol`s in `fefat_app/ports.py`; adapters are built once in `container.py` and injected. No service or function creates an adapter inside itself.
- **Features** (D-12, D-09). Prefix-invariant: as-of joins look backward on `ts_close` (alternative data on `available_at` plus its lag); no `shift(-n)`, backward fills, centred windows, full-sample ranks or normalisation, or aggregates over a session that has not ended; forward-anchored continuous series only; `Label` columns never feed a strategy.
- **Data.** Polars expressions over Python loops; frames are never mutated. Paths through `pathlib`; real data by path under `FEFAT_DATA_DIR`, never a hard-coded folder.
- **Fail fast.** Exceptions carry the expected value, the actual value, and the identifying context (instrument, run id, file name). No fallback chains such as `a or b or "unknown"`; a default exists only where the product defines one, and the run record shows it.
- **Tests.** No network in unit tests; tests run on the synthetic fixtures; Hypothesis for properties. Each acceptance item gets a test that fails without the change.
- **Names.** From the glossary in `00-product-spec.md` §7. Never `data`, `utils`, `helpers`, `common`, `shared`, `misc`, `manager`, `handler`, `processor`, `info`, or `item`; no abbreviations except `pnl`, `atr`, `rsi`, `ema`, `sma`, `wma`, `macd`, `adx`, `di`, `roc`, `obv`, `vwap`, `ohlcv`, `id`, `api`, `http`, `utc`, `csv`, `dbn`, `json`, `sql`.
- **Size.** Functions under about 40 lines, modules under about 400, nesting at most three levels, early returns. The reference engine (`fefat/reference/`) stays readable by a non-programmer and may be longer (D-10).
- **Comments.** Docstrings on public APIs and citations of specs, scenarios, or ADRs; no narrative comments.
- **Scripts.** Files in `scripts/` are small standard-library programs run through uv (`uv run --no-project python …`), except `gen_fixtures.py` (pyarrow and databento-dbn), `strip_notebooks.py` (nbstripout), `golden_backtest.py` (the SDK, step 2.10), `xcheck.py` (the SDK and databento-dbn, step 2.14), `bench.py` (the SDK and `gen_fixtures.py`, step 2.15), `tick_check.py` with `tick_check_report.py` (the SDK and `xcheck.py`, step 2.16), and `dev.py` and `e2e_server.py` (the SDK and the app, step 4.3), which run in the project environment (`uv run python …`); they follow the naming and fail-fast rules and nothing more.
- **Notebooks** are committed without outputs.
