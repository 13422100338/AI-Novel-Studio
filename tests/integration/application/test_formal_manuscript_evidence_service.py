from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from math import inf, nan
from pathlib import Path

import pytest

from ai_novel_studio.application.chapter_revision_service import (
    ChapterRevisionService,
)
from ai_novel_studio.application.formal_manuscript_evidence_service import (
    EvidenceOutcome,
    EvidenceSet,
    FormalEvidenceCandidate,
    FormalEvidenceHydrationRequest,
    FormalEvidenceIntegrityError,
    FormalEvidenceLimits,
    FormalManuscriptEvidenceService,
)
from ai_novel_studio.core.context.manuscript_chunking import (
    DEFAULT_MANUSCRIPT_CHUNK_POLICY,
)
from ai_novel_studio.domain.chapter import Chapter
from ai_novel_studio.domain.identifiers import new_id
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.search_repository import SearchRepository


def _source_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _candidate(document_id: str, *, total_score: float = 0.0) -> FormalEvidenceCandidate:
    return FormalEvidenceCandidate(
        document_id,
        ("KEYWORD",),
        total_score=total_score,
    )


def test_hydrates_exact_current_formal_candidate(tmp_path: Path) -> None:
    content = "第一段😀\r\n\r\n第二段证据\r\n"
    project = ProjectRepository.create(tmp_path / "novel", "Exact evidence")
    volume = project.list_volumes()[0]
    revisions = ChapterRevisionService(project)
    source = revisions.submit_creation(
        volume.id,
        "Evidence source",
        content=content,
    ).chapter
    target = revisions.submit_creation(
        volume.id,
        "Generation target",
        content="target",
    ).chapter
    search = SearchRepository(project)
    document = search.read_formal_manuscript_chunks(
        source.id,
        expected_revision=source.revision,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )[0]
    candidate = FormalEvidenceCandidate(
        document.id,
        ("EXACT_PHRASE", "EMBEDDING"),
        lexical_score=0.75,
        semantic_score=0.625,
        participant_boost=0.25,
        pinned_weight=0.125,
        recency_score=0.5,
        stale_penalty=-10.0,
        total_score=1.375,
    )

    evidence = FormalManuscriptEvidenceService(search).hydrate(
        FormalEvidenceHydrationRequest(target.id, (candidate,))
    )

    assert evidence.outcome == EvidenceOutcome.FOUND
    assert evidence.total_codepoints == len(content)
    assert len(evidence.hits) == 1
    hit = evidence.hits[0]
    assert (
        hit.document_id,
        hit.source_id,
        hit.chapter_id,
        hit.volume_id,
        hit.source_revision,
        hit.source_hash,
        hit.title,
        hit.source_start,
        hit.source_end,
        hit.text,
    ) == (
        document.id,
        document.source_id,
        source.id,
        volume.id,
        source.revision,
        _source_hash(content),
        source.title,
        0,
        len(content),
        content,
    )
    assert hit.retrieval_routes == candidate.retrieval_routes
    assert (
        hit.lexical_score,
        hit.semantic_score,
        hit.participant_boost,
        hit.pinned_weight,
        hit.recency_score,
        hit.stale_penalty,
        hit.total_score,
    ) == (
        candidate.lexical_score,
        candidate.semantic_score,
        candidate.participant_boost,
        candidate.pinned_weight,
        candidate.recency_score,
        candidate.stale_penalty,
        candidate.total_score,
    )
    with project.database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM memory_embeddings").fetchone()[0] == 0


