import pytest
import test_outline_writer_input as input_fixtures

from ai_novel_studio.domain.author_note import NoteSelection
from ai_novel_studio.infrastructure.storage.note_repository import NoteRepository

work = input_fixtures.work
prepare = input_fixtures.prepare


def test_saved_notes_are_optional_and_never_automatically_added(work):
    NoteRepository(work.project).create("文风", "PRIVATE-NOTE-EXCLUDED")
    plan = prepare(work)
    preview = work.writer.preview_input(plan["draft_id"])
    assert preview["note_mode"] == "NONE"
    assert "PRIVATE-NOTE-EXCLUDED" not in str(preview["messages"])


def test_selected_note_original_is_sent_only_after_confirmation(work):
    repo = NoteRepository(work.project)
    first = repo.create("细纲", "NOTE-ORIGINAL-ONE")
    second = repo.create("人物", "NOTE-ORIGINAL-TWO")
    work.novel.update_note_selection(NoteSelection("FULL", (second.id, first.id)))
    pending = prepare(work)
    assert work.gateway.calls == []
    preview = work.writer.preview_input(pending["draft_id"])
    body = "\n".join(m["content"] for m in preview["messages"])
    assert body.index("NOTE-ORIGINAL-TWO") < body.index("NOTE-ORIGINAL-ONE")
    assert body.index(work.raw) < body.index("NOTE-ORIGINAL-TWO") < body.index("独有细节-5")
    assert preview["note_summary"] is None
    work.writer.confirm_input(pending["draft_id"])
    assert [(m.role, m.content) for m in work.gateway.calls[0][1]] == [
        (m["role"], m["content"]) for m in preview["messages"]
    ]


def test_codex_summary_is_a_reviewable_candidate_and_originals_stay_out_of_messages(work):
    note = NoteRepository(work.project).create("注意事项", "FULL-PRIVATE-SOURCE")
    work.novel.update_note_selection(NoteSelection("SUMMARY", (note.id,)))
    pending = prepare(work, notes_summary="保留人物的克制性格。SUMMARY-TO-WRITER")
    preview = work.writer.preview_input(pending["draft_id"])
    body = "\n".join(m["content"] for m in preview["messages"])
    assert "SUMMARY-TO-WRITER" in body and "FULL-PRIVATE-SOURCE" not in body
    assert preview["note_originals"][0]["content"] == "FULL-PRIVATE-SOURCE"
    assert work.gateway.calls == []
    work.writer.confirm_input(pending["draft_id"])
    assert "FULL-PRIVATE-SOURCE" not in str(work.gateway.calls[0][1])


@pytest.mark.parametrize("change", ["revision", "mode", "order"])
def test_note_changes_invalidate_the_pending_writer_input(work, change):
    repo = NoteRepository(work.project)
    one, two = repo.create("一", "ONE"), repo.create("二", "TWO")
    work.novel.update_note_selection(NoteSelection("FULL", (one.id, two.id)))
    pending = prepare(work)
    if change == "revision":
        repo.save(one.id, "NEW", expected_revision=1)
    elif change == "mode":
        work.novel.update_note_selection(NoteSelection())
    else:
        work.novel.update_note_selection(NoteSelection("FULL", (two.id, one.id)))
    with pytest.raises(ValueError):
        work.writer.confirm_input(pending["draft_id"])
    assert work.gateway.calls == []


def test_summary_cannot_bypass_the_author_note_mode(work):
    with pytest.raises(ValueError):
        prepare(work, notes_summary="作者未选择笔记，不能偷偷附上")
    assert work.gateway.calls == []
