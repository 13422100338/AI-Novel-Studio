from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ai_novel_studio.application.chapter_revision_service import ChapterRevisionService
from ai_novel_studio.application.formal_evidence_query_service import (
    FormalEvidenceQueryRequest,
    FormalEvidenceQueryService,
)
from ai_novel_studio.application.formal_manuscript_evidence_service import (
    FormalManuscriptEvidenceService,
)
from ai_novel_studio.core.context.context_builder import (
    ContextBuilder,
    ContextBuildRequest,
)
from ai_novel_studio.core.context.evidence_context import (
    EVIDENCE_CATEGORY,
    EVIDENCE_SOURCE_TYPE,
    EvidenceContextAdapter,
    EvidenceContextOptions,
)
from ai_novel_studio.core.context.history_retriever import HistoryRetriever
from ai_novel_studio.core.context.token_budget import TokenBudget
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.search_repository import SearchRepository
from ai_novel_studio.infrastructure.storage.subject_repository import SubjectRepository

_CONTENT = "第一段😀\r\n\r\n第二段证据\r\n"
_QUERY = "第二段证据"


def _source_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _evidence(tmp_path: Path):
    project = ProjectRepository.create(tmp_path / "novel", "Evidence injection")
    volume = project.list_volumes()[0]
    revisions = ChapterRevisionService(project)
    source = revisions.submit_creation(
        volume.id, "Evidence source", content=_CONTENT
    ).chapter
    target = revisions.submit_creation(
        volume.id, "Generation target", content="target"
    ).chapter
    search = SearchRepository(project)
    service = FormalEvidenceQueryService(
        HistoryRetriever(search),
        SubjectRepository(project),
        FormalManuscriptEvidenceService(search),
    )
    evidence = service.query(FormalEvidenceQueryRequest(_QUERY, target.id))
    return evidence, source, target


def test_adapter_converts_evidence_with_provenance(tmp_path: Path) -> None:
    evidence, source, _target = _evidence(tmp_path)

    blocks = EvidenceContextAdapter().to_blocks(evidence)

    assert len(blocks) == 1
    block = blocks[0]
    assert block.category == EVIDENCE_CATEGORY
    assert block.source_type == EVIDENCE_SOURCE_TYPE
    assert block.content == _CONTENT
    assert block.source_chapter_id == source.id
    assert block.source_revision == source.revision
    assert block.source_hash == _source_hash(_CONTENT)
    assert "routes=" in block.rationale
    assert block.required is False
    assert block.priority == 50


def test_adapter_respects_options(tmp_path: Path) -> None:
    evidence, _source, _target = _evidence(tmp_path)

    blocks = EvidenceContextAdapter(
        EvidenceContextOptions(priority=10, required=True)
    ).to_blocks(evidence)

    assert blocks[0].priority == 10
    assert blocks[0].required is True


def test_adapter_returns_no_blocks_for_empty_evidence(tmp_path: Path) -> None:
    evidence, _source, target = _evidence(tmp_path)
    empty = FormalEvidenceQueryService(
        HistoryRetriever(SearchRepository(
            ProjectRepository.open(tmp_path / "novel")
        )),
        SubjectRepository(ProjectRepository.open(tmp_path / "novel")),
        FormalManuscriptEvidenceService(SearchRepository(
            ProjectRepository.open(tmp_path / "novel")
        )),
    ).query(FormalEvidenceQueryRequest("绝不存在的内容xyz", target.id))

    blocks = EvidenceContextAdapter().to_blocks(empty)

    assert blocks == ()


def test_adapter_rejects_non_evidence_input(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        EvidenceContextAdapter().to_blocks("not evidence")


def test_blocks_flow_into_context_builder_with_manifest_provenance(
    tmp_path: Path,
) -> None:
    evidence, source, target = _evidence(tmp_path)

    blocks = EvidenceContextAdapter().to_blocks(evidence)
    built = ContextBuilder().build(
        ContextBuildRequest(
            chapter_id=target.id,
            run_id=None,
            budget=TokenBudget(4096, 512, 128),
            blocks=blocks,
        )
    )

    selected = built.manifest.selected
    assert len(selected) == 1
    item = selected[0]
    assert item.category == EVIDENCE_CATEGORY
    assert item.source_chapter_id == source.id
    assert item.source_revision == source.revision
    assert item.source_hash == _source_hash(_CONTENT)
    assert blocks[0].content in built.text
