from __future__ import annotations

import copy
import json
from collections.abc import Sequence

import pytest

from ai_novel_studio.application.shared_semantic_analysis_service import (
    SharedSemanticAnalysisService,
)
from ai_novel_studio.core.context.semantic_windowing import project_semantic_windows
from ai_novel_studio.core.context.shared_semantic_result import (
    SemanticCandidateKind,
    candidate_source_id,
)
from ai_novel_studio.domain.memory import Authority, ReviewStatus
from ai_novel_studio.domain.view import EpistemicStatus, ViewType
from ai_novel_studio.infrastructure.llm.contract_runner import (
    ContractValidationError,
    LLMContractRunner,
)
from ai_novel_studio.infrastructure.llm.schemas import (
    LLMMessage,
    LLMResponse,
    TaskPurpose,
)

_CHAPTER_ID = "11111111-1111-4111-8111-111111111111"
_HASH = "a" * 64
_TEXT = "林岚\r\n发现钥匙🙂\r\n读者误会"


class RecordingGateway:
    def __init__(self, responses: Sequence[dict[str, object] | str]) -> None:
        self._responses = list(responses)
        self.calls: list[
            tuple[
                TaskPurpose,
                tuple[LLMMessage, ...],
                int,
                float,
                bool,
            ]
        ] = []

    def complete(
        self,
        purpose: TaskPurpose,
        messages: tuple[LLMMessage, ...],
        output_token_limit: int,
        *,
        temperature: float = 0.7,
        json_mode: bool = False,
    ) -> LLMResponse:
        self.calls.append(
            (purpose, messages, output_token_limit, temperature, json_mode)
        )
        response = self._responses.pop(0)
        text = response if isinstance(response, str) else json.dumps(
            response, ensure_ascii=False
        )
        return LLMResponse(text=text, model_id="fake-model")


def _window():
    return project_semantic_windows(
        _CHAPTER_ID,
        3,
        _HASH,
        7,
        _TEXT,
    )[0]


def _span(text: str) -> dict[str, int]:
    start = _TEXT.index(text)
    return {"start": start, "end": start + len(text)}


def _valid_payload() -> dict[str, object]:
    return {
        "subject_mentions": [
            {"mention": "林岚", "spans": [_span("林岚")]},
            {"mention": "钥匙🙂", "spans": [_span("钥匙🙂")]},
        ],
        "aliases": [{"alias": "林岚", "spans": [_span("林岚")]}],
        "occurrences": [
            {
                "occurrence_type": "DISCOVERY",
                "title": "发现钥匙",
                "summary": "林岚发现钥匙",
                "spans": [_span("发现钥匙🙂")],
            }
        ],
        "participant_links": [
            {
                "subject_mention_ordinal": 0,
                "role": "observer",
                "subject_summary": "发现者",
                "spans": [_span("林岚")],
                "occurrence_ordinal": 0,
            }
        ],
        "state_changes": [
            {
                "subject_mention_ordinal": 0,
                "change_type": "HAS_KEY",
                "detail": "持有钥匙",
                "spans": [_span("发现钥匙🙂")],
                "occurrence_ordinal": 0,
            }
        ],
        "view_differences": [
            {
                "view_type": "CHARACTER_VIEW",
                "observer_mention_ordinal": 0,
                "target_mention_ordinal": 1,
                "epistemic_status": "KNOWS",
                "content": "林岚知道钥匙存在",
                "spans": [_span("发现钥匙🙂")],
                "occurrence_ordinal": 0,
            },
            {
                "view_type": "READER_VIEW",
                "target_mention_ordinal": 0,
                "content": "读者产生误会",
                "spans": [_span("读者误会")],
            },
        ],
        "summary": {
            "content": "林岚发现钥匙，读者误会。",
            "spans": [_span("发现钥匙🙂")],
        },
    }


def _service(
    responses: Sequence[dict[str, object] | str],
    *,
    output_token_limit: int | None = None,
) -> tuple[SharedSemanticAnalysisService, RecordingGateway]:
    gateway = RecordingGateway(responses)
    runner = LLMContractRunner(gateway)
    return (
        SharedSemanticAnalysisService(
            runner,
            output_token_limit=output_token_limit,
        ),
        gateway,
    )


