import json
from dataclasses import replace
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
from ai_novel_studio.core.context.context_ranking import ContextTask
from ai_novel_studio.core.context.token_budget import TokenBudget
from ai_novel_studio.domain.identifiers import new_id
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


def test_builder_ranks_task_matching_optional_evidence_before_static_priority_noise() -> None:
    builder = ContextBuilder(CharacterEstimator())
    request = ContextBuildRequest(
        chapter_id="chapter-current",
        run_id="run-task-ranking",
        budget=TokenBudget(25, 5, 0),
        blocks=(
            _block("rules", "RULES", 1, required=True),
            _block("priority-noise", "N" * 15, 2),
            _block("relevant-evidence", "旧暗号", 50),
        ),
        task=ContextTask(
            task_type="PROSE_GENERATION",
            query_text="主角必须认出旧暗号",
        ),
    )

    built = builder.build(request)

    assert [item.block_id for item in built.manifest.selected] == [
        "rules",
        "relevant-evidence",
    ]
    assert built.manifest.omitted[-1].block_id == "priority-noise"
    assert "TASK_RELEVANCE:NO_MATCH" in built.manifest.omitted[-1].reason
    assert "TASK_RELEVANCE" in built.manifest.selected[-1].rationale


def test_builder_reserves_one_ranked_block_for_each_guaranteed_category() -> None:
    builder = ContextBuilder(CharacterEstimator())
    request = ContextBuildRequest(
        chapter_id="chapter-current",
        run_id="run-budget-guarantee",
        budget=TokenBudget(30, 10, 0),
        blocks=(
            _block("rules", "RULES", 1, required=True),
            _block("recent", "R" * 10, 10, category="RECENT_FULL"),
            _block("matching-memory", "旧暗号" * 5, 20, category="MEMORY"),
        ),
        task=ContextTask(
            task_type="PROSE_GENERATION",
            query_text="必须认出旧暗号",
        ),
        minimum_category_coverage=("RECENT_FULL",),
    )

    built = builder.build(request)

    assert [item.block_id for item in built.manifest.selected] == [
        "rules",
        "recent",
    ]
    assert built.manifest.omitted[-1].block_id == "matching-memory"


def test_builder_uses_whole_fallback_to_meet_category_coverage() -> None:
    builder = ContextBuilder(CharacterEstimator())
    request = ContextBuildRequest(
        chapter_id="chapter-current",
        run_id="run-budget-guarantee-fallback",
        budget=TokenBudget(22, 10, 0),
        blocks=(
            _block("rules", "RULES", 1, required=True),
            _block(
                "recent",
                "R" * 10,
                10,
                category="RECENT_FULL",
                fallback="S" * 5,
            ),
        ),
        minimum_category_coverage=("RECENT_FULL",),
    )

    built = builder.build(request)

    assert built.manifest.selected[-1].block_id == "recent"
    assert built.manifest.selected[-1].used_fallback is True
    assert built.text.endswith("S" * 5)


def test_builder_warns_when_available_category_coverage_cannot_fit() -> None:
    builder = ContextBuilder(CharacterEstimator())
    request = ContextBuildRequest(
        chapter_id="chapter-current",
        run_id="run-budget-guarantee-unmet",
        budget=TokenBudget(20, 10, 0),
        blocks=(
            _block("rules", "R" * 8, 1, required=True),
            _block(
                "recent",
                "F" * 10,
                10,
                category="RECENT_FULL",
                fallback="S" * 3,
            ),
        ),
        minimum_category_coverage=("RECENT_FULL",),
    )

    built = builder.build(request)

    assert built.manifest.warnings == (
        "BUDGET_GUARANTEE_UNMET:RECENT_FULL",
    )
    assert built.manifest.selected[0].block_id == "rules"
    assert built.manifest.omitted[-1].block_id == "recent"


