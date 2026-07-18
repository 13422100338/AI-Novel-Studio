# ADR 0016: Rerank optional context by deterministic task relevance

## Status

Accepted for backend Phase 3 on 2026-07-19.

## Context

The v2 hard-filter baseline removed forbidden candidates, but one scenario still demonstrated
that static source priority is not task relevance. A large, high-priority irrelevant canon
block could consume the remaining input budget before a smaller relevant evidence block was
considered.

## Decision

`ContextBuildRequest` may now carry a bounded `ContextTask` containing the task type and the
current task query. Prose generation supplies `PROSE_GENERATION` and the current chapter
requirement. After hard filtering and required-block separation, `ContextRanker` orders only
optional blocks by deterministic lexical overlap with that query. Static priority and block ID
remain tie-breakers.

The first lexical implementation uses normalized ASCII words and Chinese two-character terms.
It records up to eight matched terms in the selected Manifest rationale as
`TASK_RELEVANCE:<terms>`. Ranking examines at most 20,000 query characters and 50,000
characters per candidate. It matches candidate content rather than producer rationale, so
generic diagnostic wording cannot inflate relevance. An oversized user requirement is
truncated only for ranking; the original requirement block and prose prompt remain unchanged.

Hard safety and author intent keep precedence:

- project, revision, time, view, authority, stale, and conflict filters run before ranking;
- required blocks and manual Pins retain their existing deterministic order and cannot be
  displaced by lexical score;
- candidates with equal match counts retain static-priority ordering;
- no model call or probabilistic score decides inclusion.

The immutable v1 and v2 baselines remain available. `backend_baseline_v3.json` adds task text
and bounded synthetic ranking text to the existing priority-versus-relevance scenario. Under
the same Token budget, the relevant evidence now replaces the high-priority noise:

| Metric | v2 hard filter | v3 task rerank |
| --- | ---: | ---: |
| Forbidden selections | 0 | 0 |
| Average recall | 0.95 | 1.00 |
| Average precision | 0.8833 | 0.9333 |

Run the new comparison fixture with:

```powershell
python -m scripts.run_backend_baseline tests/fixtures/backend_baseline_v3.json
```

## Consequences

- No schema, UI, model-provider, or manuscript changes are required.
- This is a transparent first reranker, not BM25, Embedding, semantic retrieval, or a learned
  relevance formula.
- Exact lexical overlap can miss synonyms and may match common phrases. Hybrid retrieval,
  deduplication, and richer task/category signals remain separate Phase 3 tickets.
