# ADR 0021: Store memory embeddings as a replaceable derived cache

## Status

Accepted for backend Phase 3 on 2026-07-19.

## Context

ADR 0020 added an optional Embedding recall boundary to the existing `HistoryRetriever` and
`SearchRepository` path. The project still needs durable vectors so it does not regenerate every
memory embedding on each launch. Those vectors must not become a second source of story truth or
survive after their source text changes.

The application uses embedded SQLite and has no required vector extension. The first storage
version must remain portable across existing Windows installations, preserve v1-v15 migrations,
and roll back atomically if project opening is interrupted.

## Decision

Schema v16 adds `memory_embeddings` as a child cache of `memory_documents`:

- `(document_id, model_id)` is the primary key, allowing a controlled model transition without
  overwriting another model's cache row;
- `dimensions` and bounded `vector_json` describe the stored vector without adding a native vector
  extension dependency;
- `content_hash` binds the vector to the exact embedding input;
- `status` is either `CURRENT` or `STALE`;
- deleting an authoritative memory document cascades only to its derived vectors;
- `memory_embeddings_rebuild` supports model/status scans for later rebuild jobs.

The table is empty after migration. Schema v16 does not generate vectors, call a model, reinterpret
old facts, or alter `memory_documents`. `SearchRepository` owns the derived-cache operations and
uses the canonical embedding input `title.strip() + "\n\n" + content.strip()` with a SHA-256 hash:

- vector elements, dimensions, model IDs, serialized size, and stored rows are validated at the
  repository boundary;
- saving requires the caller's expected source hash and rechecks the authoritative document inside
  a `BEGIN IMMEDIATE` transaction, so a vector cannot be attached after its source changes;
- updating a memory document marks every mismatched model row stale in the same transaction, while
  changing the document itself to `STALE` invalidates all its vectors;
- chapter-revision invalidation extends the existing SEARCH dependency path and marks the affected
  document vectors stale without introducing another dependency graph;
- rebuild scans return only current, approved or locked memory documents whose requested model row
  is missing or stale.

The repository does not generate embeddings, call a provider, or perform cosine retrieval. Those
remain separate application/provider responsibilities behind the existing Embedding recall
boundary.

The new migration lives in `schema_migrations_v16.py`; v1-v15 remains frozen. The registry now
rejects duplicate and missing versions when modules are composed. Migration execution continues to
use the existing single `BEGIN IMMEDIATE` transaction. Failure therefore restores schema version
15, removes partially created v16 objects, and preserves existing memory rows; reopening can retry
the real migration.

## Consequences

- Existing projects receive one additive empty cache table and no manuscript or semantic changes.
- Stored JSON is portable and dependency-free, but cosine search will run in validated application
  code until benchmark evidence justifies a native vector extension.
- Vectors are explicitly disposable derived data; `memory_documents` remains authoritative.
- Downgrade-in-place is not introduced. Recovery uses the existing backup path or transaction
  rollback on failed migration, rather than destructive reverse migrations.
- Persistence, source-race protection, invalidation, and bounded rebuild discovery are now enabled;
  provider/API wiring and vector similarity retrieval remain disabled until later tickets.
