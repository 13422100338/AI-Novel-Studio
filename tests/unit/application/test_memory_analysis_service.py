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


def _valid_summary() -> str:
    return (
        "## 剧情概况\n主角收到一封来源不明的信，并决定核对信上的旧暗号。\n"
        "## 关键情节点\n- 收到匿名旧信\n"
        "## 人物成长\n- 主角由迟疑转为主动调查\n"
        "## 连续性要点\n- 旧暗号属于失踪者\n"
        "## 细节摘录\n- 无"
    )


def _valid_payload() -> str:
    return json.dumps(
        {
            "summary": _valid_summary(),
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
                    "subject_type": "READER",
                    "subject_id": "READER",
                    "title": "暗号来源",
                    "detail": "读者看见林岚认出了暗号。",
                    "state": "KNOWN",
                },
                {
                    "subject_type": "CHARACTER",
                    "subject_id": "林岚",
                    "title": "旧人物知识输出",
                    "detail": "应由人物状态承载。",
                    "state": "KNOWN",
                },
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
    assert result.summary.content == _valid_summary()
    assert result.authority == Authority.MODEL_EXTRACTED
    assert result.review_status == ReviewStatus.REVIEW
    assert result.character_states[0].current_goal == "核对暗号"
    assert result.clues[0].clue_type.value == "FORESHADOW"
    assert result.knowledge[0].state.value == "KNOWN"
    assert len(result.knowledge) == 1
    assert result.knowledge[0].subject_type.value == "READER"
    assert result.style == ()

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
    assert "style" not in system_prompt
    assert "文风候选" not in system_prompt
    assert "## 剧情概况" in system_prompt
    assert "## 细节摘录" in system_prompt
    assert "## 伏笔与未决问题" not in system_prompt


def test_rejects_summary_missing_required_section() -> None:
    payload = json.loads(_valid_payload())
    payload["summary"] = _valid_summary().replace("## 人物成长\n- 主角由迟疑转为主动调查\n", "")
    gateway = RecordingGateway([json.dumps(payload, ensure_ascii=False)])
    service = MemoryAnalysisService(LLMContractRunner(gateway))  # type: ignore[arg-type]

    with pytest.raises(MemoryCandidateValidationError, match="人物成长"):
        service.extract_candidates("chapter-1", 0, "原稿正文")


def test_rejects_legacy_foreshadow_section_in_summary() -> None:
    payload = json.loads(_valid_payload())
    payload["summary"] = _valid_summary().replace(
        "## 连续性要点", "## 伏笔与未决问题\n- 一封信仍待解释\n## 连续性要点"
    )
    gateway = RecordingGateway([json.dumps(payload, ensure_ascii=False)])
    service = MemoryAnalysisService(LLMContractRunner(gateway))  # type: ignore[arg-type]

    with pytest.raises(MemoryCandidateValidationError, match="伏笔"):
        service.extract_candidates("chapter-1", 0, "原稿正文")


def test_rejects_plot_overview_longer_than_one_thousand_characters() -> None:
    payload = json.loads(_valid_payload())
    payload["summary"] = _valid_summary().replace(
        "主角收到一封来源不明的信，并决定核对信上的旧暗号。", "情" * 1001
    )
    gateway = RecordingGateway([json.dumps(payload, ensure_ascii=False)])
    service = MemoryAnalysisService(LLMContractRunner(gateway))  # type: ignore[arg-type]

    with pytest.raises(MemoryCandidateValidationError, match="1000"):
        service.extract_candidates("chapter-1", 0, "原稿正文")


def test_rejects_detail_excerpt_not_found_in_source_text() -> None:
    payload = json.loads(_valid_payload())
    payload["summary"] = _valid_summary().replace("- 无", "- 原文：模型虚构的原句")
    gateway = RecordingGateway([json.dumps(payload, ensure_ascii=False)])
    service = MemoryAnalysisService(LLMContractRunner(gateway))  # type: ignore[arg-type]

    with pytest.raises(MemoryCandidateValidationError, match="原文"):
        service.extract_candidates("chapter-1", 0, "原稿正文")


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
