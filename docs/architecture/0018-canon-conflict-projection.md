# ADR 0018: Exclude explicit canon conflicts from Writer context

## Status

Accepted for backend Phase 3 on 2026-07-19.

## Context

The existing canon-card service already detects a narrow, deterministic conflict: records with
the same title and the same highest authority but different details. It correctly refuses to
choose a winner, but the prose-generation provider rendered both alternatives inside a normal
`CANON_CARD`. A warning inside model text is weaker than preventing uncertain facts from
reaching the Writer.

## Decision

Production prose context now projects each aggregated canon category into two kinds of blocks:

- reviewed, non-conflicting facts remain in a normal `CANON_CARD`;
- each explicit equal-authority conflict becomes a separate `CANON_CONFLICT` block with
  `ContextEligibility.conflicted=True`.

`ContextBuilder` hard-filters the conflict block before ranking, deduplication, or Token budget
allocation. The Context Manifest records `HARD_FILTER:CONFLICTED`, while neither conflicting
detail is concatenated into Writer messages. Non-conflicting facts in the same category remain
available.

This projection changes only prose generation. `CanonCardContextService.content` still renders
conflict alternatives with the existing “冲突待处理，不得作为确定正典” marker, so plot
discussion and review surfaces can show the user what needs resolution. The program neither
changes authority nor edits, deletes, or selects a canon record.

Character-state conflicts already follow a stricter existing boundary:
`CharacterStatusService` raises `MemoryConflictError` when multiple states occupy the same
effective boundary. This ticket does not weaken or duplicate that behavior.

The immutable v1 through v4 fixtures remain available. `backend_baseline_v5.json` marks an
explicit conflicting candidate and verifies the final hard-filter stage:

| Metric | v4 deduplication | v5 conflict projection |
| --- | ---: | ---: |
| Forbidden selections | 0 | 0 |
| Average recall | 1.00 | 1.00 |
| Average precision | 0.9667 | 1.00 |

Run it with:

```powershell
python -m scripts.run_backend_baseline tests/fixtures/backend_baseline_v5.json
```

## Consequences

- No schema, UI, model-provider, or manuscript changes are required.
- Writer context no longer treats explicit canon conflicts as usable truth.
- Plot discussion remains able to present both alternatives for user resolution.
- This ticket does not attempt semantic contradiction detection between differently titled or
  differently scoped natural-language facts. Such candidates require explicit comparable
  scope metadata or a review workflow before deterministic filtering is safe.
