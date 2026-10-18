from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from ai_novel_studio.application.changeset_service import OperationStatus
from ai_novel_studio.application.chapter_revision_service import (
    ChapterRevisionService,
)
from ai_novel_studio.application.legacy_import.importer import LegacyProjectImporter
from ai_novel_studio.application.legacy_import.scanner import LegacyProjectScanner
from ai_novel_studio.application.selection_patch import (
    ANCHOR_CODEPOINTS,
    SCHEMA_VERSION,
    SelectionPatchCapture,
    parse_selection_patch_capture,
)
from ai_novel_studio.core.context.token_budget import TokenBudget
from ai_novel_studio.harness.agent_loop import (
    ChapterGenerationLoop,
    DraftBlockedError,
)
from ai_novel_studio.harness.approval_repository import ApprovalRepository
from ai_novel_studio.harness.approvals import ApprovalStatus
from ai_novel_studio.harness.artifacts import ArtifactKind, ArtifactStore, ProjectArtifactBackend
from ai_novel_studio.harness.cancel_token import CancellationError
from ai_novel_studio.harness.event_repository import HarnessEventRepository
from ai_novel_studio.harness.event_store import HarnessEventStore
from ai_novel_studio.harness.model_roles import ModelRole, ModelRoleBinding
from ai_novel_studio.harness.projections import HarnessProjectionService
from ai_novel_studio.harness.run_state import RunEventType, RunStage
from ai_novel_studio.harness.state_capsule import ContextHealth
from ai_novel_studio.infrastructure.llm.schemas import (
    LLMStreamEvent,
    StreamEventKind,
    TaskPurpose,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository

_DRAFT_TEXT = "新的第一章正文。它替换了旧内容。"


def _write_docx(path: Path, paragraphs: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    runs = "".join(
        f'<w:p><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>' for text in paragraphs
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{runs}</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)


class _FakeGateway:
    def __init__(self, events: tuple[LLMStreamEvent, ...]) -> None:
        self._events = events
        self.stream_calls = 0

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
        yield from self._events


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _selection_capture(
    source: str,
    selected: str,
    *,
    chapter_id: str,
    revision: int,
    occurrence: int = 0,
) -> SelectionPatchCapture:
    start = -1
    for _ in range(occurrence + 1):
        start = source.index(selected, start + 1)
    end = start + len(selected)

    def span(span_start: int, span_end: int) -> dict[str, object]:
        text = source[span_start:span_end]
        return {
            "start": span_start,
            "end": span_end,
            "text": text,
            "text_hash": _hash(text),
        }

    return parse_selection_patch_capture(
        {
            "schema_version": SCHEMA_VERSION,
            "chapter_id": chapter_id,
            "base_revision": revision,
            "base_source_hash": _hash(source),
            "selection": span(start, end),
            "before_anchor": span(max(0, start - ANCHOR_CODEPOINTS), start),
            "after_anchor": span(
                end,
                min(len(source), end + ANCHOR_CODEPOINTS),
            ),
        }
    )


def _imported_project(tmp_path: Path) -> tuple[ProjectRepository, str]:
    source = tmp_path / "legacy"
    source.mkdir()
    meta = {
        "title": "冒烟旧小说",
        "global_synopsis": "旧项目导入",
        "characters": [],
        "volumes": [
            {
                "name": "第一卷",
                "synopsis": "第一卷简介",
                "chapters": [{"name": "第一章", "synopsis": "第一章简介"}],
            }
        ],
    }
    (source / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    _write_docx(source / "第一卷" / "第一章.docx", ["旧第一章正文"])
    preview = LegacyProjectScanner().scan(source)
    destination = tmp_path / "imported"
    LegacyProjectImporter().import_project(preview, destination)
    project = ProjectRepository.open(destination)
    chapter = ChapterRepository(project).list_chapters()[0]
    return project, chapter.id


def _loop(project: ProjectRepository, gateway: object) -> ChapterGenerationLoop:
    binding = ModelRoleBinding(
        ModelRole.CHAPTER_DRAFT, TaskPurpose.PROSE_GENERATION, "provider-1", "model-1"
    )
    return ChapterGenerationLoop.for_project(
        project,
        gateway,  # type: ignore[arg-type]
        binding,
        budget=TokenBudget(4096, 512, 128),
        output_token_limit=512,
    )


def test_full_chain_generate_approve_commit_and_restart(tmp_path: Path) -> None:
    project, chapter_id = _imported_project(tmp_path)
    gateway = _FakeGateway(
        (
            LLMStreamEvent(StreamEventKind.TEXT, text="新的第一章正文。"),
            LLMStreamEvent(StreamEventKind.TEXT, text="它替换了旧内容。"),
            LLMStreamEvent(StreamEventKind.COMPLETED),
        )
    )
    loop = _loop(project, gateway)

    result = loop.generate_candidate("润色第一章", chapter_id)

    assert result.draft.text == _DRAFT_TEXT
    assert isinstance(result.audit.findings, tuple)
    assert result.approval.status is ApprovalStatus.PENDING
    assert result.package.context_manifest_id == result.compiled.manifest.id
    store = HarnessEventStore(HarnessEventRepository(project))
    assert store.get_run(result.run.id).stage is RunStage.WAITING_APPROVAL

    resolution = loop.commit_approved(result.approval.request_id)
    assert resolution.approval.status is ApprovalStatus.APPROVED
    assert all(
        outcome.status is OperationStatus.APPLIED
        for outcome in resolution.result.outcomes  # type: ignore[union-attr]
    )
    updated = ChapterRepository(project).get_chapter(chapter_id)
    assert updated.revision == 1
    assert ChapterRepository(project).read_content(chapter_id) == _DRAFT_TEXT
    loop.finish(result.run.id)

    reopened = ProjectRepository.open(project.layout.root)
    store = HarnessEventStore(HarnessEventRepository(reopened))
    events = store.replay(result.run.id)
    kinds = [event.event_type for event in events]
    for expected in (
        RunEventType.RUN_CREATED,
        RunEventType.CONTEXT_COMPILATION_STARTED,
        RunEventType.CONTEXT_COMPILED,
        RunEventType.GENERATION_PACKAGE_READY,
        RunEventType.CHAPTER_STREAM_STARTED,
        RunEventType.CHAPTER_STREAM_DELTA,
        RunEventType.CHAPTER_STREAM_COMPLETED,
        RunEventType.AUDIT_STARTED,
        RunEventType.AUDIT_COMPLETED,
        RunEventType.CHANGESET_READY,
        RunEventType.APPROVAL_REQUESTED,
        RunEventType.APPROVAL_RESOLVED,
    ):
        assert expected in kinds
    approval = ApprovalRepository(reopened).get(result.approval.request_id)
    assert approval.status is ApprovalStatus.APPROVED

    projections = HarnessProjectionService(store, approvals=ApprovalRepository(reopened))
    capsule = projections.capsule(result.run.id)
    assert capsule.context_manifest_id == result.compiled.manifest.id
    assert capsule.editor_snapshot_revision == 0
    assert capsule.formal_revision == 0
    assert capsule.context_health is ContextHealth.HEALTHY
    assert capsule.pending_approvals == ()
    assert store.get_run(result.run.id).stage is RunStage.COMPLETED
    assert projections.recoverable_runs() == ()

    status = projections.context_status(result.run.id)
    assert status.draft_artifact_id is not None
    artifact = ArtifactStore(ProjectArtifactBackend(reopened)).get(str(status.draft_artifact_id))
    assert artifact.kind is ArtifactKind.DRAFT_CANDIDATE
    assert artifact.content.decode() == _DRAFT_TEXT
    assert (reopened.layout.root / ".ai_pipeline" / "artifacts").is_dir()


def test_selection_patch_replaces_only_the_selected_duplicate(tmp_path: Path) -> None:
    project, chapter_id = _imported_project(tmp_path)
    chapters = ChapterRepository(project)
    source = "重复段。\n\n中间段。\n\n重复段。"
    chapter = chapters.save_content(
        chapter_id,
        source,
        source="test",
        reason="selection fixture",
        expected_revision=0,
    )
    capture = _selection_capture(
        source,
        "重复段",
        chapter_id=chapter_id,
        revision=chapter.revision,
        occurrence=1,
    )
    gateway = _FakeGateway(
        (
            LLMStreamEvent(StreamEventKind.TEXT, text="第二处已改"),
            LLMStreamEvent(StreamEventKind.COMPLETED),
        )
    )
    loop = _loop(project, gateway)

    result = loop.generate_candidate(
        "润色",
        chapter_id,
        selection_patch=capture,
    )

    assert result.draft.text == "第二处已改"
    assert chapters.read_content_exact(chapter_id) == source
    operation = result.approval.payload["operations"][0]  # type: ignore[index]
    assert isinstance(operation, dict)
    operation_payload = operation["payload"]
    assert isinstance(operation_payload, dict)
    patch_payload = operation_payload["selection_patch"]
    assert isinstance(patch_payload, dict)
    assert patch_payload["replacement_candidate_id"] == result.draft.artifact.artifact_id

    resolution = loop.commit_approved(result.approval.request_id)
    assert all(
        outcome.status is OperationStatus.APPLIED
        for outcome in resolution.result.outcomes  # type: ignore[union-attr]
    )
    assert chapters.read_content_exact(chapter_id) == ("重复段。\n\n中间段。\n\n第二处已改。")


def test_stale_selection_closes_run_before_model_or_approval(tmp_path: Path) -> None:
    project, chapter_id = _imported_project(tmp_path)
    chapters = ChapterRepository(project)
    source = chapters.read_content_exact(chapter_id)
    capture = _selection_capture(
        source,
        "旧第一章",
        chapter_id=chapter_id,
        revision=0,
    )
    ChapterRevisionService(project).submit_revision(
        chapter_id,
        "作者已经修改正文",
        source="test",
        reason="make selection stale",
        expected_revision=0,
    )
    gateway = _FakeGateway(
        (
            LLMStreamEvent(StreamEventKind.TEXT, text="不应生成"),
            LLMStreamEvent(StreamEventKind.COMPLETED),
        )
    )
    loop = _loop(project, gateway)

    with pytest.raises(DraftBlockedError):
        loop.generate_candidate("润色", chapter_id, selection_patch=capture)

    store = HarnessEventStore(HarnessEventRepository(project))
    run = next(iter(store.list_runs()))
    assert run.stage is RunStage.STALE
    assert gateway.stream_calls == 0
    assert ApprovalRepository(project).list_for_run(run.id) == ()


def test_selection_patch_is_replayed_again_at_changeset_commit(tmp_path: Path) -> None:
    project, chapter_id = _imported_project(tmp_path)
    chapters = ChapterRepository(project)
    source = chapters.read_content_exact(chapter_id)
    capture = _selection_capture(
        source,
        "旧第一章",
        chapter_id=chapter_id,
        revision=0,
    )
    loop = _loop(
        project,
        _FakeGateway(
            (
                LLMStreamEvent(StreamEventKind.TEXT, text="候选替换"),
                LLMStreamEvent(StreamEventKind.COMPLETED),
            )
        ),
    )
    result = loop.generate_candidate("润色", chapter_id, selection_patch=capture)
    chapter = chapters.get_chapter(chapter_id)
    source_path = project.layout.root / chapter.content_path
    source_path.write_text("同修订号的外部漂移", encoding="utf-8")

    resolution = loop.commit_approved(result.approval.request_id)

    assert resolution.result is not None
    assert resolution.result.outcomes[0].status is OperationStatus.FAILED
    assert resolution.result.outcomes[0].message == "selection patch is stale"
    assert chapters.read_content_exact(chapter_id) == "同修订号的外部漂移"


def test_cancel_mid_chain_saves_partial_and_closes_run(tmp_path: Path) -> None:
    project, chapter_id = _imported_project(tmp_path)
    holder: dict[str, ChapterGenerationLoop] = {}

    class _CancellingGateway(_FakeGateway):
        def stream(
            self,
            purpose: TaskPurpose,
            messages: object,
            output_token_limit: int,
            **kwargs: object,
        ):
            yield LLMStreamEvent(StreamEventKind.TEXT, text="残稿开头")
            store = HarnessEventStore(
                HarnessEventRepository(ProjectRepository.open(project.layout.root))
            )
            active = next(
                run
                for run in store.list_runs()
                if run.stage not in {RunStage.COMPLETED, RunStage.CANCELLED, RunStage.FAILED}
            )
            holder["loop"].cancel(active.id)
            yield LLMStreamEvent(StreamEventKind.TEXT, text="迟到增量")

    loop = _loop(project, _CancellingGateway(()))
    holder["loop"] = loop

    with pytest.raises(CancellationError):
        loop.generate_candidate("会被取消的生成", chapter_id)

    store = HarnessEventStore(HarnessEventRepository(project))
    active = next(
        run for run in store.list_runs() if run.stage not in {RunStage.COMPLETED, RunStage.FAILED}
    )
    assert active.stage is RunStage.CANCELLED
    kinds = [event.event_type for event in store.replay(active.id)]
    assert RunEventType.CHAPTER_STREAM_COMPLETED not in kinds
    assert RunEventType.APPROVAL_REQUESTED not in kinds
    assert kinds.count(RunEventType.CHAPTER_STREAM_DELTA) == 1
    assert ApprovalRepository(project).list_for_run(active.id) == ()
    assert ChapterRepository(project).get_chapter(chapter_id).revision == 0
