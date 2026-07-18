# ADR 0019: Guarantee a minimum recent-continuity block before budget competition

## Status

Accepted for backend Phase 3 on 2026-07-19.

## Context

Required context already has whole-block protection: system rules, project guidance, the current
chapter requirement, a frozen Brief, and manual Pins either fit in full or preparation fails.
Optional context was different. After filtering, task ranking, and deduplication, every optional
block entered one greedy Token-budget queue.

That queue can correctly prefer task-matching memory, but under pressure it could consume the
remaining budget before any recent prose was selected. Prose generation would then lose direct
scene continuity even when a previous chapter was available. The backend plan requires a minimum
recent high-fidelity window, followed by dynamic competition, without turning experimental
percentages into permanent product rules.

## Decision

`ContextBuildRequest.minimum_category_coverage` explicitly lists optional categories that need
one selected representation before the remaining optional blocks compete for budget.

The compiler order is now:

1. hard-filter ineligible blocks;
2. separate and validate required whole blocks;
3. task-rank and optionally deduplicate optional blocks;
4. select the highest-ranked fitting block for each guaranteed category;
5. let every remaining optional block compete in ranked order.

A guaranteed block remains whole whenever it fits. If its full representation does not fit, the
existing whole fallback representation may satisfy the guarantee. If candidates exist but neither
full nor fallback content fits, the Context Manifest records
`BUDGET_GUARANTEE_UNMET:<category>`. An absent category produces no warning, so the first chapter
does not report a false failure.

Production prose generation currently requests one `RECENT_FULL` category guarantee. It does not
reserve a fixed Token count or percentage. Required blocks and manual Pins keep their stronger
existing semantics, while character state, canon, active threads, style, and historical evidence
continue to compete dynamically for the remaining budget.

The v6 deterministic baseline adds a pressure case where lexical task relevance would otherwise
fill the budget with a long memory block before recent continuity. The guaranteed recent block is
selected instead:

| Metric | v6 result |
| --- | ---: |
| Matched scenarios | 10 / 10 |
| Forbidden selections | 0 |
| Average recall | 1.00 |
| Average precision | 1.00 |

Run it with:

```powershell
python -m scripts.run_backend_baseline tests/fixtures/backend_baseline_v6.json
```

## Consequences

- No schema, UI, model-provider, manuscript, or stored-memory changes are required.
- Recent continuity cannot be displaced solely because another optional block has a stronger
  lexical task match.
- Budget pressure remains auditable through selected fallbacks, omissions, and explicit warnings.
- This ticket guarantees category presence, not a percentage or multiple-block quota. Additional
  floors must be justified by benchmark evidence rather than inferred from the planning example.
