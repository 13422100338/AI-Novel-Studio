# ADR 0023: Build imported-novel semantics in manuscript order before Subject projection

## Status

Accepted for the supplemental backend plan on 2026-08-11.

## Context

An existing novel may mention several Subjects in the same scene. Building each character profile by
searching that Subject's name and sending the matching manuscript passages to a model independently
would have two structural defects:

- retrieval relevance order is not narrative order;
- shared scenes are reread once per Subject, so import cost trends toward
  `O(Manuscript × Subjects)` instead of `O(Manuscript)`.

The current backend already has important parts of the correct foundation:

- `ChapterRepository` owns canonical volume/chapter order and exact chapter revisions;
- ADR 0022 defines exact Unicode code-point source ranges and revision-aware Formal Manuscript
  chunks;
- `ChapterRevisionService` maintains those derived chunks locally after revisions;
- `ManuscriptMemoryBuildService` invokes its analyzer once per chapter, not once per Subject;
- R3a can hydrate explicit candidate document IDs back to exact, current, pre-target manuscript
  evidence.

However, retrieval chunks are not scene semantics, and the backend does not yet have shared
Occurrence/Participant Link persistence, a Subject History facade, scene-semantic lifecycle state,
or character-profile aggregation over structured history. The existing chapter analyzer also used a
newline-normalizing read after validating the exact source, which could detach derived candidates
from the canonical snapshot on CRLF manuscripts.

## Decision

### Manuscript-centered first understanding

The first semantic understanding of an imported novel follows canonical manuscript order:

```text
Formal Manuscript
-> volume/chapter narrative order
-> scene or bounded semantic window
-> shared semantic candidates
-> shared narrative memory
-> Subject projections and profiles
```

A Subject name search is an evidence lookup, not a history builder. The import pipeline must not
create one full-manuscript or full-scene evidence request per Subject. Shared source material is read
once by the principal semantic pass and later projected through links.

### Exact source identity before derived writes

Every semantic input is the exact UTF-8-decoded canonical chapter string, preserving its line
endings. Before any model-derived bundle is persisted, the application boundary requires an exact
match on:

- `source_chapter_id`;
- `source_revision`;
- SHA-256 `source_hash` of that exact decoded string.

A mismatch rejects the whole model bundle. It may fall back to the existing deterministic chapter
placeholder summary, but it must not create Character State, Canon, Clue, Knowledge, View,
Occurrence, or other model-derived records from the mismatched bundle. Model output remains
untrusted and REVIEW-only.

This identity check does not replace revision invalidation or the later pre-persistence source-race
gate. It is the minimum boundary that prevents an analyzer or adapter from attaching results to a
different snapshot.

### Retrieval chunks are not semantic windows

`paragraph-codepoint-v1` Formal Manuscript chunks remain a derived retrieval projection. Their
1,600/200 code-point policy must not silently become the semantic Scene contract.

A later semantic-window ticket will define an independent, versioned, deterministic DTO with exact
half-open source spans and narrative coordinates. It should prefer chapter and detectable scene
boundaries, then paragraph clusters, with a bounded overlapping window only as a fallback. That
ticket must not add a second Formal Manuscript store, retriever, vector cache, or Context Compiler.

### Shared semantic result and truth boundaries

A later shared semantic pass may emit one validated candidate envelope containing Subject mentions,
alias candidates, shared Occurrence candidates, Participant Links, real State changes, sparse View
differences, relationship candidates, narrative-control candidates, and a scene/chapter summary
candidate.

The envelope is not an authority source:

- Formal Manuscript remains the sole content authority;
- one shared event becomes one Occurrence with many Participant Links;
- real per-Subject changes remain State Events;
- epistemic differences remain sparse View Assertions;
- summaries and character profiles remain derived projections;
- no normal participation matrix is copied into View Assertions.

Occurrence, Participant Link, Subject History, and their schema remain separately reviewed work.
This ADR does not authorize those tables or overload existing Character State, Knowledge, Clue,
View, SearchDocument participant hints, or chapter briefs as shared event truth.

### Narrative order and story time remain separate

Narrative coordinates describe when the reader encounters a source unit. Story time describes when
the event happens in the fictional world and may be unknown, partial, or relative. Retrieval score
must never replace either ordering.

Chapter summaries consume chapter material in narrative order and must cover the complete chapter
processing chain. A relevance Top-K alone cannot be called a chapter summary. Summaries must retain
epistemic qualifiers such as announced, believed, suspected, or misunderstood rather than flattening
them into world truth.

### Initial import and incremental revision are different cost models

The initial import may perform a bounded sequential semantic pass over the manuscript. Later chapter
creation or revision processes only the changed chapter and directly dependent derived records.
Editing an old chapter marks revision-bound dependents stale and rebuilds locally; it does not
rescan the whole novel.

Embedding/FTS indexing cost is tracked separately from chat/reasoning model input. Future import-run
telemetry should distinguish manuscript, semantic-pass, summary, profile-aggregation, review, and
embedding usage so repeated semantic reading is measurable.

## Implementation sequence

The remaining work is split into independently reviewed tickets:

1. exact shared-import source guard (this ADR's first code increment);
2. scene/semantic-window DTO and exact source spans;
3. validated shared semantic result DTO;
4. Occurrence and Participant Link dedup/upsert;
5. State/View/Relationship candidate binding;
6. full-coverage epistemic-safe chapter summary;
7. ordered Subject History projection;
8. character-profile candidate aggregation from structured history plus selected evidence;
9. per-derived-type import lifecycle and cost telemetry;
10. chapter-local incremental semantic maintenance.

Each ticket must preserve current user data, avoid eager backfills in schema migrations, and stop at
its own review boundary.

## Consequences

- The existing chapter-centered analyzer direction is retained and made exact-source-safe.
- Existing retrieval, Context Compiler, model gateway, and revision-maintenance paths are reused.
- Character profiles cannot be implemented as `RAG(character_name)` over the whole manuscript.
- Some deliberate rereading remains acceptable for bounded overlap, complete chapter summaries, or
  selected exact evidence; repetition proportional to Subject count is not.
- Main Agent, subagents, AgentRun, tool loops, Writer runtime, ModelRequestManifest, and frontend
  Agent UI are outside this import-domain decision.

## Alternatives rejected

### Build every character independently from name-based RAG

Rejected because relevance order is not a timeline and shared scenes are multiplied by Subject
count.

### Treat Formal retrieval chunks as persisted scenes

Rejected because retrieval sizing and semantic scene identity have different purposes and revision
lifecycles.

### Add a new vector store or semantic truth repository

Rejected because ADR 0022 already defines the Formal evidence path, while shared event truth belongs
to the separately reviewed Occurrence contract.

### Start with multi-agent import orchestration

Rejected because agents are execution harnesses, not novel-domain authority, and would hide repeated
reading before deterministic boundaries and lifecycle state exist.
