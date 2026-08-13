from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from ai_novel_studio.core.context.semantic_windowing import (
    SemanticWindowPolicy,
    project_semantic_windows,
)
from ai_novel_studio.core.context.shared_semantic_result import (
    SHARED_SEMANTIC_RESULT_V1,
    AliasCandidate,
    OccurrenceCandidate,
    ParticipantLinkCandidate,
    ResolvedSubjectReference,
    SharedSemanticResult,
    SourceSpan,
    StateChangeCandidate,
    SubjectMentionCandidate,
    ViewDifferenceCandidate,
    WindowSummaryCandidate,
    candidate_source_id,
)
from ai_novel_studio.domain.memory import Authority, ReviewStatus
from ai_novel_studio.domain.view import EpistemicStatus, ViewType

_CHAPTER_ID = "00000000-0000-0000-0000-000000000001"
_SOURCE_HASH = "a" * 64


def _window(text: str = "林在门口。她知道秘密。"):
    return project_semantic_windows(
        _CHAPTER_ID,
        3,
        _SOURCE_HASH,
        7,
        text,
    )[0]


def _span(window, start: int, end: int) -> SourceSpan:
    return SourceSpan(start, end, window.text[start:end])


def _result(window=None) -> SharedSemanticResult:
    window = window or _window()
    mention = SubjectMentionCandidate(
        candidate_source_id(window, "subject-mention", 0),
        "林",
        (_span(window, 0, 1),),
    )
    resolved = ResolvedSubjectReference("00000000-0000-0000-0000-000000000010")
    target = ResolvedSubjectReference("00000000-0000-0000-0000-000000000011")
    occurrence = OccurrenceCandidate(
        candidate_source_id(window, "occurrence", 0),
        "DISCOVERY",
        "发现秘密",
        "林在门口发现秘密",
        (_span(window, 0, 1),),
    )
    link = ParticipantLinkCandidate(
        candidate_source_id(window, "participant-link", 0),
        None,
        "observer",
        "门口的观察者",
        (_span(window, 0, 1),),
        occurrence.candidate_id,
        mention.candidate_id,
    )
    state = StateChangeCandidate(
        candidate_source_id(window, "state-change", 0),
        None,
        "KNOWLEDGE_CHANGE",
        "开始知晓秘密",
        (_span(window, 4, 6),),
        occurrence.candidate_id,
        mention.candidate_id,
    )
    view = ViewDifferenceCandidate(
        candidate_source_id(window, "view-difference", 0),
        ViewType.CHARACTER_VIEW,
        ResolvedSubjectReference(resolved.subject_id),
        target,
        EpistemicStatus.KNOWS,
        "观察者知道秘密",
        (_span(window, 4, 6),),
        occurrence.candidate_id,
    )
    return SharedSemanticResult(
        window=window,
        subject_mentions=(mention,),
        aliases=(),
        occurrences=(occurrence,),
        participant_links=(link,),
        state_changes=(state,),
        view_differences=(view,),
        summary=WindowSummaryCandidate(
            candidate_source_id(window, "window-summary", 0),
            "窗口摘要",
            (_span(window, 0, 6),),
        ),
    )


def test_result_is_bound_to_one_exact_window_and_has_fixed_review_defaults() -> None:
    result = _result()
    assert result.schema_version == SHARED_SEMANTIC_RESULT_V1
    assert result.authority is Authority.MODEL_EXTRACTED
    assert result.review_status is ReviewStatus.REVIEW
    assert result.occurrences[0].candidate_id
    with pytest.raises(FrozenInstanceError):
        result.summary = None  # type: ignore[misc]


def test_exact_crlf_unicode_spans_and_stable_ids_replay() -> None:
    window = _window("林😀\r\n她知道秘密。")
    first = _result(window)
    replay = _result(window)
    assert first == replay
    assert first.subject_mentions[0].spans[0].quote == "林"
    assert first.window is window


def test_occurrence_has_no_child_lists_and_one_way_links_validate() -> None:
    result = _result()
    assert not hasattr(result.occurrences[0], "participant_link_ids")
    assert result.participant_links[0].occurrence_candidate_id == result.occurrences[0].candidate_id


