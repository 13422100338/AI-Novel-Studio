# ADR 0013: Separate migration execution from historical schema definitions

## Status

Accepted before backend Phase 3 on 2026-07-18.

## Context

The original `migration_manager.py` accumulated transaction orchestration and every schema
migration from v1 through v15 in one file. It reached 974 lines, made the failure boundary harder
to review, and guaranteed that every later backend phase would keep enlarging a central module.
The public imports are already used by repositories and migration tests, including a few
historical migration helpers used to construct legacy databases.

## Decision

Migration responsibilities are separated without changing schema behavior:

- `migration_manager.py` owns transaction start, version checks, migration ordering, version
  recording, and the existing compatibility exports;
- `schema_migrations.py` is the small registry that exposes the latest version and combined
  migration map;
- `schema_migrations_v1_to_v15.py` is the frozen historical definition set.

Future migrations start in a new versioned definition module and are composed in the registry.
Existing call sites continue importing `MigrationManager`, `MIGRATIONS`, and
`LATEST_SCHEMA_VERSION` from `migration_manager.py`. The `_migration_1` through `_migration_4`
compatibility exports remain available for tests that construct historical schemas.

## Consequences

- Migration execution and atomic rollback behavior are unchanged.
- Historical v1-v15 SQL is moved, not rewritten.
- New schema phases no longer enlarge the executor or modify the frozen historical module.
- The registry becomes the single place that must reject duplicate or missing future versions;
  such validation should be added with the first post-v15 migration.
