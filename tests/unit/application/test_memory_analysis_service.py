import json

import pytest

from ai_novel_studio.application.memory_analysis_service import (
    MemoryAnalysisService,
    MemoryCandidateValidationError,
)
from ai_novel_studio.domain.memory import Authority, ReviewStatus
from ai_novel_studio.infrastructure.llm.contract_runner import LLMContractRunner
from ai_novel_studio.infrastructure.llm.schemas import LLMResponse, TaskPurpose


class RecordingGateway:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[tuple[TaskPurpose, tuple[object, ...], int, dict[str, object]]] = []

    def complete(  # type: ignore[no-untyped-def]
        self, purpose, messages, output_token_limit, **kwargs
    ):
        self.calls.append((purpose, messages, output_token_limit, kwargs))
        return LLMResponse(self.responses.pop(0), "memory-model")


def _valid_payload() -> str:
    return json.dumps(
        {
            "summary": "主角收到一封来源不明的信。",
            "character_states": [
                {
                    "character_name": "林岚",
                    "motivation": "查清寄信人",
                    "psychology": "警惕",
                    "current_goal": "核对暗号",
                    "relationships": "暂未变化",
                    "recent_activity": "收到来信",
                }
            ],
            "canon": [{"title": "暗号", "detail": "暗号属于失踪者。"}],
            "clues": [
                {
                    "clue_type": "FORESHADOW",
                    "title": "旧暗号",
                    "detail": "暗号再次出现。",
                    "action": "PLANT",
                }
            ],
            "knowledge": [
                {
                    "subject_type": "CHARACTER",
                    "subject_id": "character-lin",
                    "title": "暗号来源",
                    "detail": "林岚认出了暗号。",
                    "state": "KNOWN",
                }
            ],
            "style": [
                {
                    "scope_type": "CHAPTER",
                    "scope_id": "chapter-1",
                    "rule_type": "叙述节奏",
                    "rule_text": "本章使用短句制造紧张感。",
                }
            ],
        },
        ensure_ascii=False,
    )


def test_extracts_review_candidates_with_source_provenance_and_ordered_prompt() -> None:
    gateway = RecordingGateway([_valid_payload()])
    service = MemoryAnalysisService(LLMContractRunner(gateway), output_token_limit=6_000)  # type: ignore[arg-type]

    result = service.extract_candidates("chapter-1", 3, "原稿正文")

    assert result.source_chapter_id == "chapter-1"
    assert result.source_revision == 3
    assert result.summary.content == "主角收到一封来源不明的信。"
    assert result.authority == Authority.MODEL_EXTRACTED
    assert result.review_status == ReviewStatus.REVIEW
    assert result.character_states[0].current_goal == "核对暗号"
    assert result.clues[0].clue_type.value == "FORESHADOW"
    assert result.knowledge[0].state.value == "KNOWN"

    purpose, messages, output_limit, options = gateway.calls[0]
    assert purpose == TaskPurpose.MEMORY_EXTRACTION
    assert [message.role for message in messages] == ["system", "user"]  # type: ignore[attr-defined]
    assert "chapter-1" in messages[1].content  # type: ignore[attr-defined]
    assert messages[1].content.index("revision=3") < messages[1].content.index("原稿正文")  # type: ignore[attr-defined]
    assert output_limit == 6_000
    assert options == {"temperature": 0.2, "json_mode": True}


def test_rejects_invalid_nested_model_output_without_saving_or_guessing() -> None:
    payload = json.loads(_valid_payload())
    payload["clues"][0]["clue_type"] = "UNSUPPORTED"
    gateway = RecordingGateway([json.dumps(payload, ensure_ascii=False)])
    service = MemoryAnalysisService(LLMContractRunner(gateway))  # type: ignore[arg-type]

    with pytest.raises(MemoryCandidateValidationError, match="clue_type"):
        service.extract_candidates("chapter-1", 0, "原稿正文")

    assert len(gateway.calls) == 1


def test_empty_source_is_rejected_before_calling_the_model() -> None:
    gateway = RecordingGateway([_valid_payload()])
    service = MemoryAnalysisService(LLMContractRunner(gateway))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="正文"):
        service.extract_candidates("chapter-1", 0, "  ")

    assert gateway.calls == []


def test_default_memory_output_budget_is_dynamic_and_bounded() -> None:
    gateway = RecordingGateway([_valid_payload(), _valid_payload()])
    service = MemoryAnalysisService(LLMContractRunner(gateway))  # type: ignore[arg-type]

    service.extract_candidates("chapter-short", 0, "短正文" * 100)
    service.extract_candidates("chapter-long", 0, "长正文" * 10_000)

    short_limit = gateway.calls[0][2]
    long_limit = gateway.calls[1][2]
    assert 2_400 <= short_limit < long_limit <= 6_000


def test_memory_prompt_declares_nested_enum_values_and_structured_summary() -> None:
    gateway = RecordingGateway([_valid_payload()])
    service = MemoryAnalysisService(LLMContractRunner(gateway))  # type: ignore[arg-type]

    service.extract_candidates("chapter-1", 0, "原稿正文")

    system_prompt = gateway.calls[0][1][0].content  # type: ignore[attr-defined]
    assert "FORESHADOW" in system_prompt
    assert "PLANT" in system_prompt
    assert "## 剧情概况" in system_prompt


def test_character_state_allows_unknown_fields_as_empty_strings() -> None:
    payload = json.loads(_valid_payload())
    payload["character_states"][0]["relationships"] = ""
    gateway = RecordingGateway([json.dumps(payload, ensure_ascii=False)])
    service = MemoryAnalysisService(LLMContractRunner(gateway))  # type: ignore[arg-type]

    result = service.extract_candidates("chapter-1", 0, "原稿正文")

    assert result.character_states[0].relationships == ""


def test_character_state_normalizes_unknown_null_to_empty_string() -> None:
    payload = json.loads(_valid_payload())
    payload["character_states"][0]["relationships"] = None
    gateway = RecordingGateway([json.dumps(payload, ensure_ascii=False)])
    service = MemoryAnalysisService(LLMContractRunner(gateway))  # type: ignore[arg-type]

    result = service.extract_candidates("chapter-1", 0, "原稿正文")

    assert result.character_states[0].relationships == ""


def test_character_state_normalizes_relationship_object_to_readable_text() -> None:
    payload = json.loads(_valid_payload())
    payload["character_states"][0]["relationships"] = {
        "苏砚": "暂不信任",
        "来信者": ["身份未知", "保持警惕"],
    }
    gateway = RecordingGateway([json.dumps(payload, ensure_ascii=False)])
    service = MemoryAnalysisService(LLMContractRunner(gateway))  # type: ignore[arg-type]

    result = service.extract_candidates("chapter-1", 0, "原稿正文")

    assert result.character_states[0].relationships == (
        "苏砚：暂不信任；来信者：身份未知；保持警惕"
    )
