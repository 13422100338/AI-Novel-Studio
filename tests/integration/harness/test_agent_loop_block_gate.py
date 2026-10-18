from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from ai_novel_studio.application.chapter_revision_service import ChapterRevisionService
from ai_novel_studio.application.selection_patch import (
    ANCHOR_CODEPOINTS,
    SCHEMA_VERSION,
    SelectionPatchStaleError,
    SelectionPatchValidationError,
    finalize_selection_patch,
    parse_selection_patch,
    parse_selection_patch_capture,
    replay_selection_patch,
    validate_selection_patch_capture,
)
from ai_novel_studio.core.context.token_budget import TokenBudget
from ai_novel_studio.harness.agent_loop import ChapterGenerationLoop, DraftBlockedError
from ai_novel_studio.harness.approval_resolver import ApprovalResolver
from ai_novel_studio.harness.event_repository import HarnessEventRepository
from ai_novel_studio.harness.event_store import HarnessEventStore
from ai_novel_studio.harness.model_roles import ModelRole, ModelRoleBinding
from ai_novel_studio.harness.run_state import RunEventType, RunStage
from ai_novel_studio.infrastructure.llm.schemas import (
    LLMStreamEvent,
    StreamEventKind,
    TaskPurpose,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _span(source: str, start: int, end: int) -> dict[str, object]:
    text = source[start:end]
    return {
        "start": start,
        "end": end,
        "text": text,
        "text_hash": _hash(text),
    }


def _capture_payload(
    source: str,
    start: int,
    end: int,
    *,
    chapter_id: str = "chapter-1",
    revision: int = 7,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "chapter_id": chapter_id,
        "base_revision": revision,
        "base_source_hash": _hash(source),
        "selection": _span(source, start, end),
        "before_anchor": _span(source, max(0, start - ANCHOR_CODEPOINTS), start),
        "after_anchor": _span(
            source,
            end,
            min(len(source), end + ANCHOR_CODEPOINTS),
        ),
    }


class _CountingGateway:
    def __init__(self, *, stream_ok: bool = False) -> None:
        self.stream_calls = 0
        self._stream_ok = stream_ok

    def complete(self, *args: object, **kwargs: object) -> object:
        raise NotImplementedError

    def stream(
        self,
        purpose: TaskPurpose,
        messages: object,
        output_token_limit: int,
        **kwargs: object,
    ):
        self.stream_calls += 1
        if self._stream_ok:
            yield LLMStreamEvent(StreamEventKind.TEXT, text="新正文")
            yield LLMStreamEvent(StreamEventKind.COMPLETED)


def _loop(tmp_path: Path, *, stream_ok: bool = False):
    project = ProjectRepository.create(tmp_path / "novel", "Block gate")
    volume = project.list_volumes()[0]
    chapter = (
        ChapterRevisionService(project)
        .submit_creation(volume.id, "Chapter", content="正文")
        .chapter
    )
    gateway = _CountingGateway(stream_ok=stream_ok)
    binding = ModelRoleBinding(
        ModelRole.CHAPTER_DRAFT, TaskPurpose.PROSE_GENERATION, "provider-1", "model-1"
    )
    loop = ChapterGenerationLoop.for_project(
        project,
        gateway,  # type: ignore[arg-type]
        binding,
        budget=TokenBudget(4096, 512, 128),
        output_token_limit=512,
    )
    return project, chapter, gateway, loop


def test_unresolved_package_blocks_draft_model_with_visible_reason(
    tmp_path: Path,
) -> None:
    project, chapter, gateway, loop = _loop(tmp_path)

    with pytest.raises(DraftBlockedError, match="unresolved plot decisions"):
        loop.generate_candidate("写第二章", chapter.id, unresolved=("结局没想好",))

    assert gateway.stream_calls == 0
    store = HarnessEventStore(HarnessEventRepository(project))
    run = store.list_runs()[0]
    assert run.stage is RunStage.INTERRUPTED
    assert run.failure_code == "DRAFT_BLOCKED"
    assert "unresolved plot decisions" in (run.failure_message or "")
    kinds = [event.event_type for event in store.replay(run.id)]
    assert RunEventType.GENERATION_PACKAGE_READY in kinds
    assert RunEventType.CHAPTER_STREAM_STARTED not in kinds
    assert RunEventType.CHAPTER_STREAM_COMPLETED not in kinds


def test_ready_package_still_streams(tmp_path: Path) -> None:
    _project, chapter, gateway, loop = _loop(tmp_path, stream_ok=True)

    result = loop.generate_candidate("写第二章", chapter.id)

    assert gateway.stream_calls == 1
    assert result.draft.text == "新正文"


def test_selection_candidate_proposes_full_chapter_with_only_selection_replaced(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Selection edit")
    volume = project.list_volumes()[0]
    chapter = (
        ChapterRevisionService(project)
        .submit_creation(
            volume.id,
            "Chapter",
            content="开头\n旧句\n结尾",
        )
        .chapter
    )
    gateway = _CountingGateway(stream_ok=True)
    loop = ChapterGenerationLoop.for_project(
        project,
        gateway,  # type: ignore[arg-type]
        ModelRoleBinding(
            ModelRole.CHAPTER_DRAFT,
            TaskPurpose.PROSE_GENERATION,
            "provider-1",
            "model-1",
        ),
        budget=TokenBudget(4096, 512, 128),
        output_token_limit=512,
    )

    source = "开头\n旧句\n结尾"
    start = source.index("旧句")
    capture = parse_selection_patch_capture(
        _capture_payload(
            source,
            start,
            start + len("旧句"),
            chapter_id=chapter.id,
            revision=chapter.revision,
        )
    )
    result = loop.generate_candidate("润色", chapter.id, selection_patch=capture)

    assert result.draft.text == "新正文"
    operation = result.approval.payload["operations"][0]
    patch_payload = operation["payload"]["selection_patch"]
    assert operation["payload"]["content"] == patch_payload["result_hash"]
    assert operation["payload"]["content"] != result.draft.text
    assert result.approval.summary == "候选稿替换选区(3 字)"
    assert ChapterRepository(project).read_content(chapter.id) == "开头\n旧句\n结尾"

    ApprovalResolver.for_project(project).resolve_and_commit(
        result.approval.request_id,
        approved=True,
    )

    assert ChapterRepository(project).read_content(chapter.id) == "开头\n新正文\n结尾"


def test_selection_patch_finalize_replay_and_strict_schema() -> None:
    source = "重复段。\n\n中间段。\n\n重复段。"
    selected = "重复段"
    start = source.rindex(selected)
    capture = parse_selection_patch_capture(_capture_payload(source, start, start + len(selected)))
    replacement = "第二处已改"
    patch = finalize_selection_patch(
        capture,
        source=source,
        chapter_id="chapter-1",
        revision=7,
        replacement_candidate_id=f"sha256:{_hash(replacement)}",
        replacement_text=replacement,
    )

    assert (
        replay_selection_patch(
            patch,
            source=source,
            chapter_id="chapter-1",
            revision=7,
        )
        == "重复段。\n\n中间段。\n\n第二处已改。"
    )
    assert parse_selection_patch(patch.to_payload()) == patch

    invalid = capture.to_payload()
    invalid["unexpected"] = "no"
    with pytest.raises(SelectionPatchValidationError):
        parse_selection_patch_capture(invalid)

    with pytest.raises(SelectionPatchValidationError):
        validate_selection_patch_capture(
            replace(capture, schema_version="selection-patch-v2"),
            source=source,
            chapter_id="chapter-1",
            revision=7,
        )


def test_selection_patch_never_relocates_after_source_or_anchor_drift() -> None:
    source = "相同\n\n中间\n\n相同"
    start = source.rindex("相同")
    capture = parse_selection_patch_capture(_capture_payload(source, start, start + len("相同")))
    replacement = "替换"
    patch = finalize_selection_patch(
        capture,
        source=source,
        chapter_id="chapter-1",
        revision=7,
        replacement_candidate_id=f"sha256:{_hash(replacement)}",
        replacement_text=replacement,
    )

    with pytest.raises(SelectionPatchStaleError):
        replay_selection_patch(
            patch,
            source=source + " drift",
            chapter_id="chapter-1",
            revision=7,
        )

    tampered = patch.to_payload()
    before = dict(tampered["before_anchor"])  # type: ignore[arg-type]
    before["text"] = "伪" * len(str(before["text"]))
    before["text_hash"] = _hash(str(before["text"]))
    tampered["before_anchor"] = before
    with pytest.raises(SelectionPatchStaleError):
        replay_selection_patch(
            parse_selection_patch(tampered),
            source=source,
            chapter_id="chapter-1",
            revision=7,
        )
