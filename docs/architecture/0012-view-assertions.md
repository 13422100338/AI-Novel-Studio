# ADR 0012: Add sparse Subject View Time assertions

## Status

Accepted for backend Phase 2 foundation on 2026-07-18.

## Context

Schema v12 provides stable character subjects, but the current memory tables cannot reliably
distinguish world truth, a character's belief, reader-visible information, and an author's
future plan. Treating these as one fact pool risks omniscient characters, premature reveals,
and accidental promotion of an outline intention into canon.

## Decision

Schema v13 adds `view_assertions`. The first Phase 2 slice supports active `CHARACTER` subjects
and four explicit views:

- `WORLD_TRUTH`: established story-world facts;
- `CHARACTER_VIEW`: one character's explicit `KNOWS`, `BELIEVES`, `SUSPECTS`,
  `MISBELIEVES`, or `UNAWARE` state;
- `READER_VIEW`: sparse reveal-control records with a required narrative visibility start;
- `AUTHOR_PLAN`: future author intent that must not be read as world truth.

`CHARACTER_VIEW` requires a stable `viewer_subject_id` and epistemic status. Other views forbid
both fields. Missing character-view data means `UNKNOWN`; the system never manufactures an
`UNAWARE` assertion from absence.

The storage model has two independent time dimensions. `valid_from_sequence` and
`valid_to_sequence` describe when an assertion is true in the story state.
`narrative_visible_from_sequence` and `narrative_visible_to_sequence` describe when it may be
shown in narrative context. `story_time_label` is optional display metadata and does not drive
ordering.

This ticket exposes one conservative write path: an explicitly user-confirmed record is stored
as `USER_CONFIRMED`, `APPROVED`, and `HUMAN`. Model candidates, bulk extraction, conflict
resolution, editing, and UI are deferred.

## Context safety boundary

The Phase 2 query is a hard deterministic filter. It returns only records that:

- exactly match the requested view and, for character view, the requested viewer;
- are `APPROVED` or `LOCKED`;
- are neither stale nor marked `source_changed`;
- contain the requested narrative sequence in both applicable intervals.

Authority is not globally ranked across views or time scopes. Assertions in different views
coexist and are never allowed to overwrite one another merely because one has a higher
authority value.

## Data and failure boundaries

- Subject and viewer IDs must resolve to active character subjects.
- SQL values are parameterized and text/sequence inputs are bounded or validated.
- SQLite constraints repeat the critical view-shape, range, enum, and reader-reveal rules.
- Migration v13 is additive and atomic. It does not modify manuscripts or rewrite existing
  memory rows.

## Consequences

- Phase 3 Context Compiler can consume view-safe rows without guessing epistemic state.
- Reader secrets remain invisible before their explicit reveal boundary.
- Existing memory and generation paths are unchanged until a later integration ticket.
- `LOCATION`, `ORGANIZATION`, `ITEM`, `ABILITY`, `EVENT`, and `CONCEPT` subjects remain
  deferred, as do model-generated assertion candidates and UI review workflows.