def test_context_request_rejects_duplicate_or_blank_category_coverage() -> None:
    common = {
        "chapter_id": "chapter-current",
        "run_id": "run-invalid-budget-guarantee",
        "budget": TokenBudget(100, 10, 0),
        "blocks": (),
    }

    with pytest.raises(ValueError, match="duplicates"):
        ContextBuildRequest(
            **common,
            minimum_category_coverage=("RECENT_FULL", "RECENT_FULL"),
        )
    with pytest.raises(ValueError, match="cannot be blank"):
        ContextBuildRequest(
            **common,
            minimum_category_coverage=(" ",),
        )


def test_context_task_bounds_oversized_ranking_query() -> None:
    task = ContextTask(
        task_type=" PROSE_GENERATION ",
        query_text="x" * 25_000,
    )

    assert task.task_type == "PROSE_GENERATION"
    assert len(task.query_text) == 20_000


def test_builder_deduplicates_ranked_optional_content_but_preserves_required_blocks() -> None:
    builder = ContextBuilder(CharacterEstimator())
    request = ContextBuildRequest(
        chapter_id="chapter-current",
        run_id="run-deduplication",
        budget=TokenBudget(100, 10, 0),
        blocks=(
            _block("required-a", "RULES", 1, required=True),
            _block("required-b", "RULES", 2, required=True),
            _block("canonical-card", "人物卡：艾瑞克", 10),
            _block("alias-card", "  人物卡：艾瑞克  ", 11),
        ),
        deduplicate=True,
    )

    built = builder.build(request)

    assert [item.block_id for item in built.manifest.selected] == [
        "required-a",
        "required-b",
        "canonical-card",
    ]
    duplicate = built.manifest.omitted[0]
    assert duplicate.block_id == "alias-card"
    assert duplicate.reason == "DEDUPLICATED:canonical-card"


def test_builder_keeps_same_full_content_when_fallback_representations_differ() -> None:
    builder = ContextBuilder(CharacterEstimator())
    built = builder.build(
        ContextBuildRequest(
            chapter_id="chapter-current",
            run_id="run-deduplication-fallback",
            budget=TokenBudget(100, 10, 0),
            blocks=(
                _block("full-only", "same full content", 10),
                _block(
                    "with-fallback",
                    "same full content",
                    11,
                    fallback="distinct summary",
                ),
            ),
            deduplicate=True,
        )
    )

    assert [item.block_id for item in built.manifest.selected] == [
        "full-only",
        "with-fallback",
    ]
    assert built.manifest.omitted == ()


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
            target_chapter_revision=current.revision,
            requirement_revision=12,
        )
    )

    path = ContextManifestRepository(project).save(built.manifest)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["chapter_id"] == current.id
    assert payload["schema_version"] == 3
    assert payload["compiler_version"] == "context-compiler/2.0"
    assert payload["target_chapter_revision"] == current.revision
    assert payload["requirement_revision"] == 12
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


def test_context_manifest_loads_legacy_v1_json_with_explicit_metadata(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "project", "legacy manifest")
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id,
        "current",
    )
    manifest = ContextBuilder(CharacterEstimator()).build(
        ContextBuildRequest(
            chapter_id=chapter.id,
            run_id="run-legacy",
            budget=TokenBudget(100, 20, 10),
            blocks=(_block("source", "visible", 10),),
        )
    ).manifest
    repository = ContextManifestRepository(project)
    path = repository.save(manifest)
    payload = json.loads(path.read_text(encoding="utf-8"))
    for field in (
        "schema_version",
        "compiler_version",
        "target_chapter_revision",
        "requirement_revision",
    ):
        payload.pop(field, None)
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = repository.load(manifest.id)

    assert loaded.schema_version == 1
    assert loaded.compiler_version is None
    assert loaded.target_chapter_revision is None
    assert loaded.requirement_revision is None
    with pytest.raises(ValueError, match="new context manifest"):
        repository.save(replace(loaded, id=new_id()))


