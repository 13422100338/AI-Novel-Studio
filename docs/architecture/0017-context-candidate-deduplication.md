# ADR 0017: Deduplicate ranked optional context before budgeting

## Status

Accepted for backend Phase 3 on 2026-07-19.

## Context

The v3 baseline reached full relevant-source recall, but still selected both a canonical
character card and an identical alias-derived card. Sending the same prompt content twice
wastes Token budget and lowers precision. `GenerationMemoryContextProvider` also performed a
partial silent text deduplication before the Context Manifest existed, which made exclusions
impossible to audit.

## Decision

`ContextBuildRequest` now explicitly enables optional-block deduplication for production prose
generation. Deduplication runs after hard filtering and task relevance ranking, but before
Token budget allocation. Therefore, the highest-ranked copy is retained and lower-ranked
copies cannot consume budget.

Only optional blocks participate. Required blocks and manual Pins retain their exact existing
semantics even when their rendered text is identical. A removed block remains in the Context
Manifest with:

```text
DEDUPLICATED:<kept-block-id>
```

For content up to 50,000 characters, the fingerprint normalizes case and whitespace before
SHA-256 hashing. The fingerprint covers both full content and optional fallback content, so an
otherwise identical block with a distinct summary fallback remains available under a smaller
budget. Larger content uses its exact text to avoid allocating an additional large normalized
copy and to avoid false equivalence after bounded-prefix comparison. The operation is
deterministic and does not call a model.

Automatic candidates are no longer silently deduplicated inside
`GenerationMemoryContextProvider`; its local suppression now only prevents an automatic block
from duplicating the same explicitly pinned source. Production automatic-to-automatic
deduplication belongs to `ContextBuilder`, where the decision is visible in the Manifest.

The immutable v1 through v3 fixtures remain available. `backend_baseline_v4.json` enables
deduplication for the duplicate-character-alias scenario:

| Metric | v3 task rerank | v4 deduplication |
| --- | ---: | ---: |
| Forbidden selections | 0 | 0 |
| Average recall | 1.00 | 1.00 |
| Average precision | 0.9333 | 0.9667 |

Run it with:

```powershell
python -m scripts.run_backend_baseline tests/fixtures/backend_baseline_v4.json
```

## Consequences

- No schema, UI, model-provider, or manuscript changes are required.
- Exact and whitespace/case-equivalent prompt content no longer consumes duplicate budget.
- This ticket does not merge records, delete cards, or infer that differently worded cards
  belong to the same character. Subject-aware semantic consolidation remains a review workflow
  or later retrieval ticket.
- Near-duplicate prose, contradiction detection, and conflict projection remain separate
  Context Compiler stages.
