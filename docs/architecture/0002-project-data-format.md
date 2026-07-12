# ADR 0002: Project data format and recovery boundary

## Status

Accepted on 2026-07-02.

## Decision

A V3 project is a portable directory with this durable core:

```text
project/
├── project.json
├── project.sqlite3
├── manuscript/
│   └── volume_<UUID>/chapter_<UUID>.md
├── assets/
├── exports/
├── backups/
└── .ai_pipeline/
    ├── history/
    ├── trash/
    └── migration_reports/
```

`project.json` contains only the format version, stable project ID, and display title. It never
contains a machine-specific absolute path. SQLite owns volume/chapter structure and revision
metadata. UTF-8 Markdown under `manuscript/` is the only canonical chapter content.

## Write and recovery rules

- Canonical Markdown is written to a temporary sibling file, flushed, and atomically replaced.
- Before an existing chapter is replaced, its previous revision is copied to
  `.ai_pipeline/history/` and recorded with a SHA-256 hash.
- Chapter deletion moves content to `.ai_pipeline/trash/`; restoration keeps the same chapter ID.
- Volume deletion requires a different destination volume. Its chapters keep their IDs and are
  moved into the destination volume before the source volume is removed.
- SQLite migrations are ordered, recorded in `schema_migrations`, and safe to call repeatedly.
- A writer lock permits one writing process per project. Lock metadata contains process and time
  information only, never private paths.
- Backup creation uses SQLite's online backup API and stores a coherent database snapshot with
  canonical Markdown and recovery history in a ZIP archive.

## Legacy import boundary

The importer reads legacy `meta.json` and chapter DOCX files without changing them. Preview hashes
are checked again during import. Missing, corrupt, or changed source files are skipped and recorded
in a portable JSON report. Duplicate volume/chapter names are valid because imported records receive
new stable UUIDs.

Legacy global synopsis, character records, and per-chapter AI summaries are preserved inside the
migration report for a later memory-schema migration. The Phase 1 importer does not treat that
unvalidated legacy material as current V3 canon.

## Deferred scope

Phase 1 exposes repositories and migration services, not end-user UI. Project creation/opening,
diagnostics, backups, and migration will be wired into the Phase 2 interface. Model calls and Token
configuration remain Phase 3 concerns.