@pytest.mark.parametrize("schema_version", [None, 4])
def test_context_manifest_rejects_explicit_invalid_schema(
    tmp_path: Path,
    schema_version: int | None,
) -> None:
    project = ProjectRepository.create(tmp_path / "project", "future manifest")
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id,
        "current",
    )
    manifest = ContextBuilder(CharacterEstimator()).build(
        ContextBuildRequest(
            chapter_id=chapter.id,
            run_id="run-future",
            budget=TokenBudget(100, 20, 10),
            blocks=(_block("source", "visible", 10),),
        )
    ).manifest
    repository = ContextManifestRepository(project)
    path = repository.save(manifest)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema_version"] = schema_version
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="schema version"):
        repository.load(manifest.id)


@pytest.mark.parametrize(
    ("schema_version", "compiler_version"),
    [
        (3, None),
        (2, None),
        (2, "context-compiler/other"),
    ],
)
def test_context_manifest_rejects_direct_invalid_version_contract(
    schema_version: int,
    compiler_version: str | None,
) -> None:
    manifest = ContextBuilder(CharacterEstimator()).build(
        ContextBuildRequest(
            chapter_id="chapter-current",
            run_id="run-invalid",
            budget=TokenBudget(100, 20, 10),
            blocks=(_block("source", "visible", 10),),
        )
    ).manifest

    with pytest.raises(ValueError, match="context manifest"):
        replace(
            manifest,
            schema_version=schema_version,
            compiler_version=compiler_version,
        )


def _provenance_block(
    block_id: str,
    content: str,
    priority: int,
    *,
    required: bool = False,
    source_chapter_id: str = "chapter-source",
    source_revision: int = 4,
    source_hash: str | None = None,
    provenance_overrides: dict[str, object] | None = None,
) -> ContextBlock:
    from ai_novel_studio.core.context.context_builder import RetrievalProvenance

    hash_value = source_hash or "a" * 64
    provenance_fields: dict[str, object] = {
        "document_id": f"doc-{block_id}",
        "expanded_document_ids": (f"doc-{block_id}", f"neighbor-{block_id}"),
        "source_id": f"FORMAL_MANUSCRIPT:{block_id}:0",
        "chapter_id": source_chapter_id,
        "volume_id": "volume-1",
        "revision": source_revision,
        "source_hash": hash_value,
        "start": 10,
        "end": 40,
        "retrieval_routes": ("EXACT_PHRASE", "KEYWORD"),
        "lexical_score": 1.5,
        "semantic_score": 0.0,
        "participant_boost": 0.25,
        "pinned_weight": 0.0,
        "recency_score": 0.9,
        "stale_penalty": 0.0,
        "total_score": 2.65,
    }
    if provenance_overrides:
        provenance_fields.update(provenance_overrides)
    return ContextBlock(
        id=block_id,
        category="history",
        content=content,
        priority=priority,
        required=required,
        source_type="FORMAL_MANUSCRIPT",
        source_id=str(provenance_fields["source_id"]),
        source_chapter_id=source_chapter_id,
        source_revision=source_revision,
        source_hash=hash_value,
        rationale="检索命中",
        retrieval=RetrievalProvenance(**provenance_fields),  # type: ignore[arg-type]
    )


