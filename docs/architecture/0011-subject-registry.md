# ADR 0011: Add an additive character Subject Registry

## Status

Accepted for backend Phase 1 on 2026-07-18.

## Context

The existing `characters` table stores a character card and its aliases in one JSON field.
Identity review can merge a short-name card into a full-name card, but downstream context
code has no stable, normalized identity boundary that later `View` and `Time` records can
reference. Replacing every character foreign key in one migration would make rollback risky
and mix the Subject Registry change with the later Context Compiler work.

## Decision

Schema v12 adds two normalized tables:

- `subjects`: stable identity, type, canonical name, activity state, and timestamps;
- `subject_aliases`: one alias row with its source identifier and confirmation state.

Phase 1 supports only `CHARACTER`. Existing character IDs are reused as subject IDs, so no
current event, Brief, or memory foreign key needs rewriting. Migration v12 backfills every
character and marks an already-merged source subject inactive.

For this compatibility phase, `characters.profile` remains the character-card detail model,
while Subject Registry is the sole runtime source for canonical names, aliases, and activity.
The legacy `characters.canonical_name` and `characters.aliases_json` columns remain write-only
compatibility mirrors. The following writes update both models in the same SQLite transaction:

- creating a character creates its subject and confirmed alias rows;
- applying a user-confirmed identity merge deactivates the source subject and adds its names to
  the target with source provenance;
- undo reactivates the source and removes only aliases contributed by that merge source.

Agent identity proposals resolve names through the Registry, but remain review-only. Neither a
model response nor an Agent tool call can directly merge subjects.

## Data and failure boundaries

- All SQL values are parameterized.
- Empty names, invalid booleans, duplicate aliases per subject, and unsupported subject types are
  rejected by schema constraints or domain validation.
- Legacy alias JSON is treated as untrusted migration input. A malformed non-string-list payload
  aborts the entire migration; Schema v11 and user data remain unchanged for a safe retry.
- The migration is additive. It does not edit manuscript files, model settings, or existing
  character/event identifiers.

## Consequences

- Phase 2 records can reference a stable `subject_id` without depending on display names.
- Existing UI and memory code continue to work while later tickets move reads to the Registry.
- Direct edits to the legacy name and alias mirror cannot override runtime identity. Direct edits
  to the authoritative Subject Registry remain unsupported and are detected before merge Undo.
- Location, organization, item, ability, event, and concept subjects remain deferred.
- There is no destructive down migration. Recovery uses the existing atomic migration rollback
  and verified project backup workflow.
