from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from ai_novel_studio.application.chapter_revision_service import (
    ChapterRevisionService,
)
from ai_novel_studio.application.shared_semantic_analysis_service import (
    SharedSemanticAnalysisService,
)
from ai_novel_studio.application.shared_semantic_import_service import (
    SharedSemanticChapterResult,
)
from ai_novel_studio.application.shared_semantic_view_service import (
    SharedSemanticViewBindingStatus,
    SharedSemanticViewService,
)
from ai_novel_studio.core.context.semantic_windowing import SemanticWindow
from ai_novel_studio.core.context.shared_semantic_result import (
    SharedSemanticResult,
    SourceSpan,
    SubjectMentionCandidate,
    ViewDifferenceCandidate,
    ViewDifferenceKind,
    candidate_source_id,
)
from ai_novel_studio.domain.memory import Authority, ReviewStatus
from ai_novel_studio.domain.view import EpistemicStatus, ViewType
from ai_novel_studio.infrastructure.llm.contract_runner import (
    ContractValidationError,
    LLMContractRunner,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.view_assertion_repository import (
    ViewAssertionRepository,
)

CHAPTER_BODIES = {
    1: "第一章\r\n\r\n艾琳把密信交给守卫。\r\n守卫没有声张。\r\n",
    2: "第二章\r\n\r\n守卫在井边烧掉了密信。\r\n",
    3: "第三章\r\n\r\n真相揭晓：密信来自王室。\r\n",
}


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Fixture:
    project: ProjectRepository
    chapter_id: str
    revision: int
    source_hash: str


def _fixture(tmp_path: Path) -> Fixture:
    project = ProjectRepository.create(tmp_path / "novel", "Gate E1 sparse views")
    revisions = ChapterRevisionService(project)
    volume = project.list_volumes()[0]
    first = revisions.submit_creation(volume.id, "第一章", "1", CHAPTER_BODIES[1])
    revisions.submit_creation(volume.id, "第二章", "2", CHAPTER_BODIES[2])
    characters = CharacterMemoryRepository(project)
    characters.create_character("艾琳")
    characters.create_character("守卫")
    chapter = ChapterRepository(project).get_chapter(first.chapter.id)
    return Fixture(
        project=project,
        chapter_id=chapter.id,
        revision=chapter.revision,
        source_hash=_hash(CHAPTER_BODIES[1]),
    )


def _window(fixture: Fixture) -> SemanticWindow:
    from ai_novel_studio.core.context.semantic_windowing import (
        project_semantic_windows,
    )

    return project_semantic_windows(
        fixture.chapter_id,
        fixture.revision,
        fixture.source_hash,
        1,
        CHAPTER_BODIES[1],
    )[0]


def _span(window: SemanticWindow, value: str) -> SourceSpan:
    start = window.text.index(value)
    return SourceSpan(
        start,
        start + len(value),
        window.text[start : start + len(value)],
    )


def _result(
    window: SemanticWindow,
    *,
    mention_names: tuple[str, ...],
    views: tuple[dict[str, object], ...],
) -> SharedSemanticResult:
    mentions = tuple(
        SubjectMentionCandidate(
            candidate_source_id(window, "subject-mention", index),
            name,
            (_span(window, name),),
        )
        for index, name in enumerate(mention_names)
    )
    by_name = {
        name: mentions[index].candidate_id
        for index, name in enumerate(mention_names)
    }
    candidates = tuple(
        ViewDifferenceCandidate(
            candidate_id=candidate_source_id(window, "view-difference", index),
            view_type=ViewType(str(spec["view_type"])),
            observer=None,
            target=None,
            epistemic_status=spec.get("status"),  # type: ignore[arg-type]
            content=str(spec["content"]),
            spans=(_span(window, str(spec["anchor"])),),
            observer_mention_candidate_id=(
                by_name[str(spec["observer"])]
                if spec.get("observer") is not None
                else None
            ),
            target_mention_candidate_id=(
                by_name[str(spec["target"])] if spec.get("target") is not None else None
            ),
            difference_kind=spec.get("kind"),  # type: ignore[arg-type]
        )
        for index, spec in enumerate(views)
    )
    return SharedSemanticResult(
        window=window,
        subject_mentions=mentions,
        aliases=(),
        occurrences=(),
        participant_links=(),
        state_changes=(),
        view_differences=candidates,
        summary=None,
    )


def test_ordinary_participation_binds_no_view_assertions(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    window = _window(fixture)

    binding = SharedSemanticViewService(fixture.project).bind_chapter_views(
        SharedSemanticChapterResult(
            chapter_id=fixture.chapter_id,
            source_revision=fixture.revision,
            source_hash=fixture.source_hash,
            narrative_sequence=1,
            results=(
                _result(window, mention_names=("艾琳", "守卫"), views=()),
            ),
        )
    )

    assert binding.status is SharedSemanticViewBindingStatus.APPLIED
    assert binding.accepted_assertion_ids == ()
    repository = ViewAssertionRepository(fixture.project)
    assert repository.list_model_review_candidates() == ()


def test_sparse_views_bind_as_review_with_derived_visibility(
    tmp_path: Path,
) -> None:
    fixture = _fixture(tmp_path)
    window = _window(fixture)
    sequence = ChapterRepository(fixture.project).get_chapter_sequence(
        fixture.chapter_id
    )
    views = (
        dict(
            view_type="CHARACTER_VIEW",
            observer="艾琳",
            target="守卫",
            status=EpistemicStatus.MISBELIEVES,
            kind=ViewDifferenceKind.FALSE_BELIEF,
            content="艾琳误信守卫已上交密信。",
            anchor="艾琳",
        ),
        dict(
            view_type="READER_VIEW",
            target="艾琳",
            kind=ViewDifferenceKind.PARTIAL_DISCLOSURE,
            content="读者只知存在密信。",
            anchor="密信",
        ),
    )

    bound = SharedSemanticViewService(fixture.project).bind_chapter_views(
        SharedSemanticChapterResult(
            chapter_id=fixture.chapter_id,
            source_revision=fixture.revision,
            source_hash=fixture.source_hash,
            narrative_sequence=1,
            results=(_result(window, mention_names=("艾琳", "守卫"), views=views),),
        )
    )
    assert bound.status is SharedSemanticViewBindingStatus.APPLIED
    assert len(bound.accepted_assertion_ids) == 2

    ChapterRevisionService(fixture.project).submit_creation(
        project_volume(fixture.project), "第三章", "3", CHAPTER_BODIES[3]
    )

    repository = ViewAssertionRepository(fixture.project)
    stored = tuple(
        repository.get(item) for item in bound.accepted_assertion_ids
    )
    for assertion in stored:
        assert assertion.review_status is ReviewStatus.REVIEW
        assert assertion.authority is Authority.MODEL_EXTRACTED
        assert assertion.narrative_visible_from_sequence == sequence + 1


def project_volume(project: ProjectRepository) -> str:
    return project.list_volumes()[0].id


def test_envelope_rejects_ordinary_knows_and_reader_secret(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    window = _window(fixture)
    base = dict(anchor="艾琳", content="差异内容。")

    with pytest.raises(ValueError):
        _result(
            window,
            mention_names=("艾琳", "守卫"),
            views=(
                dict(
                    **base,
                    view_type="CHARACTER_VIEW",
                    observer="艾琳",
                    target="守卫",
                    status=EpistemicStatus.KNOWS,
                    kind=ViewDifferenceKind.SECRET,
                ),
            ),
        )
    with pytest.raises(ValueError):
        _result(
            window,
            mention_names=("艾琳",),
            views=(
                dict(
                    **base,
                    view_type="READER_VIEW",
                    target="艾琳",
                    kind=ViewDifferenceKind.SECRET,
                ),
            ),
        )


class _AnalysisGateway:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = responses

    def complete(self, purpose, messages, output_token_limit, **kwargs):  # type: ignore[no-untyped-def]
        del purpose, messages, output_token_limit, kwargs
        payload = self.responses.pop(0)
        return __import__(
            "ai_novel_studio.infrastructure.llm.schemas", fromlist=["LLMResponse"]
        ).LLMResponse(text=json.dumps(payload, ensure_ascii=False), model_id="t")


def test_correction_loop_rejects_plain_reader_fact_and_maps_valid_kind(
    tmp_path: Path,
) -> None:
    del tmp_path
    from ai_novel_studio.infrastructure.llm.schemas import LLMResponse

    text = "林岚\r\n发现钥匙🙂\r\n读者误会"

    def raw_span(value: str) -> dict[str, int]:
        start = text.index(value)
        return {"start": start, "end": start + len(value)}

    window = __import__(
        "ai_novel_studio.core.context.semantic_windowing",
        fromlist=["project_semantic_windows"],
    ).project_semantic_windows(
        "11111111-1111-4111-8111-111111111111",
        3,
        _hash(text),
        7,
        text,
    )[0]
    reader_span = raw_span("读者误会")
    invalid = {
        "subject_mentions": [
            {"mention": "林岚", "spans": [raw_span("林岚")]},
            {"mention": "读者误会", "spans": [reader_span]},
        ],
        "aliases": [],
        "occurrences": [],
        "participant_links": [],
        "state_changes": [],
        "view_differences": [
            {
                "view_type": "READER_VIEW",
                "difference_kind": "SECRET",
                "target_mention_ordinal": 1,
                "content": "正文显式可见的普通事实。",
                "spans": [dict(reader_span)],
            }
        ],
        "summary": None,
    }
    valid = {
        **invalid,
        "view_differences": [
            {
                "view_type": "READER_VIEW",
                "difference_kind": "PARTIAL_DISCLOSURE",
                "target_mention_ordinal": 1,
                "content": "读者只知部分。",
                "spans": [dict(reader_span)],
            }
        ],
    }

    service = SharedSemanticAnalysisService(
        LLMContractRunner(_AnalysisGateway([invalid, invalid]))
    )
    with pytest.raises(ContractValidationError):
        service.extract(window)

    corrected = SharedSemanticAnalysisService(
        LLMContractRunner(_AnalysisGateway([invalid, valid]))
    ).extract(window)

    assert (
        corrected.view_differences[0].difference_kind
        is ViewDifferenceKind.PARTIAL_DISCLOSURE
    )
    assert LLMResponse is not None