def test_invalid_quote_dangling_reference_and_alternate_authority_reject() -> None:
    window = _window()
    valid = _result(window)
    bad_span = SourceSpan(0, 1, "X")
    bad_mention = SubjectMentionCandidate(
        valid.subject_mentions[0].candidate_id,
        "林",
        (bad_span,),
    )
    with pytest.raises(ValueError, match="semantic result"):
        SharedSemanticResult(
            window=window,
            subject_mentions=(bad_mention,),
        )
    with pytest.raises(ValueError, match="semantic result"):
        SharedSemanticResult(window=window, authority=Authority.USER_CONFIRMED)


def test_view_shape_is_sparse_and_reader_view_has_no_observer() -> None:
    window = _window()
    target = ResolvedSubjectReference("00000000-0000-0000-0000-000000000010")
    with pytest.raises(ValueError, match="semantic result"):
        SharedSemanticResult(
            window=window,
            view_differences=(
                ViewDifferenceCandidate(
                    candidate_source_id(window, "view-difference", 0),
                    ViewType.READER_VIEW,
                    None,
                    target,
                    EpistemicStatus.KNOWS,
                    "知道",
                    (_span(window, 0, 1),),
                ),
            ),
        )


def test_aliases_remain_unresolved_without_auto_subject_creation() -> None:
    window = _window()
    alias = AliasCandidate(
        candidate_source_id(window, "alias", 0),
        "她",
        (_span(window, 5, 6),),
    )
    result = SharedSemanticResult(window=window, aliases=(alias,))
    assert result.aliases[0].resolved_subject is None


def test_caps_and_cross_window_ids_fail_closed() -> None:
    window = _window()
    with pytest.raises(ValueError, match="semantic result"):
        SharedSemanticResult(
            window=window,
            subject_mentions=tuple(
                SubjectMentionCandidate(
                    candidate_source_id(window, "subject-mention", index),
                    "林",
                    (_span(window, 0, 1),),
                )
                for index in range(101)
            ),
        )
    other = _window("另一段文本")
    with pytest.raises(ValueError, match="semantic result"):
        SharedSemanticResult(
            window=window,
            subject_mentions=(
                SubjectMentionCandidate(
                    candidate_source_id(other, "subject-mention", 0),
                    "另",
                    (_span(other, 0, 1),),
                ),
            ),
        )


def test_runtime_reference_types_and_xor_subject_routes_are_enforced() -> None:
    window = _window()
    valid = _result(window)
    link = valid.participant_links[0]
    with pytest.raises(ValueError, match="semantic result"):
        SharedSemanticResult(
            window=window,
            subject_mentions=valid.subject_mentions,
            occurrences=valid.occurrences,
            participant_links=(replace(link, subject="raw-id"),),  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="semantic result"):
        SharedSemanticResult(
            window=window,
            subject_mentions=valid.subject_mentions,
            occurrences=valid.occurrences,
            participant_links=(
                replace(link, subject_mention_candidate_id=None),
            ),
        )
    with pytest.raises(ValueError, match="semantic result"):
        SharedSemanticResult(
            window=window,
            aliases=(replace(valid.aliases[0], resolved_subject="raw-id"),)
            if valid.aliases
            else (
                AliasCandidate(
                    candidate_source_id(window, "alias", 0),
                    "林",
                    (_span(window, 0, 1),),
                    "raw-id",  # type: ignore[arg-type]
                ),
            ),
        )
    with pytest.raises(ValueError, match="semantic result"):
        SharedSemanticResult(
            window=window,
            view_differences=(
                replace(
                    valid.view_differences[0],
                    view_type="CHARACTER_VIEW",  # type: ignore[arg-type]
                ),
            ),
        )


def test_candidate_kind_is_closed_and_long_policy_ids_remain_valid() -> None:
    policy_version = "p" * 100
    window = project_semantic_windows(
        _CHAPTER_ID,
        0,
        _SOURCE_HASH,
        1,
        "文本",
        policy=SemanticWindowPolicy(policy_version, 6_000, 600),
    )[0]
    source_id = candidate_source_id(window, "participant-link", 9_999)
    assert source_id.endswith(":participant-link:9999")
    with pytest.raises(ValueError, match="semantic result"):
        candidate_source_id(window, "custom-kind", 0)
