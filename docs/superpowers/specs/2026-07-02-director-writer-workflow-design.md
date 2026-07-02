# Director-Writer Workflow Design

## Status

Approved on 2026-07-02.

## Goal

Extend AI Novel Studio with a reviewable handoff between plot discussion and prose generation,
temporal character knowledge, protected narrative misdirection, layered style rules, deterministic
style checks, and authorship provenance. The workflow must improve long-form consistency without
turning every chapter into an expensive, mandatory Agent run.

## Evidence and adaptation boundary

The design was informed by a published long-form workflow that separates a director session from
delegated prose writing, compiles per-episode briefs, tracks character knowledge and foreshadowing,
and runs configurable prose-pattern checks:

- https://medium.com/@osushi_cr/my-setup-for-writing-full-length-novels-with-claude-code-62d334cde91c
- https://www.reddit.com/r/WritingWithAI/comments/1s4zfa9/

AI Novel Studio does not copy that workflow's code, skill files, prompts, or repository structure.
It independently implements the reusable product principles inside the existing PySide6, SQLite,
Markdown, repository, checkpoint, and model-gateway architecture.

## Core decisions

1. The plot-discussion model acts as director; the prose model acts as writer.
2. A frozen Chapter Brief is the only formal handoff from director to writer in Standard and
   Strict modes.
3. A Chapter Brief is a versioned pipeline artifact, not a second manuscript or memory database.
4. Character state, character knowledge, and reader knowledge are separate temporal records.
5. Real foreshadowing and intentional misdirection are different clue types.
6. Style guidance is layered and compiled per task instead of injecting one ever-growing guide.
7. Deterministic checks report measurable patterns before model-based review.
8. AI-derived updates are candidates; locked human canon, decisions, rules, and samples are
   immutable until the user explicitly accepts a change.
9. Every accepted chapter can be traced to human decisions, AI suggestions, inputs, model calls,
   and user edits.
10. Fast mode remains available and does not require the full design workflow.

## Architecture

```text
Plot chat / outline / memory / current manuscript
                    |
                    v
            ChapterBriefCompiler
                    |
             Draft Chapter Brief
                    |
             Human review + freeze
                    |
                    v
             ContextBuilder + manifest
                    |
                    v
                Prose model
                    |
              Versioned draft
                    |
         DeterministicStyleChecker
                    |
          Model audit when requested
                    |
          Human accept/edit/reject
                    |
      Candidate memory + provenance log
```

The compiler can use a structured model call to normalize language, but deterministic code selects
the source records, enforces authority, applies the chapter time boundary, and validates every ID.
The prose model cannot query or mutate project storage directly.

## Chapter Brief

`ChapterBriefCompiler.compile(chapter_id, mode, source_revision) -> ChapterBriefDraft` gathers:

- dramatic purpose, target length, story date, and point-of-view character;
- hard events, soft goals, prohibited changes, and explicit creative freedom;
- current motivation, psychology, relationship, location, injury, and capability states;
- knowledge that each participating character knows, suspects, misunderstands, or does not know;
- reader knowledge at the same story time;
- clue actions to plant, reinforce, redirect, reveal, resolve, or leave open;
- relevant book voice, scene rules, character voices, forbidden patterns, and approved samples;
- recent full chapters and retrieved historical evidence with source revisions and hashes;
- omissions, stale dependencies, conflicts, and budget warnings.

Brief states are `DRAFT`, `FROZEN`, `STALE`, and `ARCHIVED`. Standard and Strict generation require
`FROZEN`. Any source revision change invalidates the source fingerprint and marks the Brief `STALE`.
A user can clone a stale Brief into a new draft, inspect the delta, then freeze the new revision.

The plot chat can propose or update a draft Brief through an explicit action. Ordinary conversation
never silently changes the Brief. A frozen Brief is read-only.

## Temporal knowledge matrix

Knowledge is modeled as stable items plus time-stamped state changes:

```text
knowledge_items(
  id, title, detail, authority, review_status
)

knowledge_state_events(
  id, knowledge_id, subject_type, subject_id,
  chapter_id, state, evidence, source_type, review_status
)
```

`subject_type` is `CHARACTER` or `READER`. `state` is `UNKNOWN`, `SUSPECTED`, `MISUNDERSTOOD`,
`KNOWN`, or `FORGOTTEN`. Queries require a chapter boundary and return the latest valid event at or
before that boundary. Rewriting an earlier chapter invalidates dependent later knowledge events; it
does not rewrite them silently.

The Brief validator rejects knowledge attributed to a character before acquisition. Reader
knowledge can shape dramatic irony but cannot be given to a character unless a character event
supports it.

## Narrative clue ledger

The existing foreshadowing concept becomes a typed narrative-clue ledger:

- `FORESHADOW`: a true clue intended for later payoff;
- `MISDIRECTION`: a deliberately misleading clue;
- `OPEN_QUESTION`: an unresolved question with no committed answer yet;
- `AUTHOR_PROMISE`: an expectation the narrative must eventually honor;
- `ATMOSPHERIC_HINT`: suggestive texture that is not a factual promise.

Each clue stores planting, reinforcement, redirection, reveal, resolution, abandonment, authority,
and review state. Audits can report accidental contradictions, but cannot automatically convert or
repair a locked Misdirection, Open Question, or Atmospheric Hint.

## Layered style system

Style data is separated by responsibility:

