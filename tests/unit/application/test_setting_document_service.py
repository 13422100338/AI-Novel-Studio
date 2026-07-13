from __future__ import annotations

from pathlib import Path

import pytest

from ai_novel_studio.application.setting_document_service import (
    SettingDocumentAnalysisService,
    SettingDocumentMemoryService,
)
from ai_novel_studio.domain.memory import ReviewStatus
from ai_novel_studio.infrastructure.llm.schemas import TaskPurpose
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class _Runner:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.purpose: TaskPurpose | None = None

    def run_json(self, purpose, messages, output_limit, contract):
        self.purpose = purpose
        return contract.validate(self.payload)


def _payload() -> dict[str, object]:
    return {
        "summary": "王国以记忆税维持魔法体系。",
        "characters": [{"name": "林默", "aliases": "小林", "profile": "谨慎的调查员。"}],
        "canon": [{"title": "魔法代价", "detail": "施法会损耗记忆。"}],
        "clues": [{"title": "失踪名册", "detail": "计划在第三卷揭示。"}],
        "style": [{"rule_type": "叙事视角", "rule_text": "限知第三人称。"}],
        "uncertain": ["导师是否死亡尚未确定"],
    }


def test_setting_analysis_uses_memory_route_and_validates_nested_fields() -> None:
    runner = _Runner(_payload())
    result = SettingDocumentAnalysisService(runner).analyze("设定", "混合设定", "正文")
    assert runner.purpose == TaskPurpose.MEMORY_EXTRACTION
    assert result.characters[0][0] == "林默"
    assert result.style == (("叙事视角", "限知第三人称。"),)


def test_setting_analysis_accepts_alias_text_array() -> None:
    payload = _payload()
    payload["characters"] = [
        {
            "name": "林默",
            "aliases": ["小林", " 阿默 ", "小林"],
            "profile": "资料",
        }
    ]

    result = SettingDocumentAnalysisService(_Runner(payload)).analyze(
        "设定", "混合设定", "正文"
    )

    assert result.characters == (("林默", "小林、阿默", "资料"),)


def test_setting_analysis_rejects_invalid_nested_model_output() -> None:
    payload = _payload()
    payload["characters"] = [
        {"name": "林默", "aliases": ["小林", 7], "profile": "资料"}
    ]
    with pytest.raises(ValueError, match="aliases"):
        SettingDocumentAnalysisService(_Runner(payload)).analyze("设定", "混合设定", "正文")


def test_setting_source_and_candidates_are_not_silently_approved(tmp_path: Path) -> None:
    project = ProjectRepository.create(tmp_path / "novel", "Novel")
    service = SettingDocumentMemoryService(SettingDocumentAnalysisService(_Runner(_payload())))
    report = service.analyze_and_store(project, "设定", "混合设定", "用户原始资料")

    with project.database.connect() as connection:
        source = connection.execute(
            "SELECT content, review_status FROM memory_documents "
            "WHERE document_type = 'SETTING_SOURCE' AND source_id = ?",
            (report.source_id,),
        ).fetchone()
        canon = connection.execute(
            "SELECT review_status, source_paragraph_id FROM canon_entries"
        ).fetchall()
        styles = connection.execute("SELECT review_status FROM style_rules").fetchall()

    assert source["content"] == "用户原始资料"
    assert source["review_status"] == ReviewStatus.APPROVED.value
    assert canon and all(row["review_status"] == ReviewStatus.REVIEW.value for row in canon)
    assert all(row["source_paragraph_id"] == f"SETTING:{report.source_id}" for row in canon)
    assert styles and all(row["review_status"] == ReviewStatus.REVIEW.value for row in styles)
