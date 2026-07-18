# ADR 0014: Hard-filter context before ranking and token budgeting

## Status

Accepted for backend Phase 3 on 2026-07-18.

## Context

The Phase 0 context baseline proved that static priority and token budgeting can select
information that the current narration must not see. Budget exhaustion happened to exclude
one future-prose candidate, but a hidden world truth and an unrevealed clue still reached the
compiled context. A safety boundary must not depend on candidate size or ranking order.

## Decision

Each `ContextBlock` carries a deterministic `ContextEligibility` value. Before required-block
checks, ranking, fallback, or token budgeting, `ContextBuilder` excludes blocks that fail any
of these gates:

- project scope;
- source revision validity;
- narrative time or reveal boundary;
- current POV or reader-view boundary;
- stale, source-changed, or conflicted state;
- authority or review eligibility.

An excluded block is retained in the `ContextManifest` with a stable
`HARD_FILTER:<REASON_CODE>` reason. Even a required block cannot bypass these safety gates.
Eligibility defaults to allowed/current for compatibility with existing producers; producers
must derive explicit restrictions from authoritative records rather than category names or
model prose.

The immutable Phase 0 fixture remains `backend_baseline_v1.json`. A new v2 fixture supplies
explicit eligibility metadata and shows the Phase 3 boundary change without rewriting the
old result:

```powershell
python -m scripts.run_backend_baseline tests/fixtures/backend_baseline_v2.json
```

In v2, forbidden selections fall from two to zero, relevant recall stays unchanged, and
precision improves because a stale state is also removed.

## Boundaries and follow-up

- No database, migration, UI, model call, or user manuscript changes are part of this ticket.
- The hard filter consumes decisions; it does not infer chronology, identity, or knowledge.
- Mapping persisted `view_assertions`, source revisions, and authority states into
  `ContextEligibility` is a separate application-layer ticket.
- Retrieval scoring, deduplication, reranking, compression, and advanced budget projection
  remain later Context Compiler 2.0 stages.
