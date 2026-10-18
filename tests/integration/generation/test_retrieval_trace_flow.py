from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_novel_studio.core.context.context_builder import (
    ContextBlock,
    ContextBuilder,
    ContextBuildRequest,
    RequiredContextOverflowError,
    RetrievalProvenance,
)
from ai_novel_studio.core.context.context_manifest import (
    ContextManifestRepository,
)
from ai_novel_studio.core.context.token_budget import TokenBudget
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class _LenEstimator:
    def estimate(self, text: str) -> int:
        return len(text)


def _hash_like(value: str) -> str:
    return "a" * 64


def _provenance_block(
    block_id: str,
    content: str,
    priority: int,
    *,
    required: bool = False,
) -> ContextBlock:
    return ContextBlock(
        id=block_id,
        category="history",
        content=content,
        priority=priority,
        required=required,
        source_type="FORMAL_MANUSCRIPT",
        source_id=f"FORMAL_MANUSCRIPT:{block_id}:0",
        source_chapter_id=None,
        source_revision=4,
        source_hash="a" * 64,
        rationale="检索命中",
        retrieval=RetrievalProvenance(
            document_id=f"doc-{block_id}",
            expanded_document_ids=(f"doc-{block_id}", f"neighbor-{block_id}"),
            source_id=f"FORMAL_MANUSCRIPT:{block_id}:0",
            source_hash="a" * 64,
            chapter_id="chapter-source",
            volume_id="volume-1",
            revision=4,
            start=10,
            end=40,
            retrieval_routes=("EXACT_PHRASE", "KEYWORD"),
            lexical_score=1.5,
            semantic_score=0.0,
            participant_boost=0.25,
            pinned_weight=0.0,
            recency_score=0.9,
            stale_penalty=0.0,
            total_score=2.65,
        ),
    )


def _plain_block(
    block_id: str,
    content: str,
    priority: int,
    *,
    required: bool = False,
) -> ContextBlock:
    return ContextBlock(
        id=block_id,
        category="rules",
        content=content,
        priority=priority,
        required=required,
        source_type="SYSTEM",
        source_id=block_id,
        source_chapter_id=None,
        source_revision=None,
        source_hash=f"hash-{block_id}",
        rationale="固定规则",
    )


def test_manifest_v3_trace_explains_selection_exclusion_and_provenance(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "project", "trace flow")
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id, "current"
    )
    body_marker = "GATE-BODY-MARKER-正文"
    built = ContextBuilder(_LenEstimator()).build(
        ContextBuildRequest(
            chapter_id=chapter.id,
            run_id="run-gate-trace",
            budget=TokenBudget(35, 20, 10),
            blocks=(
                _provenance_block("kept", "可见内容", 10),
                _provenance_block("dropped", "X" * 100, 50),
                _plain_block("plain", "普通块", 60),
            ),
        )
    )
    manifest = built.manifest
    assert manifest.schema_version == 3

    trace_by_block = {item.block_id: item for item in manifest.retrieval_trace}
    chosen = trace_by_block["kept"]
    dropped = trace_by_block["dropped"]
    assert chosen.selected is True and dropped.selected is False
    assert chosen.omission_reason is None
    assert chosen.retrieval_routes == ("EXACT_PHRASE", "KEYWORD")
    assert (chosen.start, chosen.end) == (10, 40)
    assert chosen.total_score == pytest.approx(2.65)
    omitted_item = next(
        item for item in manifest.omitted if item.block_id == "dropped"
    )
    assert dropped.omission_reason == omitted_item.reason
    assert "预算不足" in dropped.omission_reason
    assert "plain" not in trace_by_block

    repository = ContextManifestRepository(project)
    path = repository.save(manifest)
    payload = json.loads(path.read_text(encoding="utf-8"))
    rendered = json.dumps(payload, ensure_ascii=False)
    assert '"retrieval_routes"' in rendered
    assert "(EXACT_PHRASE" not in rendered
    assert body_marker not in rendered
    assert "X" * 100 not in rendered

    loaded = repository.load(manifest.id)
    assert loaded.retrieval_trace == manifest.retrieval_trace


def test_legacy_v1_and_v2_manifests_remain_readable(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "project", "legacy trace")
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id, "current"
    )
    built = ContextBuilder(_LenEstimator()).build(
        ContextBuildRequest(
            chapter_id=chapter.id,
            run_id="run-legacy",
            budget=TokenBudget(100, 20, 10),
            blocks=(_plain_block("source", "visible", 10),),
        )
    )
    repository = ContextManifestRepository(project)
    path = repository.save(built.manifest)

    payload = json.loads(path.read_text(encoding="utf-8"))
    for field in (
        "schema_version",
        "compiler_version",
        "target_chapter_revision",
        "requirement_revision",
        "retrieval_trace",
    ):
        payload.pop(field, None)
    path.write_text(json.dumps(payload), encoding="utf-8")

    legacy = repository.load(built.manifest.id)
    assert legacy.schema_version == 1
    assert legacy.compiler_version is None
    assert legacy.retrieval_trace == ()

    downgraded = json.loads(path.read_text(encoding="utf-8"))
    downgraded["schema_version"] = 2
    downgraded["compiler_version"] = "context-compiler/2.0"
    path.write_text(json.dumps(downgraded), encoding="utf-8")
    previous = repository.load(built.manifest.id)
    assert previous.schema_version == 2
    assert previous.retrieval_trace == ()

    future = json.loads(path.read_text(encoding="utf-8"))
    future["schema_version"] = 4
    path.write_text(json.dumps(future), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported context manifest"):
        repository.load(built.manifest.id)


def test_gate_failure_messages_never_leak_body_or_injected_secrets(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "project", "sanitized gate")
    chapter = ChapterRepository(project).create_chapter(
        project.list_volumes()[0].id, "current"
    )

    with pytest.raises(RequiredContextOverflowError) as overflow:
        ContextBuilder(_LenEstimator()).build(
            ContextBuildRequest(
                chapter_id=chapter.id,
                run_id="run-overflow",
                budget=TokenBudget(35, 20, 10),
                blocks=(
                    _plain_block("huge-required", "R" * 120, 1, required=True),
                    _provenance_block("evidence", "证据内容", 20),
                ),
            )
        )
    overflow_message = str(overflow.value)
    assert "huge-required" in overflow_message
    assert "R" * 120 not in overflow_message
    assert "证据内容" not in overflow_message

    built = ContextBuilder(_LenEstimator()).build(
        ContextBuildRequest(
            chapter_id=chapter.id,
            run_id="run-corrupt",
            budget=TokenBudget(200, 20, 10),
            blocks=(_plain_block("source", "visible", 10),),
        )
    )
    repository = ContextManifestRepository(project)
    path = repository.save(built.manifest)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["retrieval_trace"] = [
        {
            "block_id": "smuggled",
            "selected": True,
            "omission_reason": "SECRET-INJECTED-REASON",
            "document_id": "doc",
            "expanded_document_ids": [],
            "source_id": "src",
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

    with pytest.raises(ValueError) as corrupted:
        repository.load(built.manifest.id)
    assert str(corrupted.value) == "retrieval trace item is invalid"
    assert "SECRET-INJECTED-REASON" not in str(corrupted.value)