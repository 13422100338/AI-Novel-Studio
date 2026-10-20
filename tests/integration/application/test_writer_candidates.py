import hashlib
import json
from threading import Lock
from types import SimpleNamespace

import pytest

from ai_novel_studio.application.novel_read_service import NovelEditorSnapshot, NovelReadService
from ai_novel_studio.application.novel_writer_service import NovelWriterService
from ai_novel_studio.application.selection_patch import capture_selection_range
from ai_novel_studio.infrastructure.llm import (
    LLMStreamEvent,
    ModelCapabilities,
    ModelRoute,
    StreamEventKind,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.generation_repository import GenerationRepository
from ai_novel_studio.infrastructure.storage.outline_repository import OutlineRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.writer_input_repository import WriterInputRepository


@pytest.fixture
def candidate(tmp_path):
    project = ProjectRepository.create(tmp_path / "novel", "候选操作验证")
    chapters = ChapterRepository(project)
    raw = "开头😀\r\n重复句。\r\n中间不能变。\r\n重复句。\r\n结尾。"
    chapter = chapters.create_chapter(project.list_volumes()[0].id, "当前章", "1", raw)
    outline = OutlineRepository(project).create("全书", "# 全书原文\n以后发生的计划。")
    novel = NovelReadService(project)
    novel.update_editor(NovelEditorSnapshot(chapter.id, chapter.title, chapter.revision, raw))
    calls = []
    output = ["候选新句。"]
    operation_lock = Lock()
    route = ModelRoute("provider", "writer")

    class Gateway:
        configuration = SimpleNamespace(
            routes=SimpleNamespace(resolve=lambda _: route),
            model=lambda _: SimpleNamespace(capabilities=ModelCapabilities(context_window=1000000)),
        )

        def stream(self, purpose, messages, output_token_limit):
            calls.append(messages)
            yield LLMStreamEvent(StreamEventKind.TEXT, text=output[0])
            yield LLMStreamEvent(StreamEventKind.COMPLETED)

    events = []

    def writer():
        return NovelWriterService(
            project,
            novel,
            gateway_factory=Gateway,
            on_event=events.append,
            operation_lock=operation_lock,
        )

    service = writer()
    return SimpleNamespace(
        project=project,
        chapters=chapters,
        chapter=chapter,
        raw=raw,
        outline=outline,
        novel=novel,
        calls=calls,
        events=events,
        writer=service,
        new_writer=writer,
        output=output,
        operation_lock=operation_lock,
    )


def generate(work):
    work.writer.begin_turn()
    proposal = work.writer.generate(
        work.chapter.id, work.chapter.revision, "生成候选。", recent_chapters=0
    )
    result = work.writer.confirm_input(proposal["draft_id"])
    return result, work.events[-1]


def test_whole_chapter_adoption_creates_a_revision_and_keeps_input_snapshot(candidate):
    work = candidate
    result, event = generate(work)
    assert event["can_adopt"]
    accepted = work.writer.adopt_candidate(
        result["run_id"], event["checkpoint_id"], event["candidate_hash"]
    )
    assert accepted["text"] == "候选新句。"
    assert work.chapters.read_content_exact(work.chapter.id) == "候选新句。"
    assert GenerationRepository(work.project).get(result["run_id"]).status == "ACCEPTED"
    assert len(work.calls) == 1
    assert (
        WriterInputRepository(work.project).load(result["run_id"])["metadata"]["author_confirmed"]
        is True
    )


def test_second_repeated_selection_is_the_only_replacement(candidate):
    work = candidate
    start = work.raw.rindex("重复句。")
    capture = capture_selection_range(
        work.chapter.id, work.chapter.revision, work.raw, start, start + len("重复句。")
    )
    work.novel.update_editor(
        NovelEditorSnapshot(
            work.chapter.id,
            work.chapter.title,
            work.chapter.revision,
            work.raw,
            False,
            "重复句。",
            capture,
        )
    )
    result, event = generate(work)
    work.writer.adopt_candidate(result["run_id"], event["checkpoint_id"], event["candidate_hash"])
    expected = work.raw[:start] + "候选新句。" + work.raw[start + len("重复句。") :]
    assert work.chapters.read_content_exact(work.chapter.id) == expected
    assert expected.count("重复句。") == 1


def test_quote_without_a_capture_is_copy_only(candidate):
    work = candidate
    work.novel.update_editor(
        NovelEditorSnapshot(
            work.chapter.id, work.chapter.title, work.chapter.revision, work.raw, False, "重复句。"
        )
    )
    result, event = generate(work)
    assert not event["can_adopt"]
    with pytest.raises(ValueError):
        work.writer.adopt_candidate(
            result["run_id"], event["checkpoint_id"], event["candidate_hash"]
        )
    assert work.chapters.read_content_exact(work.chapter.id) == work.raw


@pytest.mark.parametrize("change", ["editor", "formal", "candidate"])
def test_changed_source_or_candidate_cannot_be_adopted(candidate, change):
    work = candidate
    result, event = generate(work)
    if change == "editor":
        work.novel.update_editor(
            NovelEditorSnapshot(
                work.chapter.id,
                work.chapter.title,
                work.chapter.revision,
                work.raw + "新编辑",
                True,
            )
        )
    elif change == "formal":
        work.chapters.save_content(
            work.chapter.id,
            "别处已改",
            source="user_edit",
            reason="test",
            expected_revision=work.chapter.revision,
        )
    else:
        event["candidate_hash"] = "0" * 64
    with pytest.raises(ValueError):
        work.writer.adopt_candidate(
            result["run_id"], event["checkpoint_id"], event["candidate_hash"]
        )
    assert GenerationRepository(work.project).get(result["run_id"]).status == "COMPLETED"


def test_failed_adoption_rolls_back_manuscript_and_generation_status(candidate):
    work = candidate
    result, event = generate(work)
    with work.project.database.connect() as connection:
        connection.execute(
            "CREATE TRIGGER reject_adoption BEFORE UPDATE OF status ON generation_runs "
            "WHEN NEW.status='ACCEPTED' BEGIN "
            "SELECT RAISE(ABORT,'forced adoption failure'); END"
        )
    with pytest.raises((ValueError, RuntimeError)):
        work.writer.adopt_candidate(
            result["run_id"], event["checkpoint_id"], event["candidate_hash"]
        )
    assert work.chapters.read_content_exact(work.chapter.id) == work.raw
    assert work.chapters.get_chapter(work.chapter.id).revision == work.chapter.revision
    assert GenerationRepository(work.project).get(result["run_id"]).status == "COMPLETED"


def test_discard_keeps_manuscript_checkpoint_and_input(candidate):
    work = candidate
    result, event = generate(work)
    assert work.writer.discard_candidate(
        result["run_id"], event["checkpoint_id"], event["candidate_hash"]
    )
    assert GenerationRepository(work.project).get(result["run_id"]).status == "DISCARDED"
    assert work.chapters.read_content_exact(work.chapter.id) == work.raw
    assert WriterInputRepository(work.project).messages_for(result["run_id"])
    assert work.new_writer().recover_candidates()["restored"] == 0


def test_reopen_restores_original_input_without_model_calls_or_new_outline(candidate):
    work = candidate
    result, event = generate(work)
    frozen = WriterInputRepository(work.project).messages_for(result["run_id"])
    OutlineRepository(work.project).save(
        work.outline.version.document_id, "# 今天的新大纲", expected_revision=1
    )
    restored = work.new_writer()
    assert restored.recover_candidates()["restored"] == 1
    assert work.events[-1]["draft_text"] == "候选新句。"
    assert restored.preview_candidate_input(result["run_id"])["messages"] == [
        {"role": m.role, "content": m.content} for m in frozen
    ]
    assert len(work.calls) == 1


def test_crashed_stream_checkpoint_becomes_partial_without_regeneration(candidate):
    work = candidate
    result, event = generate(work)
    with work.project.database.connect() as connection:
        connection.execute(
            "UPDATE generation_runs SET status='STREAMING' WHERE id=?", (result["run_id"],)
        )
    restored = work.new_writer()
    assert restored.recover_candidates()["restored"] == 1
    assert GenerationRepository(work.project).get(result["run_id"]).status == "PARTIAL"
    partial = work.events[-1]
    with pytest.raises(ValueError):
        restored.adopt_candidate(
            result["run_id"], partial["checkpoint_id"], partial["candidate_hash"]
        )
    restored.adopt_candidate(
        result["run_id"], partial["checkpoint_id"], partial["candidate_hash"], allow_partial=True
    )
    assert len(work.calls) == 1


def test_crlf_candidate_is_recovered_and_adopted_byte_exact(candidate):
    work = candidate
    work.output[0] = "第一行😀。\r\n\r\n第二行。\r\n"
    result, event = generate(work)
    assert event["can_adopt"]
    work.new_writer().recover_candidates()
    assert work.events[-1]["draft_text"] == work.output[0]
    work.writer.adopt_candidate(result["run_id"], event["checkpoint_id"], event["candidate_hash"])
    assert work.chapters.read_content_exact(work.chapter.id) == work.output[0]


@pytest.mark.parametrize("broken", ["checkpoint", "snapshot"])
def test_corrupt_asset_stays_visible_but_is_never_adopted_or_rebuilt(candidate, broken):
    work = candidate
    result, event = generate(work)
    if broken == "snapshot":
        path = work.project.layout.pipeline / "writer_inputs" / (result["run_id"] + ".json")
    else:
        checkpoint = work.writer.candidates.checkpoints.get(event["checkpoint_id"])
        path = work.project.layout.root / checkpoint.text_path
    path.write_bytes(b"corrupt test asset")
    assert work.new_writer().recover_candidates()["restored"] == 1
    card = work.events[-1]
    assert not card["can_adopt"]
    assert card["can_discard"]
    assert path.read_bytes() == b"corrupt test asset"
    assert work.chapters.read_content_exact(work.chapter.id) == work.raw
    assert work.writer.discard_candidate(
        result["run_id"], card["checkpoint_id"], card["candidate_hash"]
    )
    assert len(work.calls) == 1


def test_previous_snapshot_without_adoption_source_is_copy_only(candidate):
    work = candidate
    result, _ = generate(work)
    path = work.project.layout.pipeline / "writer_inputs" / (result["run_id"] + ".json")
    envelope = json.loads(path.read_bytes())
    del envelope["payload"]["metadata"]["adoption_source"]
    raw = json.dumps(
        envelope["payload"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    envelope["sha256"] = hashlib.sha256(raw).hexdigest()
    path.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
    work.new_writer().recover_candidates()
    assert work.events[-1]["draft_text"] == work.output[0]
    assert not work.events[-1]["can_adopt"]
    assert work.writer.preview_candidate_input(result["run_id"])["messages"]


def test_new_writer_cannot_recover_while_old_writer_holds_project_lock(candidate):
    work = candidate
    result, _ = generate(work)
    work.operation_lock.acquire()
    try:
        work.writer.revoke()
        with pytest.raises(ValueError, match="仍在处理"):
            work.new_writer().recover_candidates()
    finally:
        work.operation_lock.release()
    assert GenerationRepository(work.project).get(result["run_id"]).status == "COMPLETED"
    assert work.new_writer().recover_candidates()["restored"] == 1


def test_orphan_ready_without_output_is_closed_without_model_call(candidate):
    work = candidate
    work.output[0] = ""
    result, _ = generate(work)
    with work.project.database.connect() as connection:
        connection.execute(
            "UPDATE generation_runs SET status='READY' WHERE id=?", (result["run_id"],)
        )
    work.new_writer().recover_candidates()
    assert GenerationRepository(work.project).get(result["run_id"]).status == "FAILED"
    assert not work.events[-1]["can_adopt"]
    assert len(work.calls) == 1


def test_duplicate_adoption_and_revoked_project_cannot_change_manuscript(candidate):
    work = candidate
    result, event = generate(work)
    work.writer.adopt_candidate(result["run_id"], event["checkpoint_id"], event["candidate_hash"])
    revision = work.chapters.get_chapter(work.chapter.id).revision
    with pytest.raises(ValueError):
        work.writer.adopt_candidate(
            result["run_id"], event["checkpoint_id"], event["candidate_hash"]
        )
    assert work.chapters.get_chapter(work.chapter.id).revision == revision
    work.writer.revoke()
    with pytest.raises(ValueError):
        work.writer.recover_candidates()


@pytest.mark.parametrize("failure_mode", ["exception", "pending"])
def test_committed_revision_is_reported_even_if_index_maintenance_fails(
    candidate, monkeypatch, failure_mode
):
    work = candidate
    result, event = generate(work)

    def fail(*args, **kwargs):
        if failure_mode == "pending":
            return work.writer.candidates.revisions.pending_maintenance_result(*args, **kwargs)
        raise RuntimeError("test index failure")

    monkeypatch.setattr(work.writer.candidates.revisions, "maintain_current_revision", fail)
    accepted = work.writer.adopt_candidate(
        result["run_id"], event["checkpoint_id"], event["candidate_hash"]
    )
    assert accepted["maintenance_pending"]
    assert accepted["status"] == "ACCEPTED"
    assert work.chapters.read_content_exact(work.chapter.id) == work.output[0]
