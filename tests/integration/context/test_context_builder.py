import json
from pathlib import Path

import pytest

from ai_novel_studio.core.context.context_builder import (
    ContextBlock,
    ContextBuilder,
    ContextBuildRequest,
    RequiredContextOverflowError,
)
from ai_novel_studio.core.context.context_filter import ContextEligibility
from ai_novel_studio.core.context.context_manifest import ContextManifestRepository
from ai_novel_studio.core.context.token_budget import TokenBudget
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class CharacterEstimator:
    def estimate(self, text: str) -> int:
        return len(text)


def _block(
    block_id: str,
    content: str,
    priority: int,
    *,
    required: bool = False,
    fallback: str | None = None,
    category: str = "history",
    eligibility: ContextEligibility | None = None,
) -> ContextBlock:
    return ContextBlock(
        id=block_id,
        category=category,
        content=content,
        priority=priority,
        required=required,
        source_type="CHAPTER",
        source_id=block_id,
        source_chapter_id=None,
        source_revision=None,
        source_hash="hash-" + block_id,
        rationale="测试选择顺序",
        fallback_content=fallback,
        eligibility=eligibility or ContextEligibility(),
    )


def test_builder_hard_filters_ineligible_blocks_before_required_and_budget_selection() -> None:
    builder = ContextBuilder(CharacterEstimator())
    request = ContextBuildRequest(
        chapter_id="chapter-current",
        run_id="run-hard-filter",
        budget=TokenBudget(500, 50, 10),
        blocks=(
            _block("eligible", "visible", 10),
            _block(
                "other-project",
                "foreign",
                1,
                eligibility=ContextEligibility(project_scope_matches=False),
            ),
            _block(
                "old-revision",
                "superseded",
                1,
                eligibility=ContextEligibility(revision_current=False),
            ),
            _block(
                "future-required",
                "must-not-leak",
                1,
                required=True,
                eligibility=ContextEligibility(time_visible=False),
            ),
            _block(
                "wrong-view",
                "hidden",
                2,
                eligibility=ContextEligibility(view_allowed=False),
            ),
            _block(
                "stale",
                "old",
                3,
                eligibility=ContextEligibility(stale=True),
            ),
            _block(
                "source-changed",
                "pending-review",
                4,
                eligibility=ContextEligibility(source_changed=True),
            ),
            _block(
                "conflicted",
                "ambiguous",
                5,
                eligibility=ContextEligibility(conflicted=True),
            ),
            _block(
                "unapproved",
                "candidate",
                6,
                eligibility=ContextEligibility(authority_allowed=False),
            ),
        ),
    )

    built = builder.build(request)

    assert [item.block_id for item in built.manifest.selected] == ["eligible"]
    assert [item.block_id for item in built.manifest.omitted] == [
        "future-required",
        "old-revision",
        "other-project",
        "wrong-view",
        "stale",
        "source-changed",
        "conflicted",
        "unapproved",
    ]
    reasons = {item.block_id: item.reason for item in built.manifest.omitted}
    assert "PROJECT_SCOPE" in reasons["other-project"]
    assert "REVISION_INVALID" in reasons["old-revision"]
    assert "TIME_BOUNDARY" in reasons["future-required"]
    assert "VIEW_BOUNDARY" in reasons["wrong-view"]
    assert "STALE" in reasons["stale"]
    assert "SOURCE_CHANGED" in reasons["source-changed"]
    assert "CONFLICTED" in reasons["conflicted"]
    assert "AUTHORITY_REJECTED" in reasons["unapproved"]
    assert "must-not-leak" not in built.text


def test_required_context_overflow_is_explicit_and_never_truncated() -> None:
    builder = ContextBuilder(CharacterEstimator())
    request = ContextBuildRequest(
        chapter_id="chapter-current",
        run_id="run-1",
        budget=TokenBudget(50, 10, 10),
        blocks=(_block("required", "R" * 31, 1, required=True),),
    )

    with pytest.raises(RequiredContextOverflowError, match="required"):
        builder.build(request)


def test_builder_prefers_previous_full_chapter_then_uses_whole_summary_fallback() -> None:
    builder = ContextBuilder(CharacterEstimator())
    request = ContextBuildRequest(
        chapter_id="chapter-current",
        run_id="run-2",
        budget=TokenBudget(50, 10, 10),
        blocks=(
            _block("rules", "R" * 10, 1, required=True, category="hard_constraint"),
            _block("previous", "P" * 15, 10, category="recent_full_chapter"),
            _block("older", "O" * 15, 20, fallback="S" * 5),
            _block("volume", "V" * 10, 30, category="volume_summary"),
        ),
    )

    built = builder.build(request)

    assert [item.block_id for item in built.manifest.selected] == [
        "rules",
        "previous",
        "older",
    ]
    assert built.manifest.selected[-1].used_fallback is True
    assert built.manifest.selected[-1].estimated_tokens == 5
    assert built.manifest.omitted[0].block_id == "volume"
    assert "预算不足" in built.manifest.omitted[0].reason
    assert "P" * 15 in built.text
    assert "S" * 5 in built.text
    assert "O" * 15 not in built.text


def test_context_manifest_persists_sources_omissions_and_dependency(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "project", "上下文测试")
    volume = project.list_volumes()[0]
    chapters = ChapterRepository(project)
    source = chapters.create_chapter(volume.id, "来源章", "1", "来源正文")
    current = chapters.create_chapter(volume.id, "当前章", "2", "")
    builder = ContextBuilder(CharacterEstimator())
    with project.database.connect() as connection:
        row = connection.execute(
            "SELECT revision, content_hash FROM chapters WHERE id = ?", (source.id,)
        ).fetchone()
    block = ContextBlock(
        id="source-full",
        category="recent_full_chapter",
        content="来源正文",
        priority=10,
        required=False,
        source_type="CHAPTER",
        source_id=source.id,
        source_chapter_id=source.id,
        source_revision=int(row["revision"]),
        source_hash=row["content_hash"],
        rationale="上一章全文",
    )
    built = builder.build(
        ContextBuildRequest(
            chapter_id=current.id,
            run_id="run-context",
            budget=TokenBudget(100, 20, 10),
            blocks=(block, _block("too-large", "X" * 100, 50)),
        )
    )

    path = ContextManifestRepository(project).save(built.manifest)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["chapter_id"] == current.id
    assert payload["selected"][0]["source_id"] == source.id
    assert payload["omitted"][0]["block_id"] == "too-large"
    with project.database.connect() as connection:
        manifest_row = connection.execute(
            "SELECT status FROM context_manifests WHERE id = ?", (built.manifest.id,)
        ).fetchone()
        dependency = connection.execute(
            "SELECT memory_type FROM memory_dependencies WHERE memory_id = ?",
            (built.manifest.id,),
        ).fetchone()
    assert manifest_row["status"] == "CURRENT"
    assert dependency["memory_type"] == "MANIFEST"