def test_expands_exact_adjacent_ordinals_and_deduplicates_ranges(
    tmp_path: Path,
) -> None:
    content = "甲" * 1_800 + "😀" * 1_800
    project = ProjectRepository.create(tmp_path / "novel", "Neighbor evidence")
    volume = project.list_volumes()[0]
    revisions = ChapterRevisionService(project)
    source = revisions.submit_creation(volume.id, "Source", content=content).chapter
    target = revisions.submit_creation(volume.id, "Target", content="target").chapter
    search = SearchRepository(project)
    documents = search.read_formal_manuscript_chunks(
        source.id,
        expected_revision=source.revision,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )
    assert len(documents) == 3
    middle = _candidate(documents[1].id, total_score=-100.0)

    evidence = FormalManuscriptEvidenceService(
        search,
        limits=FormalEvidenceLimits(neighbor_radius=2),
    ).hydrate(
        FormalEvidenceHydrationRequest(
            target.id,
            (middle, middle, _candidate(documents[0].id, total_score=999.0)),
        )
    )

    assert evidence.outcome == EvidenceOutcome.FOUND
    assert len(evidence.hits) == 1
    hit = evidence.hits[0]
    assert hit.document_id == documents[1].id
    assert hit.expanded_document_ids == tuple(document.id for document in documents)
    assert (hit.source_start, hit.source_end, hit.text) == (0, len(content), content)
    assert hit.total_score == -100.0


