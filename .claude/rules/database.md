---
paths:
  - "python/fefat_app/src/fefat_app/database/**"
---

# Database rules (SQLite, SQLAlchemy, Alembic)

From `docs/masterplan/01-architecture.md` §5 and decisions D-11 and D-15.

- **Migrations.** A schema change is a new Alembic migration file. An existing migration is never edited, renamed, or deleted, even before it ships.
- **Batch mode.** Alembic runs in batch mode, because SQLite cannot alter most constraints in place.
- **Insert-only versions.** Versioned rows (`feature_versions`, `strategy_versions`, `runs`, `prop_rule_set_versions`, `prop_strategy_versions`, `agent_transcript`, and the like) are never updated or deleted after creation. A run's row is a submission with its job until its folder is saved, which sets its run key once; from then on it is never updated or deleted (step 5.3, triggers `WHEN OLD.run_key IS NOT NULL`).
- **Identity.** Every id is a UUIDv7 string, and every row carries `created_at`.
- **States.** Status columns hold the values of a `StrEnum`; a state transition is a compare-and-set update.
- **Boundary.** Repositories live here and are reached through ports; services never import SQLAlchemy.
