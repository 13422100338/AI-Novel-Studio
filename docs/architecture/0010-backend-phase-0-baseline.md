# ADR 0010: Freeze backend truth boundaries before Subject View Time migration

## Status

Accepted for backend Phase 0 on 2026-07-18.

## Context

The Subject × View × Time and Context Compiler 2.0 roadmap changes how long-form
knowledge is represented and selected. A schema-first rewrite would make it impossible to
show whether the extra structure improves the context that reaches the prose model. Phase 0
therefore freezes the current truth boundaries and establishes an executable baseline before
adding `subjects`, `subject_aliases`, or `view_assertions`.

## Current authority boundaries

Authority is record-scoped, not table-scoped. A model-extracted `REVIEW` row remains an
untrusted candidate even when it lives beside an `APPROVED` or `LOCKED` row.

| Current storage | Phase 0 role | Boundary |
| --- | --- | --- |
| `chapters`, `chapter_versions` | formal manuscript source | Only explicit user acceptance may replace chapter prose. |
| `chapter_requirements`, `project_guidance` | author intent source | Must not be promoted into world truth. |
| `characters` | current character identity registry | Active identity changes remain explicit, audited, and reversible. |
| `character_state_events` | temporal character-state source | Current state is derived from reviewed events before the target chapter. |
| `knowledge_items`, `knowledge_state_events` | character and reader knowledge source | Missing knowledge is `UNKNOWN`, not proof of `UNAWARE`. |
| `canon_entries` | world-fact candidate/source | Authority comparisons apply only inside a comparable semantic scope. |
| `narrative_clues`, `narrative_clue_events` | narrative-control source | Clues, secrets, and reveal actions are not ordinary canon facts. |
| `style_rules`, `style_samples` | author-approved style source | Samples guide retrieval and diagnosis; they are not hard prose quotas. |
| `chapter_context_pins` | explicit inclusion instruction | A manual pin is a selection constraint, not a new truth source. |

## Current derived and audit layers

The following remain rebuildable or audit-only and must not become new truth sources:

- `summary_nodes`, `memory_documents`, and `memory_fts`;
- `context_manifests` and `memory_dependencies`;
- chapter Briefs and their source fingerprints;
- generation runs and checkpoints;
- audit findings, repair proposals, Agent traces, and chat history.

Changing a formal source marks direct derived dependencies stale. It does not silently delete
or demote user-confirmed records.

## Baseline decision

Phase 0 adds a deterministic suite of ten synthetic chapter-context tasks: five `QUICK` and
five `NORMAL`. Each candidate is labelled `RELEVANT`, `IRRELEVANT`, or `FORBIDDEN`; the
existing `ContextBuilder` runs unchanged and produces a report containing:

- selection regression against the frozen current result;
- relevant-context recall and precision;
- forbidden-information selection count;
- estimated input Tokens and budget utilization;
- context compilation latency and unexpected errors.

Run it with:

```powershell
python -m scripts.run_backend_baseline tests/fixtures/backend_baseline_v1.json
```

The first report intentionally preserves current weaknesses. In particular, the final budget
selector cannot remove forbidden or stale candidates after upstream code has admitted them,
and static priority is not task relevance. Phase 2 and Phase 3 must improve these metrics; a
metric change is not accepted merely because the selection output changed.

## Deferred measurements

This first executable slice does not call a paid model and does not fabricate author data.
Actual model latency, provider Token usage, generation failure rate, draft adoption, manual edit
distance, and manual edit time remain explicitly uncovered. A later opt-in Phase 0 slice will
connect run-scoped observations without uploading manuscript text.

## Consequences

- No project schema or user data changes in this ticket.
- Existing migration v7 to v11 and atomic-failure tests remain the schema baseline.
- Phase 1 may add Subject Registry tables only after this suite stays reproducible.
- The legacy persisted `STRICT` value remains compatibility data; it is not reintroduced as a
  third user-visible generation mode.
