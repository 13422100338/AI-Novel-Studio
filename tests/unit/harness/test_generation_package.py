from __future__ import annotations

import hashlib

import pytest

from ai_novel_studio.domain.generation import AuditPolicy, GenerationProfile
from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.harness.generation_package import (
    EditorSnapshot,
    GenerationPackage,
    MergeOutcome,
    SnapshotState,
    classify_snapshot,
    classify_three_way,
)


def _snapshot(content: str = "正文", revision: int = 3) -> EditorSnapshot:
    return EditorSnapshot(
        str(new_id()),
        content,
        revision,
        hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )


def test_snapshot_classification() -> None:
    base = _snapshot("a", 3)
    same = _snapshot("a", 3)
    assert classify_snapshot(base, same) is SnapshotState.CURRENT

    revised = _snapshot("a", 4)
    assert classify_snapshot(base, revised) is SnapshotState.STALE_BUT_REBASABLE

    rewritten = EditorSnapshot(base.chapter_id, "b", 3, hashlib.sha256(b"b").hexdigest())
    assert classify_snapshot(base, rewritten) is SnapshotState.STALE_CONFLICTED


def test_three_way_classification() -> None:
    base = _snapshot("a")
    ours_clean = _snapshot("a")
    theirs_changed = _snapshot("b")
    assert (
        classify_three_way(base, ours_clean, theirs_changed)
        is MergeOutcome.CLEAN_APPLY
    )
    assert (
        classify_three_way(base, theirs_changed, ours_clean)
        is MergeOutcome.NO_CHANGE
    )
    assert (
        classify_three_way(base, _snapshot("x"), _snapshot("y"))
        is MergeOutcome.NEEDS_REVIEW
    )


def _package(**overrides: object) -> GenerationPackage:
    chapter_id = str(new_id())
    fields: dict[str, object] = dict(
        chapter_id=chapter_id,
        editor_snapshot=EditorSnapshot(
            chapter_id, "正文", 1, hashlib.sha256("正文".encode()).hexdigest()
        ),
        formal_revision=1,
        generation_profile=GenerationProfile.NORMAL,
        audit_policy=AuditPolicy.STANDARD,
        goal="写完雨夜重逢",
    )
    fields.update(overrides)
    return GenerationPackage(**fields)


def test_package_validation_and_normalization() -> None:
    with pytest.raises(ValueError):
        _package(goal=" ")
    with pytest.raises(ValueError):
        _package(editor_snapshot=EditorSnapshot(
            str(new_id()), "正文", 1, hashlib.sha256("正文".encode()).hexdigest()
        ))
    with pytest.raises(ValueError):
        _package(formal_revision=-1)

    package = _package(must_happen=(" 事件甲 ", "事件甲", " "), unresolved=("结尾未定",))
    assert package.must_happen == ("事件甲",)
    assert package.ready_for_draft_model is False
    assert "unresolved plot decisions" in package.draft_blocked_reasons[0]
    assert _package().ready_for_draft_model is True
