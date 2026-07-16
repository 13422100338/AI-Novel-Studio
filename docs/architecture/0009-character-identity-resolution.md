# ADR 0009: Character identity resolution is explicit and reversible

## Status

Accepted for the first backend ticket on 2026-07-16.

## Decision

Character identity suggestions are untrusted candidates. A model or Agent may later propose that two cards represent the same person, but it may not apply the decision. The application service requires explicit user confirmation and performs the merge through one deterministic SQLite transaction.

The source card is retained for audit and hidden from normal active-card listings while the merge is applied. Character-state events, character-subject knowledge events, and Brief POV references move to the chosen canonical card. The canonical card receives the source name and aliases; profiles are not automatically combined.

Every merge records the exact event IDs and post-merge Brief revisions and hashes. Undo restores only those recorded references. It refuses to run if the canonical aliases, moved references, or affected Briefs changed after the merge, so newer user work is never silently overwritten.

## Consequences

- UI code only coordinates review and confirmation; persistence stays outside PySide6.
- The first ticket does not perform fuzzy matching or automatic conflict detection.
- The first ticket rejects merge chains that would make undo ambiguous.
- Conflict review UI and Agent proposal tools can be added later without granting model output direct database write access.

## Agent proposal integration

The optional plot-discussion Agent may call `PROPOSE_CHARACTER_IDENTITY_MERGE`.
This tool validates two active character names and a non-empty reason, then records only the
normal Agent tool trace. It does not update character cards or memory references. Executed
proposals appear in the same conflict-review queue as deterministic name matches and are labeled
as Agent proposals. The existing confirmed application service remains the only merge path.

## Persistent review decisions

Schema v11 stores one current review decision for each stably ordered character pair. `DISTINCT`
and `DEFERRED` remove that pair from deterministic and Agent-origin candidate queues. `REOPENED`
returns it to normal detection. Reopening updates the existing row instead of deleting it, so the
original creation timestamp remains auditable. Deferred candidates do not automatically expire;
the user decides when to reopen them.