def test_maps_exact_spans_ordinals_views_and_review_metadata() -> None:
    window = _window()
    service, gateway = _service([_valid_payload()])

    result = service.extract(window)

    assert result.window is window
    assert result.authority is Authority.MODEL_EXTRACTED
    assert result.review_status is ReviewStatus.REVIEW
    assert result.subject_mentions[1].spans[0].quote == "钥匙🙂"
    assert result.subject_mentions[1].candidate_id == candidate_source_id(
        window,
        SemanticCandidateKind.SUBJECT_MENTION,
        1,
    )
    occurrence_id = result.occurrences[0].candidate_id
    assert result.participant_links[0].occurrence_candidate_id == occurrence_id
    assert result.state_changes[0].occurrence_candidate_id == occurrence_id
    assert (
        result.participant_links[0].subject_mention_candidate_id
        == result.subject_mentions[0].candidate_id
    )
    character_view, reader_view = result.view_differences
    assert character_view.view_type is ViewType.CHARACTER_VIEW
    assert character_view.epistemic_status is EpistemicStatus.KNOWS
    assert (
        character_view.observer_mention_candidate_id
        == result.subject_mentions[0].candidate_id
    )
    assert reader_view.view_type is ViewType.READER_VIEW
    assert reader_view.observer_mention_candidate_id is None
    assert reader_view.epistemic_status is None
    purpose, messages, limit, temperature, json_mode = gateway.calls[0]
    assert purpose is TaskPurpose.MEMORY_EXTRACTION
    assert limit == 6_000
    assert temperature == 0.2
    assert json_mode is True
    assert len(messages) == 2
    assert _TEXT in messages[1].content
    assert _HASH not in messages[1].content


@pytest.mark.parametrize(
    ("collection", "mutation"),
    [
        ("subject_mentions", lambda item: item.update({"candidate_id": "bad"})),
        ("aliases", lambda item: item.pop("spans")),
        ("occurrences", lambda item: item.update({"source_hash": _HASH})),
        ("participant_links", lambda item: item.update({"subject_id": "bad"})),
        ("state_changes", lambda item: item.update({"provenance": "bad"})),
        (
            "view_differences",
            lambda item: item.update({"participant_link_ids": []}),
        ),
    ],
)
def test_nested_objects_have_exact_required_fields(
    collection: str,
    mutation,
) -> None:
    invalid = _valid_payload()
    values = invalid[collection]
    assert isinstance(values, list)
    item = values[0]
    assert isinstance(item, dict)
    mutation(item)
    service, gateway = _service([invalid, invalid])

    with pytest.raises(ContractValidationError) as caught:
        service.extract(_window())

    assert len(gateway.calls) == 2
    assert "bad" not in str(caught.value)
    assert _HASH not in str(caught.value)


def test_invalid_first_payload_is_corrected_inside_runner_validator() -> None:
    invalid = _valid_payload()
    links = invalid["participant_links"]
    assert isinstance(links, list)
    link = links[0]
    assert isinstance(link, dict)
    link["subject_mention_ordinal"] = True
    service, gateway = _service([invalid, _valid_payload()])

    result = service.extract(_window())

    assert len(result.participant_links) == 1
    assert len(gateway.calls) == 2
    correction_messages = gateway.calls[1][1]
    assert correction_messages[-1].role == "user"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("subject_mention_ordinal", -1),
        ("subject_mention_ordinal", True),
        ("subject_mention_ordinal", 2),
        ("occurrence_ordinal", 1),
    ],
)
def test_invalid_ordinals_fail_closed(field: str, value: object) -> None:
    invalid = _valid_payload()
    links = invalid["participant_links"]
    assert isinstance(links, list)
    link = links[0]
    assert isinstance(link, dict)
    link[field] = value
    service, _ = _service([invalid, invalid])

    with pytest.raises(ContractValidationError):
        service.extract(_window())


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload["subject_mentions"][0].update(  # type: ignore[index,union-attr]
            {"spans": [{"start": True, "end": 1}]}
        ),
        lambda payload: payload["subject_mentions"][0].update(  # type: ignore[index,union-attr]
            {"spans": [{"start": 0, "end": len(_TEXT) + 1}]}
        ),
        lambda payload: payload["subject_mentions"][0].update(  # type: ignore[index,union-attr]
            {"mention": "x" * 4_001}
        ),
        lambda payload: payload["subject_mentions"][0].update(  # type: ignore[index,union-attr]
            {"spans": [_span("林岚")] * 33}
        ),
    ],
)
def test_span_and_text_amplification_is_bounded(mutation) -> None:
    invalid = _valid_payload()
    mutation(invalid)
    service, _ = _service([invalid, invalid])

    with pytest.raises(ContractValidationError):
        service.extract(_window())


