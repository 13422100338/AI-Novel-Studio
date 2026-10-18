from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from ai_novel_studio.application.chapter_revision_service import (
    ChapterRevisionService,
)
from ai_novel_studio.application.compile_context_service import (
    CompileContextService,
    EvidenceNeed,
    EvidenceNeedKind,
)
from ai_novel_studio.application.evidence_query_service import (
    EvidenceQueryService,
)
from ai_novel_studio.application.formal_manuscript_evidence_service import (
    EvidenceOutcome,
    FormalManuscriptEvidenceService,
)
from ai_novel_studio.core.context.context_builder import (
    ContextBlock,
    ContextBuilder,
    ContextBuildRequest,
    RequiredContextOverflowError,
)
from ai_novel_studio.core.context.history_retriever import HistoryRetriever
from ai_novel_studio.core.context.token_budget import TokenBudget
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.search_repository import SearchRepository

CHAPTER_BODIES = (
    "第一章\r\n\r\n艾琳在旧塔发现了铜钥匙。\r\n守卫没有察觉。\r\n",
    "第二章\r\n\r\n铜钥匙在井底发出微光。\r\n艾琳守卫对视一眼。\r\n",
    "第三章\r\n\r\n他们用铜钥匙打开了地窖。\r\n门后是空房间。\r\n",
)


@dataclass(frozen=True, slots=True)
class Fixture:
    project: ProjectRepository
    service: CompileContextService
    chapter_ids: list[str]


class _LenEstimator:
    def estimate(self, text: str) -> int:
        return len(text)


def _fixture(tmp_path: Path) -> Fixture:
    project = ProjectRepository.create(tmp_path / "novel", "Compile context")
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
    search = SearchRepository(project)
    service = CompileContextService(
        evidence_query=EvidenceQueryService(
            retriever=HistoryRetriever(search),
            evidence=FormalManuscriptEvidenceService(search),
        ),
        builder=ContextBuilder(_LenEstimator()),
    )
    return Fixture(project, service, chapter_ids)


def _base_request(
    chapter_id: str,
    *,
    budget: TokenBudget | None = None,
    blocks: tuple[ContextBlock, ...] = (),
) -> ContextBuildRequest:
    return ContextBuildRequest(
        chapter_id=chapter_id,
        run_id="run-compile",
        budget=budget or TokenBudget(2_000, 20, 10),
        blocks=blocks,
    )


def _plain_block(block_id: str, content: str) -> ContextBlock:
    return ContextBlock(
        id=block_id,
        category="rules",
        content=content,
        priority=1,
        required=True,
        source_type="SYSTEM",
        source_id=block_id,
        source_chapter_id=None,
        source_revision=None,
        source_hash=f"hash-{block_id}",
        rationale="固定规则",
    )


def _reference_hits(
    fixture: Fixture,
    target_chapter_id: str,
    *,
    query: str = "铜钥匙",
    required_hits: int | None = None,
):
    search = SearchRepository(fixture.project)
    reference = EvidenceQueryService(
        retriever=HistoryRetriever(search),
        evidence=FormalManuscriptEvidenceService(search),
    )
    from ai_novel_studio.application.evidence_query_service import (
        EvidenceQueryRequest,
    )

    return reference.query(
        EvidenceQueryRequest(
            query=query,
            target_chapter_id=target_chapter_id,
            required_hits=required_hits,
        )
    )