def test_builder_records_retrieval_trace_for_selected_and_omitted_blocks() -> None:
    selected_block = _provenance_block("trace-selected", "可见内容", 10)
    omitted_block = _provenance_block("trace-omitted", "X" * 500, 50)
    plain_block = _block("plain", "无溯源", 60)

    built = ContextBuilder(CharacterEstimator()).build(
        ContextBuildRequest(
            chapter_id="chapter-current",
            run_id="run-trace",
            budget=TokenBudget(120, 20, 10),
            blocks=(selected_block, omitted_block, plain_block),
        )
    )

    manifest = built.manifest
    assert manifest.schema_version == 3
    trace = manifest.retrieval_trace
    assert [item.block_id for item in trace] == ["trace-selected", "trace-omitted"]
    chosen = trace[0]
    dropped = trace[1]
    assert chosen.selected is True
    assert chosen.omission_reason is None
    assert chosen.retrieval_routes == ("EXACT_PHRASE", "KEYWORD")
    assert chosen.total_score == 2.65
    assert dropped.selected is False
    omitted_item = next(
        item for item in manifest.omitted if item.block_id == "trace-omitted"
    )
    assert dropped.omission_reason == omitted_item.reason
    selected_ids = {item.block_id for item in manifest.selected}
    omitted_ids = {item.block_id for item in manifest.omitted}
    for item in trace:
        target_ids = selected_ids if item.selected else omitted_ids
        assert item.block_id in target_ids


def test_v3_manifest_roundtrips_retrieval_trace_without_body_text(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "project", "trace roundtrip")
    chapters = ChapterRepository(project)
    chapter = chapters.create_chapter(project.list_volumes()[0].id, "current")
    with project.database.connect() as connection:
        row = connection.execute(
            "SELECT revision, content_hash FROM chapters WHERE id = ?",
            (chapter.id,),
        ).fetchone()
    body_marker = "TRACE-BODY-MARKER-正文"
    built = ContextBuilder(CharacterEstimator()).build(
        ContextBuildRequest(
            chapter_id=chapter.id,
            run_id="run-roundtrip",
            budget=TokenBudget(200, 20, 10),
            blocks=(
                _provenance_block(
                    "kept",
                    body_marker,
                    10,
                    source_chapter_id=chapter.id,
                    source_revision=int(row["revision"]),
                    source_hash=str(row["content_hash"]),
                ),
                _block("plain", "普通块", 20),
            ),
        )
    )
    repository = ContextManifestRepository(project)
    path = repository.save(built.manifest)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 3
    assert len(payload["retrieval_trace"]) == 1
    assert body_marker not in json.dumps(payload, ensure_ascii=False)
    loaded = repository.load(built.manifest.id)

    assert loaded.schema_version == 3
    assert loaded.retrieval_trace == built.manifest.retrieval_trace


