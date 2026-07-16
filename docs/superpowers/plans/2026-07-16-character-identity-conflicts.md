# Character Identity Conflicts Implementation Plan

**Goal:** Let users safely resolve duplicate character cards without giving model output direct write access to project memory.

## Ticket 1: Deterministic merge and undo

Add a schema-backed merge audit record and an application service that requires explicit user confirmation. A merge must run in one SQLite transaction, preserve the source card, move character-state events, character-knowledge events, and Brief POV references, and record the exact moved row IDs. Undo must restore only those recorded rows and refuse to overwrite later edits.

Files:

- `src/ai_novel_studio/domain/character_identity.py`
- `src/ai_novel_studio/infrastructure/storage/migration_manager.py`
- `src/ai_novel_studio/infrastructure/storage/character_identity_repository.py`
- `src/ai_novel_studio/infrastructure/storage/character_memory_repository.py`
- `src/ai_novel_studio/application/character_identity_service.py`
- `tests/integration/storage/test_character_identity_schema.py`
- `tests/integration/application/test_character_identity_service.py`
- `docs/architecture/0009-character-identity-resolution.md`

Verification: focused pytest, Ruff, mypy, then the full suite.

## Ticket 2: Trustworthy summary-upgrade state

Distinguish chapter scanning from actual model calls in progress reporting. Mark invalidated `SUMMARY_FALLBACK` records as historical versions, and count only chapters that still require a successful model summary as pending upgrades.

## Ticket 3: Review queue and Agent proposals

Add an identity-conflict queue with evidence comparison and explicit decisions. Agent mode may create a reviewable proposal, but only the deterministic application service may apply a confirmed merge.

Status: completed. The queue shows deterministic and Agent-origin candidates with evidence,
requires explicit canonical-card selection and confirmation, and supports guarded undo. Agent
tool retrieval is optional and defaults off; an executed identity proposal opens the review UI
without modifying project memory.