def test_aggregate_candidate_limit_includes_summary() -> None:
    invalid = _valid_payload()
    seed = {
        "subject_mention_ordinal": 0,
        "role": "observer",
        "subject_summary": "观察者",
        "spans": [_span("林岚")],
    }
    invalid["subject_mentions"] = [
        {"mention": "林岚", "spans": [_span("林岚")]}
        for _ in range(100)
    ]
    invalid["aliases"] = [
        {"alias": "林岚", "spans": [_span("林岚")]}
        for _ in range(100)
    ]
    invalid["occurrences"] = [
        {
            "occurrence_type": "EVENT",
            "title": "事件",
            "summary": "事件",
            "spans": [_span("林岚")],
        }
        for _ in range(100)
    ]
    invalid["participant_links"] = [copy.deepcopy(seed) for _ in range(500)]
    invalid["state_changes"] = [
        {
            "subject_mention_ordinal": 0,
            "change_type": "CHANGE",
            "detail": "变化",
            "spans": [_span("林岚")],
        }
        for _ in range(100)
    ]
    invalid["view_differences"] = [
        {
            "view_type": "READER_VIEW",
            "target_mention_ordinal": 0,
            "content": "读者认知",
            "spans": [_span("林岚")],
        }
        for _ in range(100)
    ]
    service, _ = _service([invalid, invalid])

    with pytest.raises(ContractValidationError):
        service.extract(_window())


def test_invalid_second_output_is_sanitized() -> None:
    raw_marker = "C:\\secret\\novel.txt sk-live BODY-MARKER"
    invalid = _valid_payload()
    invalid[raw_marker] = raw_marker
    service, _ = _service([invalid, invalid])

    with pytest.raises(ContractValidationError) as caught:
        service.extract(_window())

    message = str(caught.value)
    assert raw_marker not in message
    assert _TEXT not in message
    assert _HASH not in message


def test_prompt_freezes_exact_schema_and_single_window_scope() -> None:
    service, gateway = _service([_valid_payload()], output_token_limit=7_000)

    service.extract(_window())

    purpose, messages, limit, _, json_mode = gateway.calls[0]
    prompt = messages[0].content
    assert purpose is TaskPurpose.MEMORY_EXTRACTION
    assert limit == 7_000
    assert json_mode
    for field in (
        "subject_mentions",
        "participant_links",
        "occurrence_ordinal",
        "observer_mention_ordinal",
        "epistemic_status",
        "summary",
        "candidate",
        "subject",
        "provenance",
    ):
        assert field in prompt
    assert "CHARACTER_VIEW" in prompt
    assert "READER_VIEW" in prompt
    assert messages[1].content.count("<window_text>") == 1


def test_invalid_window_and_output_limit_reject_before_model_call() -> None:
    service, gateway = _service([])
    with pytest.raises(TypeError):
        service.extract(None)  # type: ignore[arg-type]
    assert gateway.calls == []
    for value in (True, 0, 200_001, "6000"):
        with pytest.raises(ValueError):
            SharedSemanticAnalysisService(
                LLMContractRunner(gateway),
                output_token_limit=value,  # type: ignore[arg-type]
            )