1. Book voice: point of view, psychic distance, register, narrative attention, and reader profile.
2. Genre or scene rules: action, mystery, intimacy, comedy, exposition, and other scene families.
3. Character voice: diction, verbal habits, avoided words, deflection, and emotional expression.
4. Project anti-patterns: repeated gestures, filler, over-explanation, weak endings, and banned text.
5. Chapter overrides: temporary rules required by the current dramatic function.

The compiler injects only relevant layers. Human-authored samples are immutable source artifacts.
Model annotations, extracted patterns, and rewritten examples are stored separately as candidates.
No model operation can write into the original sample file.

## Style checking

`DeterministicStyleChecker` runs before model audit and supports chapter, volume, and book scopes.
Initial deterministic rules cover:

- exact words, phrases, gestures, and regular-expression patterns;
- repeated sentence endings and same-length sentence chains;
- paragraph and sentence length thresholds;
- repeated dialogue tags and character-specific forbidden expressions;
- configurable occurrence limits per chapter, volume, and book.

The checker produces findings with rule ID, scope, paragraph reference, evidence, actual count, and
limit. It never edits prose. Model audit handles semantic concerns such as voice drift,
over-explanation, pacing, emotional truth, and insufficient character differentiation. All repairs
remain bounded proposals shown in the diff workspace.

## Provenance

Every generation run records:

- human decisions and locked constraints;
- AI suggestions accepted or rejected by the user;
- frozen Brief ID, revision, content hash, and source fingerprint;
- Context Manifest and retrieved evidence;
- model profile, prompt/contract version, token usage, and output;
- user edits, accepted repairs, and resulting manuscript revision.

Provenance categories are `HUMAN_DECISION`, `AI_SUGGESTION`, `USER_ACCEPTED`, `USER_REJECTED`, and
`USER_EDITED`. The record supports debugging, recovery, deliberate authorship, and optional export.
It is not a claim that automated logs alone determine copyright status.

## Mode behavior

### Fast

```text
Context -> prose draft -> versioned save -> human edit
```

No frozen Brief or automatic long-term memory update is required.

### Standard

```text
Event checklist -> lightweight Brief -> human freeze -> context -> prose
-> deterministic basic checks -> human confirmation -> candidate memory
```

The lightweight Brief includes participating characters, applicable knowledge, active clues, hard
events, and relevant style rules.

### Strict

```text
Event checklist -> complete Brief -> knowledge validation -> human freeze -> context -> prose
-> deterministic full-work checks -> independent model audit -> bounded repair proposals
-> human confirmation -> candidate memory and provenance
```

Strict mode does not allow unbounded review loops. Existing limits on audit and repair passes remain.

## UI contract

Phase 2 mock data must expose the later workflow without calling a model:

- The center pane opens a Brief review panel with source badges, warnings, edit, freeze, and clone
  actions.
- The plot-chat action creates a draft Brief proposal; normal chat remains conversational.
- The memory page includes tabs for character state, character knowledge, reader knowledge, and
  narrative clues.
- The style page includes layered rules, immutable samples, candidate suggestions, and frequency
  scopes.
- The audit page distinguishes deterministic findings from model findings.
- The chapter footer displays provenance and current Brief status.

## Agent constraints

Agent-ready infrastructure may query frozen Briefs, bounded knowledge state, narrative clues, and
style rules through read-only tools. Agents run sequentially by default. Only one writer Agent may
produce prose for a chapter at a time. Retrieval and audit Agents cannot write manuscript, canon,
Brief, style, or memory records. All mutations pass through repositories, optimistic revision
checks, version snapshots, and human confirmation.

## Error handling

- Missing or stale Brief source: block Standard or Strict generation and show the changed sources.
- Knowledge conflict: report all competing events and require a user decision; never guess.
- Token overflow: retain hard constraints and frozen Brief fields, then reduce evidence according to
  the existing ContextBuilder priority rules while recording omissions.
- Invalid model IDs or clue actions: reject the response through the contract layer.
- Style checker failure: preserve the draft and mark checking failed; do not delete or regenerate.
- Provenance-write failure: keep the draft as recoverable but do not mark the run complete.
- Concurrent Brief or chapter change: reject the stale write and offer a diff against the current
  revision.

## Testing

The implementation plans for Phases 2 through 8 must cover:

- Brief source fingerprints, freeze, clone, stale propagation, and time-bound evidence;
- character knowledge not available before acquisition and reader knowledge not leaking to cast;
- intentional misdirection remaining protected during audit and repair;
- immutable human style samples and separation of model annotations;
- chapter, volume, and book frequency rules with stable paragraph evidence;
- traceable human, AI, acceptance, rejection, and edit provenance;
- single-writer Agent enforcement and read-only audit/retrieval tools;
- million-word projects with thousands of knowledge events, clues, style findings, and Briefs;
- interruption and recovery at every new pipeline state.

## Phase mapping

- Phase 2: Brief review, knowledge matrix, narrative clues, style rules, and provenance UI with mock
  data.
- Phase 3: task routing for Brief normalization and style audit; no storage mutation by adapters.
- Phase 4: temporal knowledge, reader knowledge, clue ledger, layered style retrieval, fingerprints,
  and invalidation.
- Phase 5: ChapterBriefCompiler, freeze/clone/stale lifecycle, director-writer handoff, and new
  checkpoints.
- Phase 6: deterministic style engine, knowledge/misdirection audit, provenance, and bounded repair.
- Phase 7: sequential Agent scheduling, frozen-Brief tools, read-only permissions, and budgets.
- Phase 8: long-project, contamination, knowledge leakage, provenance, concurrency, and recovery
  pressure tests.

Phase 1 storage remains valid. Later schema additions must use new idempotent migrations and must not
rewrite or discard Phase 1 project data.
