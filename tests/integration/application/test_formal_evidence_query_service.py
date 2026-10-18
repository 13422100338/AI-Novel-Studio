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
    EvidenceOutcome,
    FormalManuscriptEvidenceService,
)
from ai_novel_studio.core.context.history_retriever import HistoryRetriever
from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.search_repository import (
    FORMAL_MANUSCRIPT_DOCUMENT_TYPE,
    MAX_FORMAL_EVIDENCE_CANDIDATES,
    SearchRepository,
)
from ai_novel_studio.infrastructure.storage.subject_repository import SubjectRepository

_CONTENT = "第一段😀\r\n\r\n第二段证据\r\n"
_QUERY = "第二段证据"


def _source_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _service(tmp_path: Path) -> tuple:
    project = ProjectRepository.create(tmp_path / "novel", "R3b query")
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
    return service, search, source, target


def test_query_returns_found_formal_evidence_with_provenance(tmp_path: Path) -> None:
    service, _search, source, target = _service(tmp_path)

    evidence = service.query(FormalEvidenceQueryRequest(_QUERY, target.id))

    assert evidence.outcome is EvidenceOutcome.FOUND
    assert len(evidence.hits) == 1
    hit = evidence.hits[0]
    assert hit.text == _CONTENT
    assert hit.chapter_id == source.id
    assert hit.source_revision == source.revision
    assert hit.source_hash == _source_hash(_CONTENT)
    assert hit.source_start == 0
    assert hit.source_end == len(_CONTENT)
    assert "KEYWORD" in hit.retrieval_routes or "EXACT_PHRASE" in hit.retrieval_routes


def test_query_rejects_empty_query(tmp_path: Path) -> None:
    _service_obj, _search, _source, target = _service(tmp_path)
    with pytest.raises(ValueError):
        FormalEvidenceQueryRequest("   ", target.id)


def test_query_rejects_unknown_participant(tmp_path: Path) -> None:
    service, _search, _source, target = _service(tmp_path)
    with pytest.raises(ValueError):
        service.query(
            FormalEvidenceQueryRequest(
                _QUERY, target.id, participants=(str(new_id()),)
            )
        )


def test_query_rejects_out_of_bounds_limit_and_required_hits(tmp_path: Path) -> None:
    _service_obj, _search, _source, target = _service(tmp_path)
    with pytest.raises(ValueError):
        FormalEvidenceQueryRequest(_QUERY, target.id, limit=0)
    with pytest.raises(ValueError):
        FormalEvidenceQueryRequest(
            _QUERY, target.id, limit=MAX_FORMAL_EVIDENCE_CANDIDATES + 1
        )
    with pytest.raises(ValueError):
        FormalEvidenceQueryRequest(_QUERY, target.id, required_hits=0)


def test_query_limit_respects_hydration_limits(tmp_path: Path) -> None:
    service, _search, _source, target = _service(tmp_path)

    with pytest.raises(ValueError):
        service.query(FormalEvidenceQueryRequest(_QUERY, target.id, limit=30))


def test_query_no_match_returns_not_found(tmp_path: Path) -> None:
    service, _search, _source, target = _service(tmp_path)

    evidence = service.query(
        FormalEvidenceQueryRequest("绝不存在的内容xyz", target.id)
    )

    assert evidence.outcome is EvidenceOutcome.NOT_FOUND
    assert evidence.hits == ()


def test_required_hits_not_met_returns_insufficient(tmp_path: Path) -> None:
    service, _search, _source, target = _service(tmp_path)

    evidence = service.query(
        FormalEvidenceQueryRequest(_QUERY, target.id, required_hits=2)
    )

    assert evidence.outcome is EvidenceOutcome.INSUFFICIENT
    assert len(evidence.hits) == 1


def test_non_formal_documents_are_excluded_from_evidence(tmp_path: Path) -> None:
    service, search, source, target = _service(tmp_path)
    search.index_chapter(source.id, source.title, _CONTENT)

    raw_hits = HistoryRetriever(search).search(_QUERY, target.id)
    assert any(hit.document_type != FORMAL_MANUSCRIPT_DOCUMENT_TYPE for hit in raw_hits)
    assert any(hit.document_type == FORMAL_MANUSCRIPT_DOCUMENT_TYPE for hit in raw_hits)

    evidence = service.query(FormalEvidenceQueryRequest(_QUERY, target.id))

    assert evidence.outcome is EvidenceOutcome.FOUND
    assert len(evidence.hits) == 1
    assert evidence.hits[0].text == _CONTENT
