# ADR 0015: Compile reviewed view assertions into production prose context

## Status

Accepted for backend Phase 3 on 2026-07-19.

## Context

ADR 0014 introduced deterministic context eligibility and hard filtering, but production prose
generation did not yet create blocks from persisted `view_assertions`. The existing
`list_visible_at` query is intentionally safe, but using only its successful rows would hide
why a candidate was excluded from the Context Manifest.

## Decision

The application layer now recalls bounded view-assertion candidates and projects each record
into a `ContextBlock` with explicit `ContextEligibility`. Candidate content reaches the prose
prompt only after `ContextBuilder` applies revision, time, review, stale, and source-change
gates.

Production prose recall is deliberately narrow:

- `READER_VIEW` candidates are recalled for both BASIC and STANDARD generation;
- `CHARACTER_VIEW` candidates are recalled only when a frozen Brief supplies an explicit POV
  character ID;
- another character's view is not recalled;
- `WORLD_TRUTH` and `AUTHOR_PLAN` are not automatically sent to the prose model.

This follows the non-reveal rule: the existence of a world truth is not permission to expose
it to the Writer. A future projection stage may convert selected hidden causes into explicit
non-revealable behavioral constraints, but it must not bypass this boundary.

The target chapter's narrative sequence is its one-based position in canonical book order.
Both story-valid and narrative-visible intervals must contain that sequence. `APPROVED` and
`LOCKED` records are authority-eligible; an approved model candidate remains
`MODEL_EXTRACTED` provenance but may enter context because a user reviewed it. `REVIEW` and
`REJECTED` records remain excluded.

When an assertion identifies a chapter as its source, the provider compares its saved source
revision with the current chapter revision and records the current chapter hash in the
manifest dependency. Existing `stale` and `source_changed` transitions keep their more
specific exclusion reasons; an otherwise unflagged mismatch is `REVISION_INVALID`.

Candidate recall is bounded to 250 rows per requested view. Unsafe candidate text remains an
in-memory block only until deterministic filtering; it is never concatenated into model
messages. The Manifest records the block metadata and exclusion reason, not its content.

Legacy reader-knowledge summaries remain a compatibility projection because old knowledge
items do not contain enough subject semantics for a safe automatic rewrite. A reviewed,
currently eligible `READER_VIEW` replaces one legacy reader event only when its `source_id`
exactly equals that event ID. The prose projection removes only that linked event from the
legacy summary. Pending, rejected, stale, source-changed, future, expired, or unlinked
assertions never suppress legacy data. This is a read-time convergence rule: it does not delete
or reinterpret old rows, and it avoids treating text similarity as identity.
The application service exposes a user-confirmed conversion operation that verifies project
ownership, reader scope, review state, active knowledge state, and replacement uniqueness before
creating this provenance link.

## Consequences

- No schema migration, UI change, model call, or manuscript rewrite is required.
- Existing `ViewAssertionService.list_for_context` behavior remains unchanged for other
  callers.
- BASIC generation has no character POV knowledge unless a future explicit BASIC-mode POV
  input is introduced; it still receives eligible reader-view boundaries.
- Conflict detection and conversion of hidden causality into non-revealable constraints remain
  separate Context Compiler tickets.
- Explicit provenance can move individual reader facts onto `READER_VIEW` without creating a
  second context chain or losing unrelated legacy reader knowledge.
