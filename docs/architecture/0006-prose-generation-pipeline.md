# ADR 0006: Prose generation pipeline

## Status

Accepted for V3 Phase 5.

## Context

Long-form novel writing needs prose generation that can use large prior context without treating the model output as authoritative storage. The system must support user-defined output Token limits, interruption recovery, manual review, and million-word projects. It must also keep prose generation separate from memory extraction, audit, repair, and future Agent tool loops.

## Decision

Phase 5 adds a traceable prose-generation pipeline:

```text
Current Chapter Requirement
        |
        v
Chapter Brief lifecycle
        |
        v
GenerationContextService -> Context Manifest
        |
        v
ProseGenerationService -> Checkpoints
        |
        v
GenerationAcceptanceService
        |
        v
ChapterRepository.save_content
```

The prose model never writes formal manuscript content directly. It can only stream a draft into checkpoints. A user action must explicitly accept a completed or explicitly allowed partial draft before the chapter正文 is changed.

## Ownership boundaries

- UI widgets emit intents and display state only.
- `ProjectGenerationSession` owns framework-neutral generation state and synchronous use cases.
- `QtProjectGenerationRuntime` lives under `ui/qt` and translates that session into Qt signals and background jobs.
- `ProjectRuntime` composes a project with `ProjectGenerationSession`; it does not import PySide6 or UI modules.
- Application services own pipeline state transitions.
- Repositories own SQLite and filesystem persistence.
- The model gateway owns provider calls and cannot mutate project storage.
- Memory extraction, audit, repair, and Agent tools remain separate phases.

The UI exposes only `BASIC` (快速) and `STANDARD` (普通) as creation modes. The
persisted `STRICT` value is retained as a compatibility encoding for the optional
pre-accept audit gate; it is not a third user-facing mode.

## Legal generation states

Generation runs use:

- `PREPARING`: context is being validated and assembled.
- `READY`: prompt and manifest are saved; no paid prose call has started yet.
- `STREAMING`: a single prose stream is active.
- `PARTIAL`: durable draft checkpoints exist, but the stream ended before completion.
- `COMPLETED`: a full draft checkpoint exists.
- `FAILED`: no acceptable draft should be offered.
- `ACCEPTED`: the user accepted the draft into the formal chapter.
- `DISCARDED`: the user abandoned the run; checkpoints are preserved.

At most one `PREPARING / READY / STREAMING` writer run may exist per chapter.

## Prompt order

The prose prompt is assembled in stable order:

1. fixed writing-system prefix;
2. Phase 5 safety and authorship boundary;
3. Current Chapter Requirement;
4. frozen Brief, when required by mode;
5. recent full chapters when budget allows;
6. structured memory and style evidence;
7. compressed history and search evidence;
8. final instruction to output only the current chapter prose.

Required blocks are never partially truncated. Optional blocks are selected whole, replaced with a whole fallback summary, or omitted with a manifest record.

## Token policy

The user-selected output Token limit is passed through unchanged. If the selected model reports a lower maximum output limit, preparation fails clearly instead of silently shrinking the request. The context budget is:

```text
context_window - output_token_limit - safety_margin
```

This means million-word projects rely on dynamic assembly rather than full-book prompt stuffing.

## Checkpoint format

Each checkpoint is cumulative text saved under:

```text
.ai_pipeline/checkpoints/run_<run_id>/checkpoint_<sequence>.md
```

The database stores run ID, sequence, relative path, SHA-256 hash, finish reason, and timestamp. Reading a checkpoint verifies that the path stays inside the project root and that the content hash still matches.

## Adoption boundary

Acceptance requires:

- run status `COMPLETED`, or `PARTIAL` with explicit partial adoption;
- latest checkpoint exists and passes integrity checks;
- chapter revision matches the expected revision;
- chapter history snapshot is created before overwrite;
- memory dependencies are invalidated through the existing chapter-save path;
- accepted chapter revision is recorded on the generation run.

If the user edited the chapter after the draft was generated, adoption is rejected and the checkpoint remains recoverable.

## Recovery

Recovery scans `PREPARING / READY / STREAMING / PARTIAL` runs and existing checkpoints. It never starts a second model call automatically. The UI may show the recovered draft and let the user discard, retry from a new run, or explicitly accept a partial draft.

## Phase separation

Phase 5 intentionally does not implement:

- deterministic style repair;
- knowledge/misdirection audit;
- provenance export beyond generation-run and chapter history records;
- Agent tool calls while reasoning;
- automatic memory promotion after prose generation.

Those remain Phase 6 and Phase 7 concerns.

## Verification

Phase 5 is covered by unit, integration, and UI tests for schema, Brief lifecycle, context preparation, stream checkpoints, recovery, acceptance, UI separation, and hundred-chapter pressure behavior.
