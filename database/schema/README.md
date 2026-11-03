# Canonical PostgreSQL schema

Export only from a dedicated migrated PostgreSQL18 TEST database. Do not export rows.
CI `verify.sh` produces `artifacts/schema/schema.sql` with native pg_dump and a
structural snapshot (columns/types/null/defaults, PK/FK/unique/check/indexes,
views, sequences, extensions, revision, aggregate row counts). Never compare
only Alembic version numbers. Compare snapshot.structure and fingerprint;
counts/revision are separate invariants and environment database name is excluded.

Normalize dump solely through `python3 scripts/ci/normalize_ddl.py < schema.sql`.
Version comments/random restrict keys are metadata; all SQL objects remain intact.
The canonical SQL and structural snapshot will be committed after TEST generation.