def test_v2_manifest_still_loads_with_empty_trace(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "project", "v2 compat")
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id,
        "current",
    )
    built = ContextBuilder(CharacterEstimator()).build(
        ContextBuildRequest(
            chapter_id=chapter.id,
            run_id="run-v2",
            budget=TokenBudget(100, 20, 10),
            blocks=(_block("source", "visible", 10),),
        )
    )
    repository = ContextManifestRepository(project)
    path = repository.save(built.manifest)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema_version"] = 2
    payload.pop("retrieval_trace", None)
    path.write_text(json.dumps(payload), encoding="utf-8")

    loaded = repository.load(built.manifest.id)
    assert loaded.schema_version == 2
    assert loaded.retrieval_trace == ()

    payload["retrieval_trace"] = [
        {
            "block_id": "smuggled",
            "selected": True,
            "omission_reason": None,
            "document_id": "d",
            "expanded_document_ids": [],
            "source_id": "s",
            "chapter_id": None,
            "volume_id": None,
            "revision": None,
            "source_hash": "h",
            "start": None,
            "end": None,
            "retrieval_routes": [],
            "lexical_score": 0,
            "semantic_score": 0,
            "participant_boost": 0,
            "pinned_weight": 0,
            "recency_score": 0,
            "stale_penalty": 0,
            "total_score": 0,
        }
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")
    reloaded = repository.load(built.manifest.id)
    assert reloaded.schema_version == 2
    assert reloaded.retrieval_trace == ()


def test_retrieval_trace_item_validation_rejects_bad_rows() -> None:
    from ai_novel_studio.core.context.context_manifest import RetrievalTraceItem

    base: dict[str, object] = {
        "block_id": "b",
        "selected": True,
        "omission_reason": None,
        "document_id": "doc",
        "expanded_document_ids": ("doc",),
        "source_id": "src",
        "chapter_id": None,
        "volume_id": None,
        "revision": 1,
        "source_hash": "a" * 64,
        "start": None,
        "end": None,
        "retrieval_routes": ("KEYWORD",),
        "lexical_score": 0.0,
        "semantic_score": 0.0,
        "participant_boost": 0.0,
        "pinned_weight": 0.0,
        "recency_score": 0.0,
        "stale_penalty": 0.0,
        "total_score": 0.0,
    }
    assert RetrievalTraceItem(**base).block_id == "b"

    def broken(**changes: object) -> dict[str, object]:
        row = dict(base)
        row.update(changes)
        return row

    with pytest.raises(ValueError):
        RetrievalTraceItem(**broken(selected=False))
    with pytest.raises(ValueError):
        RetrievalTraceItem(**broken(omission_reason="dropped"))
    with pytest.raises(ValueError):
        RetrievalTraceItem(**broken(start=40, end=10))
    with pytest.raises(ValueError):
        RetrievalTraceItem(**broken(end=10))
    with pytest.raises(ValueError):
        RetrievalTraceItem(**broken(revision=-1))
    with pytest.raises(ValueError):
        RetrievalTraceItem(**broken(total_score=True))
    with pytest.raises(ValueError):
        RetrievalTraceItem(**broken(document_id=""))


def test_manifest_save_rolls_back_file_when_database_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sqlite3

    from ai_novel_studio.infrastructure.storage.database import Database

    project = ProjectRepository.create(tmp_path / "project", "rollback")
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id,
        "current",
    )
    manifest = ContextBuilder(CharacterEstimator()).build(
        ContextBuildRequest(
            chapter_id=chapter.id,
            run_id="run-rollback",
            budget=TokenBudget(100, 20, 10),
            blocks=(_block("source", "visible", 10),),
        )
    ).manifest
    repository = ContextManifestRepository(project)
    expected_path = (
        project.layout.pipeline / "manifests" / f"context_{manifest.id}.json"
    )

    def broken_connect(self: Database) -> object:
        raise sqlite3.OperationalError("database is closed")

    monkeypatch.setattr(Database, "connect", broken_connect)
    with pytest.raises(sqlite3.OperationalError):
        repository.save(manifest)

    assert not expected_path.exists()


def _valid_trace_row() -> dict[str, object]:
    return {
        "block_id": "kept",
        "selected": True,
        "omission_reason": None,
        "document_id": "doc-kept",
        "expanded_document_ids": ("doc-kept", "neighbor"),
        "source_id": "FORMAL_MANUSCRIPT:src:0",
        "chapter_id": None,
        "volume_id": None,
        "revision": 1,
        "source_hash": "a" * 64,
        "start": 0,
        "end": 5,
        "retrieval_routes": ("KEYWORD",),
        "lexical_score": 1.0,
        "semantic_score": 0.0,
        "participant_boost": 0.0,
        "pinned_weight": 0.0,
        "recency_score": 0.0,
        "stale_penalty": 0.0,
        "total_score": 1.0,
    }


def test_retrieval_trace_item_fails_closed_on_nan_and_identity_gaps() -> None:
    from ai_novel_studio.core.context.context_manifest import RetrievalTraceItem

    base = _valid_trace_row()

    def broken(**changes: object) -> dict[str, object]:
        row = dict(base)
        row.update(changes)
        return row

    assert RetrievalTraceItem(**base).block_id == "kept"

    cases = (
        {"lexical_score": float("nan")},
        {"total_score": float("inf")},
        {"semantic_score": -float("inf")},
        {"source_hash": "not-a-sha256"},
        {"source_hash": "A" * 64},
        {"expanded_document_ids": ()},
        {"expanded_document_ids": ("neighbor",)},
        {"expanded_document_ids": ("doc-kept", "doc-kept")},
        {"retrieval_routes": ()},
        {"retrieval_routes": ("UNKNOWN",)},
        {"retrieval_routes": ("KEYWORD", "KEYWORD")},
        {"retrieval_routes": ("keyword",)},
    )
    for changes in cases:
        with pytest.raises(ValueError):
            RetrievalTraceItem(**broken(**changes))


