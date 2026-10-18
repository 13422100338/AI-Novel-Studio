from __future__ import annotations

from pathlib import Path

import pytest

from ai_novel_studio.application.chapter_revision_service import ChapterRevisionService
from ai_novel_studio.application.project_constitution_service import (
    ProjectConstitutionService,
)
from ai_novel_studio.core.context.token_budget import TokenBudget
from ai_novel_studio.domain.project_constitution import (
    ConstitutionRule,
    ProjectConstitutionProposal,
)
from ai_novel_studio.harness.artifacts import ArtifactKind, ArtifactStore, FileArtifactBackend
from ai_novel_studio.harness.core_tools import (
    CORE_TOOL_DEFINITIONS,
    TOOL_ARTIFACT_READ,
    TOOL_CONTEXT_COMPILE,
    TOOL_MANUSCRIPT_GET_SELECTION,
    TOOL_MANUSCRIPT_READ,
    TOOL_MEMORY_QUERY,
    TOOL_PLAN_QUERY,
    TOOL_PROJECT_CONSTITUTION_READ,
    TOOL_SUBJECT_QUERY,
    TOOL_TOOL_SEARCH,
    CoreToolResult,
    CoreToolService,
    register_core_tools,
)
from ai_novel_studio.harness.event_repository import HarnessEventRepository
from ai_novel_studio.harness.event_store import HarnessEventStore
from ai_novel_studio.harness.permission_gateway import (
    GateContext,
    GateDecision,
    PermissionGateway,
)
from ai_novel_studio.harness.run_state import RunStage
from ai_novel_studio.harness.subject_tools import register_subject_tools
from ai_novel_studio.harness.tool_registry import ToolRegistry
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_constitution_repository import (
    ProjectConstitutionRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository

_CONTENT = "第一段😀\r\n\r\n第二段证据\r\n"


def _service(tmp_path: Path):
    project = ProjectRepository.create(tmp_path / "novel", "Core tools")
    volume = project.list_volumes()[0]
    revisions = ChapterRevisionService(project)
    source = revisions.submit_creation(
        volume.id, "Evidence source", content=_CONTENT
    ).chapter
    target = revisions.submit_creation(
        volume.id, "Generation target", content="目标正文"
    ).chapter
    store = HarnessEventStore(HarnessEventRepository(project))
    run, _ = store.start_run(goal="核心工具", active_chapter_id=target.id)
    registry = ToolRegistry()
    register_core_tools(registry)
    register_subject_tools(registry)
    artifacts = ArtifactStore(FileArtifactBackend(tmp_path / "artifacts"))
    service = CoreToolService.for_project(
        project,
        budget=TokenBudget(4096, 512, 128),
        registry=registry,
        artifacts=artifacts,
    )
    return project, source, target, store, run, registry, artifacts, service


def _constitution_proposal() -> ProjectConstitutionProposal:
    return ProjectConstitutionProposal(
        base_revision=0,
        shared_creative_rules=(ConstitutionRule("tone.default", "压抑克制"),),
        agent_only_rules=(ConstitutionRule("agent.planning", "先提问再计划"),),
        writer_only_rules=(),
        overridable_rules=(ConstitutionRule("tone.default", "压抑克制"),),
        non_overridable_rules=(ConstitutionRule("canon.locked", "禁止改写已确认设定"),),
        source_decisions=("已确认:基调压抑",),
        behavior_note="影响正文与剧情模型",
    )


def test_definitions_are_read_only_and_allowed_by_gateway(tmp_path: Path) -> None:
    _project, *_rest, registry, _artifacts, service = _service(tmp_path)
    gateway = PermissionGateway(registry)
    context = GateContext(
        run_stage=RunStage.CREATED,
        expected_revision=None,
        idempotency_key=None,
        project_scope_enabled=True,
        run_scope_enabled=True,
    )

    assert len(CORE_TOOL_DEFINITIONS) == 9
    for definition in CORE_TOOL_DEFINITIONS:
        decision = gateway.evaluate(definition.id, context=context)
        assert decision.decision is GateDecision.ALLOWED, definition.id


def test_context_compile_tool_returns_manifest_and_evidence(tmp_path: Path) -> None:
    _project, _source, target, _store, run, _registry, _artifacts, service = _service(
        tmp_path
    )

    result = service.execute(
        TOOL_CONTEXT_COMPILE,
        {
            "chapter_id": target.id,
            "evidence_requests": [{"kind": "EXACT_QUOTE", "query": "第二段证据"}],
        },
        run_id=run.id,
    )

    assert isinstance(result, CoreToolResult)
    assert "manifest_id=" in result.content
    assert "evidence_hit_count=1" in result.content
    assert "第二段证据" in result.content


def test_manuscript_read_and_selection(tmp_path: Path) -> None:
    _project, _source, target, _store, run, _registry, _artifacts, service = _service(
        tmp_path
    )

    read = service.execute(
        TOOL_MANUSCRIPT_READ, {"chapter_id": target.id}, run_id=run.id
    )
    assert "Generation target" in read.content
    assert "目标正文" in read.content

    selection = service.execute(
        TOOL_MANUSCRIPT_GET_SELECTION,
        {"chapter_id": target.id, "start_offset": 1, "end_offset": 3},
        run_id=run.id,
    )
    assert selection.content == "标正"

    defaulted = service.execute(
        TOOL_MANUSCRIPT_GET_SELECTION, {}, run_id=run.id
    )
    assert defaulted.content == "目标正文"

    with pytest.raises(ValueError):
        service.execute(
            TOOL_MANUSCRIPT_GET_SELECTION,
            {"start_offset": 5, "end_offset": 2},
            run_id=run.id,
        )


def test_subject_query_by_name_alias_and_substring(tmp_path: Path) -> None:
    project, _source, _target, _store, run, _registry, _artifacts, service = _service(
        tmp_path
    )
    memory = CharacterMemoryRepository(project)
    memory.create_character("艾瑞克", aliases=("白鸦镇领主",))

    by_name = service.execute(
        TOOL_SUBJECT_QUERY, {"query": "艾瑞克"}, run_id=run.id
    )
    assert "subject_id=" in by_name.content
    by_alias = service.execute(
        TOOL_SUBJECT_QUERY, {"query": "白鸦镇领主"}, run_id=run.id
    )
    assert "艾瑞克" in by_alias.content
    by_part = service.execute(TOOL_SUBJECT_QUERY, {"query": "艾瑞"}, run_id=run.id)
    assert "艾瑞克" in by_part.content
    missing = service.execute(
        TOOL_SUBJECT_QUERY, {"query": "不存在的人"}, run_id=run.id
    )
    assert "未找到" in missing.content


def test_plan_query_tags_author_plan(tmp_path: Path) -> None:
    _project, _source, target, _store, run, _registry, _artifacts, service = _service(
        tmp_path
    )

    result = service.execute(TOOL_PLAN_QUERY, {"chapter_id": target.id}, run_id=run.id)

    assert "AUTHOR_PLAN" in result.content
    assert "计划，不是正典" in result.content
    assert "项目指引" in result.content


def test_memory_query_requires_narrative_boundary(tmp_path: Path) -> None:
    project, _source, target, store, run, _registry, _artifacts, service = _service(
        tmp_path
    )
    orphan_run, _ = store.start_run(goal="无章节边界")

    with pytest.raises(ValueError, match="叙事边界"):
        service.execute(
            TOOL_MEMORY_QUERY, {"query": "第二段证据"}, run_id=orphan_run.id
        )

    result = service.execute(
        TOOL_MEMORY_QUERY,
        {"query": "第二段证据", "before_chapter_id": target.id},
        run_id=run.id,
    )
    assert "Evidence source" in result.content


def test_constitution_read_renders_revision_or_none(tmp_path: Path) -> None:
    project, _source, _target, _store, run, _registry, _artifacts, service = _service(
        tmp_path
    )

    empty = service.execute(TOOL_PROJECT_CONSTITUTION_READ, {}, run_id=run.id)
    assert "尚未确立" in empty.content

    ProjectConstitutionService(ProjectConstitutionRepository(project)).commit(
        _constitution_proposal(),
        approved_by_author=True,
        expected_revision=0,
    )
    rendered = service.execute(TOOL_PROJECT_CONSTITUTION_READ, {}, run_id=run.id)
    assert "v1" in rendered.content
    assert "tone.default" in rendered.content
    assert "压抑克制" in rendered.content


def test_artifact_read_excerpts_by_content_address(tmp_path: Path) -> None:
    _project, *_rest, _store, run, _registry, artifacts, service = _service(tmp_path)
    artifact = artifacts.put(
        ArtifactKind.TOOL_RESULT, run.id, "很长的工具结果正文".encode()
    )

    result = service.execute(
        TOOL_ARTIFACT_READ, {"artifact_id": artifact.artifact_id}, run_id=run.id
    )

    assert artifact.artifact_id in result.content
    assert "很长的工具结果正文" in result.content
    with pytest.raises(ValueError, match="sha256"):
        service.execute(TOOL_ARTIFACT_READ, {"artifact_id": "bad-id"}, run_id=run.id)


def test_tool_search_matches_registry_ids(tmp_path: Path) -> None:
    _project, *_rest, _store, run, _registry, _artifacts, service = _service(tmp_path)

    result = service.execute(TOOL_TOOL_SEARCH, {"query": "subject."}, run_id=run.id)

    assert "subject.inspect" in result.content
    assert "subject.propose_merge" in result.content
    missing = service.execute(TOOL_TOOL_SEARCH, {"query": "no.such"}, run_id=run.id)
    assert "未找到" in missing.content


def test_bad_arguments_fail_deterministically(tmp_path: Path) -> None:
    _project, _source, target, _store, run, _registry, _artifacts, service = _service(
        tmp_path
    )

    with pytest.raises(ValueError):
        service.execute(TOOL_MANUSCRIPT_READ, {"chapter_id": "not-a-uuid"}, run_id=run.id)
    with pytest.raises(ValueError):
        service.execute(
            TOOL_CONTEXT_COMPILE,
            {"chapter_id": target.id, "evidence_requests": [{"kind": "BAD"}]},
            run_id=run.id,
        )
    with pytest.raises(KeyError):
        service.execute("manuscript.write", {}, run_id=run.id)