def test_compiles_exact_evidence_blocks_with_full_provenance(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    target = fixture.chapter_ids[2]
    need = EvidenceNeed(
        kind=EvidenceNeedKind.HISTORICAL_DETAIL,
        query="铜钥匙",
    )
    reference = _reference_hits(fixture, target)
    assert reference.outcome is EvidenceOutcome.FOUND

    compiled = fixture.service.compile(
        _base_request(target, blocks=(_plain_block("rules", "保持视角一致。"),)),
        evidence_needs=(need,),
    )

    built = compiled.built
    assert built.manifest.schema_version == 3
    evidence_selected = [
        item
        for item in built.manifest.selected
        if item.source_type == "FORMAL_MANUSCRIPT"
    ]
    assert len(evidence_selected) == len(reference.hits)
    assert all(item.category == "exact_evidence" for item in evidence_selected)
    assert {item.source_chapter_id for item in evidence_selected} == {
        hit.chapter_id for hit in reference.hits
    }
    for hit in reference.hits:
        assert hit.text in built.text
    body_by_chapter = dict(zip(fixture.chapter_ids, CHAPTER_BODIES, strict=True))
    for hit in reference.hits:
        assert hit.text == body_by_chapter[hit.chapter_id][
            hit.source_start : hit.source_end
        ]

    trace = built.manifest.retrieval_trace
    evidence_trace = [
        item for item in trace if item.block_id.startswith("EVIDENCE:")
    ]
    assert len(evidence_trace) == len(reference.hits)
    for item in evidence_trace:
        assert item.selected is True
        assert item.omission_reason is None
        assert item.volume_id
        matching = [
            hit
            for hit in reference.hits
            if hit.document_id == item.document_id
        ]
        assert len(matching) == 1
        hit = matching[0]
        assert item.source_id == hit.source_id
        assert (item.start, item.end) == (hit.source_start, hit.source_end)
        assert item.retrieval_routes == tuple(
            str(route) for route in hit.retrieval_routes
        )
        assert item.total_score == hit.total_score

    outcomes = compiled.evidence_outcomes
    assert [item.kind for item in outcomes] == [EvidenceNeedKind.HISTORICAL_DETAIL]
    assert outcomes[0].outcome is EvidenceOutcome.FOUND
    assert outcomes[0].hit_count == len(reference.hits)


def test_not_found_and_insufficient_are_recorded_without_fabrication(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    target = fixture.chapter_ids[2]
    missing_need = EvidenceNeed(
        kind=EvidenceNeedKind.EXISTENCE_CHECK,
        query="完全不存在的内容词组",
    )
    insufficient_need = EvidenceNeed(
        kind=EvidenceNeedKind.EXACT_QUOTE,
        query="铜钥匙",
        required_hits=8,
    )

    missing = fixture.service.compile(
        _base_request(target), evidence_needs=(missing_need,)
    )
    insufficient = fixture.service.compile(
        _base_request(target), evidence_needs=(insufficient_need,)
    )

    assert missing.evidence_outcomes[0].outcome is EvidenceOutcome.NOT_FOUND
    assert missing.evidence_outcomes[0].hit_count == 0
    assert missing.built.text == ""

    assert insufficient.evidence_outcomes[0].outcome is EvidenceOutcome.INSUFFICIENT
    assert 0 < insufficient.evidence_outcomes[0].hit_count < 8
    evidence_selected = [
        item
        for item in insufficient.built.manifest.selected
        if item.source_type == "FORMAL_MANUSCRIPT"
    ]
    assert 0 < len(evidence_selected) < 8


def test_each_need_queries_exactly_once_in_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _fixture(tmp_path)
    target = fixture.chapter_ids[2]
    calls: list[str] = []
    original = HistoryRetriever.search

    def recording(self, query, target_chapter_id, **kwargs):
        calls.append(query)
        return original(self, query, target_chapter_id, **kwargs)

    monkeypatch.setattr(HistoryRetriever, "search", recording)
    needs = (
        EvidenceNeed(kind=EvidenceNeedKind.HISTORICAL_DETAIL, query="铜钥匙"),
        EvidenceNeed(
            kind=EvidenceNeedKind.EXISTENCE_CHECK,
            query="空房间",
        ),
    )

    compiled = fixture.service.compile(_base_request(target), evidence_needs=needs)

    assert calls == ["铜钥匙", "空房间"]
    assert [item.kind for item in compiled.evidence_outcomes] == [
        EvidenceNeedKind.HISTORICAL_DETAIL,
        EvidenceNeedKind.EXISTENCE_CHECK,
    ]
    assert compiled.evidence_outcomes[0].outcome is EvidenceOutcome.FOUND
    assert compiled.evidence_outcomes[1].outcome is EvidenceOutcome.NOT_FOUND


def test_budget_still_governs_evidence_blocks(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    target = fixture.chapter_ids[2]

    compiled = fixture.service.compile(
        _base_request(
            target,
            budget=TokenBudget(35, 20, 10),
        ),
        evidence_needs=(
            EvidenceNeed(kind=EvidenceNeedKind.HISTORICAL_DETAIL, query="铜钥匙"),
        ),
    )

    manifest = compiled.built.manifest
    omitted_evidence = [
        item for item in manifest.omitted if item.block_id.startswith("EVIDENCE:")
    ]
    assert omitted_evidence
    trace_by_block = {item.block_id: item for item in manifest.retrieval_trace}
    for item in omitted_evidence:
        traced = trace_by_block[item.block_id]
        assert traced.selected is False
        assert traced.omission_reason == item.reason


def test_required_context_overflow_still_raises(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    target = fixture.chapter_ids[2]

    with pytest.raises(RequiredContextOverflowError):
        fixture.service.compile(
            _base_request(
                target,
                budget=TokenBudget(35, 20, 10),
                blocks=(_plain_block("huge-required", "R" * 100),),
            ),
            evidence_needs=(
                EvidenceNeed(
                    kind=EvidenceNeedKind.HISTORICAL_DETAIL,
                    query="铜钥匙",
                ),
            ),
        )


def test_input_validation_rejects_invalid_needs_and_services(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    target = fixture.chapter_ids[2]

    with pytest.raises(TypeError):
        EvidenceNeed()  # type: ignore[no-untyped-call]
    with pytest.raises(ValueError):
        EvidenceNeed(kind=EvidenceNeedKind.EXACT_QUOTE, query="   ")
    with pytest.raises(ValueError):
        EvidenceNeed(kind=EvidenceNeedKind.EXACT_QUOTE, query="钥匙", limit=0)
    with pytest.raises(ValueError):
        EvidenceNeed(
            kind=EvidenceNeedKind.EXACT_QUOTE,
            query="钥匙",
            participants=(" ",),
        )
    with pytest.raises(TypeError):
        fixture.service.compile(_base_request(target), evidence_needs=("bad",))  # type: ignore[arg-type]