def test_manifest_rejects_orphan_mislabeled_and_duplicate_trace_rows(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "project", "orphan trace")
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id, "current"
    )
    with project.database.connect() as connection:
        chapter_row = connection.execute(
            "SELECT revision, content_hash FROM chapters WHERE id = ?",
            (chapter.id,),
        ).fetchone()
    built = ContextBuilder(CharacterEstimator()).build(
        ContextBuildRequest(
            chapter_id=chapter.id,
            run_id="run-orphan",
            budget=TokenBudget(200, 20, 10),
            blocks=(
                _provenance_block(
                    "kept",
                    "可见内容",
                    10,
                    source_chapter_id=chapter.id,
                    source_revision=int(chapter_row["revision"]),
                    source_hash=str(chapter_row["content_hash"]),
                ),
            ),
        )
    )
    from ai_novel_studio.core.context.context_manifest import RetrievalTraceItem

    repository = ContextManifestRepository(project)

    with pytest.raises(ValueError, match="context manifest retrieval trace"):
        replace(
            built.manifest,
            retrieval_trace=(
                *built.manifest.retrieval_trace,
                RetrievalTraceItem(
                    **{  # type: ignore[arg-type]
                        **_valid_trace_row(),
                        "block_id": "orphan",
                        "document_id": "doc-orphan",
                        "expanded_document_ids": ("doc-orphan",),
                    }
                ),
            ),
        )

    mislabeled_rows = [
        {**row, "selected": False, "omission_reason": "预算不足"}
        for row in [json.loads(json.dumps(_valid_trace_row()))]
    ]
    path = repository.save(built.manifest)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["retrieval_trace"] = mislabeled_rows
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="context manifest retrieval trace"):
        repository.load(built.manifest.id)

    duplicated = json.loads(path.read_text(encoding="utf-8"))
    duplicated["schema_version"] = 3
    duplicated["retrieval_trace"] = [
        json.loads(json.dumps(_valid_trace_row())),
        json.loads(json.dumps(_valid_trace_row())),
    ]
    path.write_text(json.dumps(duplicated), encoding="utf-8")
    with pytest.raises(ValueError, match="context manifest retrieval trace"):
        repository.load(built.manifest.id)


def test_manifest_rejects_duplicate_selected_block_ids() -> None:
    chapter_free_manifest = ContextBuilder(CharacterEstimator()).build(
        ContextBuildRequest(
            chapter_id="chapter-current",
            run_id="run-dup",
            budget=TokenBudget(100, 20, 10),
            blocks=(_block("dup", "内容", 10),),
        )
    ).manifest

    with pytest.raises(ValueError, match="context manifest block identity"):
        replace(
            chapter_free_manifest,
            selected=chapter_free_manifest.selected
            + chapter_free_manifest.selected[:1],
        )


def test_loader_unknown_trace_field_fails_fixed_without_payload_leak(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "project", "unknown field")
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id, "current"
    )
    built = ContextBuilder(CharacterEstimator()).build(
        ContextBuildRequest(
            chapter_id=chapter.id,
            run_id="run-unknown",
            budget=TokenBudget(100, 20, 10),
            blocks=(_block("source", "visible", 10),),
        )
    )
    repository = ContextManifestRepository(project)
    path = repository.save(built.manifest)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["retrieval_trace"] = [
        {
            **json.loads(json.dumps(_valid_trace_row())),
            "smuggled_field": "SECRET-INJECTION",
        }
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError) as caught:
        repository.load(built.manifest.id)

    assert str(caught.value) == "retrieval trace item is invalid"
    assert "SECRET-INJECTION" not in str(caught.value)
