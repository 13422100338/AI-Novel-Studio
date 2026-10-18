from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ai_novel_studio.application.chapter_revision_service import (
    ChapterRevisionService,
)
from ai_novel_studio.application.evidence_query_service import (
    EvidenceQueryRequest,
    EvidenceQueryService,
)
from ai_novel_studio.application.formal_manuscript_evidence_service import (
    EvidenceOutcome,
    FormalManuscriptEvidenceService,
)
from ai_novel_studio.core.context.history_retriever import HistoryRetriever
from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.infrastructure.storage.database import Database
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.search_repository import SearchRepository

CHAPTER_BODIES = (
    "第一章\r\n\r\n艾琳在旧塔发现了铜钥匙。\r\n守卫没有察觉。\r\n",
    "第二章\r\n\r\n铜钥匙在井底发出微光。\r\n艾琳守卫对视一眼。\r\n",
    "第三章\r\n\r\n他们用铜钥匙打开了地窖。\r\n门后是空房间。\r\n",
)


def _service(tmp_path: Path) -> tuple[EvidenceQueryService, ProjectRepository, list[str]]:
    project = ProjectRepository.create(tmp_path / "novel", "Evidence query")
    revisions = ChapterRevisionService(project)
    chapter_ids: list[str] = []
    for index, body in enumerate(CHAPTER_BODIES, start=1):
        submitted = revisions.submit_creation(
            project.list_volumes()[0].id,
            f"第{index}章",
            str(index),
            body,
        )
        chapter_ids.append(submitted.chapter.id)
    repository = SearchRepository(project)
    service = EvidenceQueryService(
        retriever=HistoryRetriever(repository),
        evidence=FormalManuscriptEvidenceService(repository),
    )
    return service, project, chapter_ids


def test_query_returns_exact_formal_hits_with_provenance(tmp_path: Path) -> None:
    service, project, chapter_ids = _service(tmp_path)

    result = service.query(
        EvidenceQueryRequest(
            query="铜钥匙",
            target_chapter_id=chapter_ids[2],
        )
    )

    assert result.outcome is EvidenceOutcome.FOUND
    assert result.hits
    assert result.total_codepoints == sum(len(hit.text) for hit in result.hits)
    body_by_chapter = {
        chapter_ids[index]: CHAPTER_BODIES[index] for index in range(3)
    }
    for hit in result.hits:
        assert hit.chapter_id in chapter_ids[:2]
        assert hit.source_revision == 0
        assert hit.text == body_by_chapter[hit.chapter_id][
            hit.source_start : hit.source_end
        ]
        assert hit.retrieval_routes
        assert hit.document_id in hit.expanded_document_ids


def test_non_formal_documents_are_excluded(tmp_path: Path) -> None:
    service, project, chapter_ids = _service(tmp_path)
    search = SearchRepository(project)
    search.index_chapter(
        chapter_ids[0],
        "第一章",
        CHAPTER_BODIES[0],
    )

    result = service.query(
        EvidenceQueryRequest(
            query="铜钥匙",
            target_chapter_id=chapter_ids[2],
        )
    )

    assert result.outcome is EvidenceOutcome.FOUND
    assert result.hits
    assert all(
        hit.source_id.startswith("FORMAL_MANUSCRIPT:") for hit in result.hits
    )


def test_target_and_future_chapters_are_excluded(tmp_path: Path) -> None:
    service, project, chapter_ids = _service(tmp_path)

    result = service.query(
        EvidenceQueryRequest(
            query="空房间",
            target_chapter_id=chapter_ids[2],
        )
    )

    assert result.outcome is EvidenceOutcome.NOT_FOUND
    assert result.hits == ()
    assert result.total_codepoints == 0


def test_insufficient_when_required_hits_unmet(tmp_path: Path) -> None:
    service, project, chapter_ids = _service(tmp_path)

    result = service.query(
        EvidenceQueryRequest(
            query="铜钥匙",
            target_chapter_id=chapter_ids[2],
            required_hits=8,
        )
    )

    assert result.outcome is EvidenceOutcome.INSUFFICIENT
    assert len(result.hits) < 8
    assert result.hits


def test_invalid_requests_fail_before_database_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, project, chapter_ids = _service(tmp_path)

    def forbidden_connect(database: Database) -> sqlite3.Connection:
        raise AssertionError("invalid input reached database")

    monkeypatch.setattr(Database, "connect", forbidden_connect)
    with pytest.raises(ValueError):
        service.query(
            EvidenceQueryRequest(query="   ", target_chapter_id=chapter_ids[0])
        )
    with pytest.raises(ValueError):
        service.query(EvidenceQueryRequest(query="钥匙", target_chapter_id="not-a-uuid"))
    with pytest.raises(ValueError):
        service.query(
            EvidenceQueryRequest(
                query="钥匙",
                target_chapter_id=chapter_ids[0],
                limit=0,
            )
        )


def test_unknown_target_chapter_fails_closed(tmp_path: Path) -> None:
    service, project, chapter_ids = _service(tmp_path)

    with pytest.raises(Exception) as captured:
        service.query(
            EvidenceQueryRequest(query="铜钥匙", target_chapter_id=new_id())
        )

    assert "RAW" not in str(captured.value)
