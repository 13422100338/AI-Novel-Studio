# ADR 0022: Extend the existing search cache with revision-aware Formal Manuscript chunks

## Status

Accepted for the supplemental backend plan on 2026-08-09.

## Context

The production history path already uses `SearchRepository`, `HistoryRetriever`, FTS5, and the
replaceable `memory_embeddings` cache described by ADR 0020 and ADR 0021. Formal Manuscript text
is currently indexed as one `CHAPTER` document. Search results therefore contain an FTS snippet or
the first part of the indexed body, not an exact range that can be hydrated against the current
chapter revision.

Gate S0 confirmed that the existing retrieval and context boundaries should evolve rather than be
replaced. It also found two identity gaps:

- `memory_documents` has no source range or chunk-policy identity;
- `memory_embeddings` identifies a vector only by `(document_id, model_id)`, so providers using
  the same model ID can collide and an embedding-input contract change cannot be distinguished.

Formal Manuscript must remain the only正文 authority. Search rows, FTS rows, chunks, and vectors are
derived data that may be invalidated or rebuilt, and must never rewrite manuscript files or chapter
revision metadata.

## Decision

### One existing retrieval path

Reuse `memory_documents`, `memory_fts`, `memory_embeddings`, `SearchRepository`,
`EmbeddingIndexService`, and `HistoryRetriever`. Do not add another retriever, vector database,
search table family, or context compiler.

Formal chunks use the dedicated `FORMAL_MANUSCRIPT` document type. Legacy `CHAPTER` rows remain
readable by existing general-memory callers during the transition, but later Exact Evidence
queries accept only validated current `FORMAL_MANUSCRIPT` rows.

### Range and chunk identity

Source ranges are zero-based, half-open Python Unicode code-point offsets `[start, end)` over the
exact UTF-8-decoded current chapter string. A range is valid only when:

- `0 <= start < end <= len(current_content)`;
- the row's chapter revision and content hash match the current non-deleted chapter;
- slicing the current chapter by the stored range yields the indexed chunk's primary source text.

Chunking is a pure deterministic projection owned above storage. Its policy is explicit and
versioned. Paragraph-aware boundaries, maximum size, and overlap are policy inputs, not permanent
architecture constants. R1a does not freeze attractive numeric defaults.

R1b introduces the initial policy `paragraph-codepoint-v1` with validated, injectable defaults:

- maximum chunk length: 1,600 Unicode code points;
- target overlap: 200 Unicode code points;
- blank-line-separated paragraphs are preferred boundaries;
- an oversized paragraph is split deterministically so every emitted range stays within the
  maximum;
- a whitespace-only chapter produces no Formal chunks;
- every chunk body is the exact source slice for its stored half-open range, including original
  whitespace and line endings.

These values are the first benchmarkable operating defaults, not permanent architectural
constants. Callers may inject another validated size/overlap combination only under a distinct
policy version. Changing the meaning or defaults of an already persisted policy version is
forbidden. Overlap may cross a preferred paragraph boundary when required for deterministic
coverage, but the projection must always make forward progress and must never infer, normalize, or
rewrite manuscript text.

For a given chapter revision and policy version, chunk ordinals are zero-based and deterministic.
The derived `source_id` is stable for that exact `(chapter_id, revision, policy_version, ordinal)`
identity. A later chapter revision creates a different derived identity; it never silently
reinterprets an old row.

### Schema v19 and compatibility

R1a exclusively owns schema v19.

Schema v19 adds nullable range/projection metadata to `memory_documents` so existing rows remain
valid:

- `source_start`;
- `source_end`;
- `chunk_ordinal`;
- `chunk_policy_version`.

Repository validation requires all four values for `FORMAL_MANUSCRIPT` rows and rejects them when
inconsistent. Existing non-Formal rows keep null values and unchanged behavior. The existing
`UNIQUE(document_type, source_id)` constraint remains sufficient because each Formal chunk has a
distinct deterministic source ID.

The migration does not read manuscript files, create chunks, call a model, or backfill historical
rows. Existing projects open with no Formal chunk rows. Migration failure rolls back to v18 using
the existing transactional migration manager.

### Structured embedding cache identity

Embedding cache identity becomes:

`(document_id, provider_id, model_id, embedding_schema_version)`.

`dimensions` remains stored and validated data rather than part of the primary key. The provider
ID comes from the configured model route. The embedding schema version identifies the exact
canonical input/projection contract, independently from the provider's public model ID.

Legacy model-only vectors are disposable derived cache data. Schema v19 recreates the embedding
cache empty under the structured identity instead of guessing a provider or schema version. Source
documents and manuscript data are preserved; later bounded rebuilds repopulate vectors.

Repository and application protocols expose a typed embedding index identity. Query and document
embedding paths must use the same identity, validate dimensions, and fail closed on identity or
source-hash mismatch. Provider failures continue to fail open to lexical/subject recall where the
existing caller permits it.

### Incremental delivery

R1 is split into independently reviewable tickets:

1. **R1a — v19 storage and identity foundation**
   - migration and latest-schema registration;
   - Formal chunk metadata and repository validation;
   - transactional replace/read operations for one chapter revision;
   - structured embedding cache identity and compatibility tests;
   - no production chunk generation or automatic revision maintenance.
2. **R1b — deterministic chunk projection and bounded build**
   - pure versioned chunk policy;
   - `ManuscriptMemoryBuildService` writes current `FORMAL_MANUSCRIPT` chunks through the new
     repository operation while retaining its legacy `CHAPTER` indexing during rollout;
   - FTS and pending embedding rows for current Formal chunks;
   - no automatic save/accept/repair indexing.
3. **R2 — revision-local maintenance**
   - one application revision-impact boundary for manual saves, accepted drafts, repairs, and
     imports;
   - local current-revision chunk replacement and bounded recovery;
   - provider failure never rolls back saved manuscript content.

R1a releases schema ownership before any Occurrence migration begins. O1 must use a later
master-assigned migration number.

## Alternatives considered

### Add a second Formal Evidence search system

Rejected. It would duplicate FTS, vector recall, review/time filters, and context integration while
creating another derived-data ownership boundary.

### Keep whole-chapter rows and infer offsets from snippets

Rejected. FTS snippets and truncated prefixes are not stable source ranges and cannot prove an
exact current-revision quote.

### Encode provider identity into `model_id`

Rejected. It changes the meaning of an existing public model ID, still cannot distinguish an input
schema transition cleanly, and encourages string parsing instead of a typed boundary.

### Preserve legacy vectors by assigning a guessed provider

Rejected. Provider provenance cannot be reconstructed reliably. Rebuilding disposable cache rows
is safer than granting guessed identity to stale vectors.

### Make chunk numbers permanent architecture constants

Rejected. Chunk sizing and overlap require benchmark evidence. Only the deterministic,
policy-versioned boundary is architectural.

## Consequences

- Existing projects migrate without manuscript or semantic backfill.
- v19 intentionally clears only the replaceable embedding cache.
- Formal chunks can be traced to an exact current chapter range and safely rejected after revision.
- General history retrieval remains compatible while Exact Evidence gains a dedicated namespace.
- R1a touches a public persisted cache contract and requires Sol xhigh review plus exclusive schema
  ownership.
- R1b and R2 remain separate so storage correctness is proven before production indexing changes.
- Evidence hydration, `EvidenceSet`, Context/Manifest retrieval trace, Occurrence, sparse View, and
  Subject History remain later tickets.