def test_preserves_input_rank_across_distinct_sources_without_score_threshold(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Ranked evidence")
    volume = project.list_volumes()[0]
    revisions = ChapterRevisionService(project)
    first = revisions.submit_creation(volume.id, "First", content="first source").chapter
    second = revisions.submit_creation(volume.id, "Second", content="second source").chapter
    target = revisions.submit_creation(volume.id, "Target", content="target").chapter
    search = SearchRepository(project)

    def document_id(chapter_id: str, content: str) -> str:
        return search.read_formal_manuscript_chunks(
            chapter_id,
            expected_revision=0,
            expected_source_hash=_source_hash(content),
            chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
        )[0].id

    second_candidate = _candidate(document_id(second.id, "second source"), total_score=-9.0)
    first_candidate = _candidate(document_id(first.id, "first source"), total_score=0.0)

    evidence = FormalManuscriptEvidenceService(search).hydrate(
        FormalEvidenceHydrationRequest(
            target.id,
            (second_candidate, first_candidate),
        )
    )

    assert [hit.chapter_id for hit in evidence.hits] == [second.id, first.id]
    assert [hit.total_score for hit in evidence.hits] == [-9.0, 0.0]


def test_outcomes_depend_only_on_validated_hits_and_explicit_requirement(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Evidence outcomes")
    volume = project.list_volumes()[0]
    revisions = ChapterRevisionService(project)
    source = revisions.submit_creation(volume.id, "Source", content="evidence").chapter
    target = revisions.submit_creation(volume.id, "Target", content="target").chapter
    search = SearchRepository(project)
    document = search.read_formal_manuscript_chunks(
        source.id,
        expected_revision=0,
        expected_source_hash=_source_hash("evidence"),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )[0]
    service = FormalManuscriptEvidenceService(search)

    not_found = service.hydrate(FormalEvidenceHydrationRequest(target.id, ()))
    insufficient = service.hydrate(
        FormalEvidenceHydrationRequest(
            target.id,
            (_candidate(document.id, total_score=-1_000_000.0),),
            required_hits=2,
        )
    )

    assert not_found.outcome == EvidenceOutcome.NOT_FOUND
    assert not_found.hits == ()
    assert insufficient.outcome == EvidenceOutcome.INSUFFICIENT
    assert len(insufficient.hits) == 1


def test_limits_bound_candidates_neighbors_hits_and_total_output(tmp_path: Path) -> None:
    for limits in (
        {"max_candidates": 51},
        {"neighbor_radius": 3},
        {"max_codepoints_per_hit": 8_001},
        {"max_codepoints_per_set": 32_001},
        {"max_codepoints_per_hit": 4_800, "max_codepoints_per_set": 4_799},
    ):
        with pytest.raises(ValueError, match="formal evidence"):
            FormalEvidenceLimits(**limits)

    project = ProjectRepository.create(tmp_path / "novel", "Bounded evidence")
    volume = project.list_volumes()[0]
    revisions = ChapterRevisionService(project)
    sources = tuple(
        revisions.submit_creation(
            volume.id,
            f"Source {index}",
            content=str(index) * 3_000,
        ).chapter
        for index in range(2)
    )
    target = revisions.submit_creation(volume.id, "Target", content="target").chapter
    search = SearchRepository(project)
    candidates = tuple(
        _candidate(
            search.read_formal_manuscript_chunks(
                source.id,
                expected_revision=0,
                expected_source_hash=_source_hash(str(index) * 3_000),
                chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
            )[0].id
        )
        for index, source in enumerate(sources)
    )
    service = FormalManuscriptEvidenceService(
        search,
        limits=FormalEvidenceLimits(
            max_candidates=2,
            neighbor_radius=1,
            max_codepoints_per_hit=4_800,
            max_codepoints_per_set=4_800,
        ),
    )

    evidence = service.hydrate(
        FormalEvidenceHydrationRequest(target.id, candidates, required_hits=2)
    )

    assert evidence.outcome == EvidenceOutcome.INSUFFICIENT
    assert len(evidence.hits) == 1
    assert evidence.total_codepoints <= 4_800
    with pytest.raises(ValueError, match="candidate limit"):
        FormalManuscriptEvidenceService(
            search,
            limits=FormalEvidenceLimits(max_candidates=1),
        ).hydrate(FormalEvidenceHydrationRequest(target.id, candidates))
    with pytest.raises(FormalEvidenceIntegrityError):
        FormalManuscriptEvidenceService(
            search,
            limits=FormalEvidenceLimits(
                max_candidates=1,
                neighbor_radius=0,
                max_codepoints_per_hit=1,
                max_codepoints_per_set=1,
            ),
        ).hydrate(FormalEvidenceHydrationRequest(target.id, (candidates[0],)))
    with pytest.raises(ValueError, match="formal evidence candidates"):
        FormalEvidenceHydrationRequest(
            target.id,
            tuple(candidates[0] for _ in range(51)),
        )


@pytest.mark.parametrize(
    ("routes", "score"),
    [
        ((), 0.0),
        (("KEYWORD", "KEYWORD"), 0.0),
        (("NOT_A_ROUTE",), 0.0),
        (("KEYWORD",), nan),
        (("KEYWORD",), inf),
        (("KEYWORD",), True),
    ],
)
def test_candidates_reject_invalid_routes_and_nonfinite_scores(
    routes: tuple[str, ...],
    score: float,
) -> None:
    with pytest.raises(ValueError, match="formal evidence"):
        FormalEvidenceCandidate(
            "00000000-0000-0000-0000-000000000001",
            routes,  # type: ignore[arg-type]
            total_score=score,
        )


def test_candidates_reject_leaky_invalid_identifiers_with_fixed_message() -> None:
    leaked = "C:/private/manuscript/secret.txt"
    with pytest.raises(ValueError) as captured:
        FormalEvidenceCandidate(leaked, ("KEYWORD",))
    assert str(captured.value) == "formal evidence candidate document ID is invalid"
    assert leaked not in str(captured.value)


def test_hydration_rejects_unsafe_candidate_universe_without_false_evidence(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Unsafe evidence")
    volume = project.list_volumes()[0]
    revisions = ChapterRevisionService(project)
    chapters: list[tuple[Chapter, str]] = []
    for title in ("Stale", "Review", "Old", "Deleted", "Rejected"):
        content = f"{title} evidence"
        chapters.append(
            (revisions.submit_creation(volume.id, title, content=content).chapter, content)
        )
    target = revisions.submit_creation(volume.id, "Target", content="target").chapter
    future = revisions.submit_creation(volume.id, "Future", content="future evidence").chapter
    search = SearchRepository(project)

    document_ids = []
    for chapter, content in chapters:
        document_ids.append(
            search.read_formal_manuscript_chunks(
                chapter.id,
                expected_revision=0,
                expected_source_hash=_source_hash(content),
                chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
            )[0].id
        )
    target_document_id = search.read_formal_manuscript_chunks(
        target.id,
        expected_revision=0,
        expected_source_hash=_source_hash("target"),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )[0].id
    future_document_id = search.read_formal_manuscript_chunks(
        future.id,
        expected_revision=0,
        expected_source_hash=_source_hash("future evidence"),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )[0].id
    legacy = search.index_chapter(chapters[0][0].id, "Legacy", "legacy excerpt")
    with project.database.connect() as connection, connection:
        connection.execute(
            "UPDATE memory_documents SET status = 'STALE' WHERE id = ?",
            (document_ids[0],),
        )
        connection.execute(
            "UPDATE memory_documents SET review_status = 'REVIEW' WHERE id = ?",
            (document_ids[1],),
        )
        connection.execute(
            "UPDATE chapters SET revision = revision + 1 WHERE id = ?",
            (chapters[2][0].id,),
        )
        connection.execute(
            "UPDATE chapters SET is_deleted = 1 WHERE id = ?",
            (chapters[3][0].id,),
        )
        connection.execute(
            "UPDATE memory_documents SET review_status = 'REJECTED' WHERE id = ?",
            (document_ids[4],),
        )

    evidence = FormalManuscriptEvidenceService(search).hydrate(
        FormalEvidenceHydrationRequest(
            target.id,
            tuple(
                _candidate(document_id)
                for document_id in (
                    new_id(),
                    legacy.id,
                    *document_ids,
                    target_document_id,
                    future_document_id,
                )
            ),
        )
    )

    assert evidence == EvidenceSet(EvidenceOutcome.NOT_FOUND, (), 0)


def test_locked_current_formal_projection_remains_authoritative(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Locked evidence")
    volume = project.list_volumes()[0]
    revisions = ChapterRevisionService(project)
    source = revisions.submit_creation(volume.id, "Locked", content="locked body").chapter
    target = revisions.submit_creation(volume.id, "Target", content="target").chapter
    search = SearchRepository(project)
    document = search.read_formal_manuscript_chunks(
        source.id,
        expected_revision=0,
        expected_source_hash=_source_hash("locked body"),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )[0]
    with project.database.connect() as connection, connection:
        connection.execute(
            "UPDATE memory_documents SET review_status = 'LOCKED' WHERE chapter_id = ?",
            (source.id,),
        )

    evidence = FormalManuscriptEvidenceService(search).hydrate(
        FormalEvidenceHydrationRequest(target.id, (_candidate(document.id),))
    )

    assert evidence.outcome == EvidenceOutcome.FOUND
    assert evidence.hits[0].text == "locked body"


@pytest.mark.parametrize(
    "corruption",
    ["document", "source_hash", "fts", "dependency"],
)
def test_current_projection_corruption_raises_only_stable_safe_error(
    tmp_path: Path,
    corruption: str,
) -> None:
    secret = "RAW SECRET MANUSCRIPT BODY"
    project = ProjectRepository.create(tmp_path / "novel", "Corrupt evidence")
    volume = project.list_volumes()[0]
    revisions = ChapterRevisionService(project)
    source = revisions.submit_creation(volume.id, "Source", content="trusted body").chapter
    target = revisions.submit_creation(volume.id, "Target", content="target").chapter
    search = SearchRepository(project)
    document = search.read_formal_manuscript_chunks(
        source.id,
        expected_revision=0,
        expected_source_hash=_source_hash("trusted body"),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )[0]
    with project.database.connect() as connection, connection:
        if corruption == "document":
            connection.execute(
                "UPDATE memory_documents SET content = ? WHERE id = ?",
                (secret, document.id),
            )
        elif corruption == "source_hash":
            connection.execute(
                "UPDATE memory_documents SET source_hash = ? WHERE id = ?",
                ("b" * 64, document.id),
            )
        elif corruption == "fts":
            connection.execute("DELETE FROM memory_fts WHERE document_id = ?", (document.id,))
        else:
            connection.execute(
                "DELETE FROM memory_dependencies WHERE memory_type = 'SEARCH' AND memory_id = ?",
                (document.id,),
            )

    with pytest.raises(FormalEvidenceIntegrityError) as captured:
        FormalManuscriptEvidenceService(search).hydrate(
            FormalEvidenceHydrationRequest(target.id, (_candidate(document.id),))
        )

    assert str(captured.value) == "formal manuscript evidence cannot be validated"
    assert secret not in str(captured.value)
    assert str(project.layout.root) not in str(captured.value)
    assert document.source_hash not in str(captured.value)
    assert captured.value.__cause__ is None


def test_source_change_during_hydration_fails_closed_without_leaking_body(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = "trusted source body"
    changed = "SOURCE CHANGED DURING HYDRATE"
    project = ProjectRepository.create(tmp_path / "novel", "Racing evidence")
    volume = project.list_volumes()[0]
    revisions = ChapterRevisionService(project)
    source = revisions.submit_creation(volume.id, "Source", content=content).chapter
    target = revisions.submit_creation(volume.id, "Target", content="target").chapter
    search = SearchRepository(project)
    document = search.read_formal_manuscript_chunks(
        source.id,
        expected_revision=0,
        expected_source_hash=_source_hash(content),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )[0]
    original = search._current_formal_source
    calls = 0

    def racing_source(*args: object, **kwargs: object) -> tuple[object, str]:
        nonlocal calls
        result = original(*args, **kwargs)  # type: ignore[arg-type]
        calls += 1
        if calls == 1:
            chapter = ChapterRepository(project).get_chapter(source.id)
            source_path = project.layout.root / chapter.content_path
            with source_path.open("w", encoding="utf-8", newline="") as stream:
                stream.write(changed)
        return result

    monkeypatch.setattr(search, "_current_formal_source", racing_source)

    with pytest.raises(FormalEvidenceIntegrityError) as captured:
        FormalManuscriptEvidenceService(search).hydrate(
            FormalEvidenceHydrationRequest(target.id, (_candidate(document.id),))
        )

    assert str(captured.value) == "formal manuscript evidence cannot be validated"
    assert changed not in str(captured.value)


def test_raw_storage_error_is_normalized_without_leaking_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_error = "RAW SQL ERROR C:/private/manuscript.txt secret body"
    project = ProjectRepository.create(tmp_path / "novel", "Storage error")
    search = SearchRepository(project)

    def fail_storage(*args: object, **kwargs: object) -> object:
        raise sqlite3.OperationalError(raw_error)

    monkeypatch.setattr(search, "hydrate_formal_manuscript_candidates", fail_storage)
    with pytest.raises(FormalEvidenceIntegrityError) as captured:
        FormalManuscriptEvidenceService(search).hydrate(
            FormalEvidenceHydrationRequest(
                "00000000-0000-0000-0000-000000000001",
                (),
            )
        )

    assert str(captured.value) == "formal manuscript evidence cannot be validated"
    assert raw_error not in str(captured.value)
    assert captured.value.__cause__ is None


def test_evidence_dtos_reject_directly_constructed_inconsistent_state(
    tmp_path: Path,
) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Validated DTOs")
    volume = project.list_volumes()[0]
    revisions = ChapterRevisionService(project)
    source = revisions.submit_creation(volume.id, "Source", content="body").chapter
    target = revisions.submit_creation(volume.id, "Target", content="target").chapter
    search = SearchRepository(project)
    document = search.read_formal_manuscript_chunks(
        source.id,
        expected_revision=0,
        expected_source_hash=_source_hash("body"),
        chunk_policy_version=DEFAULT_MANUSCRIPT_CHUNK_POLICY.version,
    )[0]
    evidence = FormalManuscriptEvidenceService(search).hydrate(
        FormalEvidenceHydrationRequest(target.id, (_candidate(document.id),))
    )

    with pytest.raises(ValueError, match="formal evidence"):
        replace(evidence.hits[0], text="not the exact range")
    with pytest.raises(ValueError, match="formal evidence"):
        replace(evidence, total_codepoints=evidence.total_codepoints + 1)
