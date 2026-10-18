from __future__ import annotations

from pathlib import Path

import pytest

from ai_novel_studio.harness.approval_repository import ApprovalRepository
from ai_novel_studio.harness.approvals import ApprovalKind, ApprovalStatus
from ai_novel_studio.harness.event_repository import HarnessEventRepository
from ai_novel_studio.harness.event_store import HarnessEventStore
from ai_novel_studio.harness.permission_gateway import (
    GateContext,
    GateDecision,
    PermissionGateway,
)
from ai_novel_studio.harness.run_state import RunStage
from ai_novel_studio.harness.subject_tools import (
    SUBJECT_TOOL_DEFINITIONS,
    TOOL_SUBJECT_COMPARE,
    TOOL_SUBJECT_INSPECT,
    TOOL_SUBJECT_PREVIEW_MERGE,
    TOOL_SUBJECT_PROPOSE_MERGE,
    SubjectToolResult,
    SubjectToolService,
    register_subject_tools,
)
from ai_novel_studio.harness.tool_registry import ToolRegistry
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.subject_repository import SubjectRepository


def _service(tmp_path: Path):
    project = ProjectRepository.create(tmp_path / "novel", "Subject tools")
    store = HarnessEventStore(HarnessEventRepository(project))
    service = SubjectToolService.for_project(project)
    run, _ = store.start_run(goal="检查人物卡")
    memory = CharacterMemoryRepository(project)
    source = memory.create_character("艾瑞克", aliases=("白鸦镇领主",))
    target = memory.create_character("艾瑞克·温德米尔")
    return project, store, service, run, source, target


def _gate() -> tuple[ToolRegistry, PermissionGateway]:
    registry = ToolRegistry()
    register_subject_tools(registry)
    return registry, PermissionGateway(registry)


def test_definitions_registered_and_gateway_decisions(tmp_path: Path) -> None:
    registry, gateway = _gate()

    assert {definition.id for definition in registry.snapshot()} == {
        TOOL_SUBJECT_INSPECT,
        TOOL_SUBJECT_COMPARE,
        TOOL_SUBJECT_PREVIEW_MERGE,
        TOOL_SUBJECT_PROPOSE_MERGE,
    }
    allowed = GateContext(
        run_stage=RunStage.CREATED,
        expected_revision=None,
        idempotency_key=None,
        project_scope_enabled=True,
        run_scope_enabled=True,
    )
    for tool_id in (TOOL_SUBJECT_INSPECT, TOOL_SUBJECT_COMPARE, TOOL_SUBJECT_PREVIEW_MERGE):
        decision = gateway.evaluate(tool_id, context=allowed)
        assert decision.decision is GateDecision.ALLOWED

    denied = gateway.evaluate(TOOL_SUBJECT_PROPOSE_MERGE, context=allowed)
    assert denied.decision is GateDecision.DENIED
    assert "idempotency_key" in (denied.reason or "")

    keyed = GateContext(
        run_stage=RunStage.CREATED,
        expected_revision=None,
        idempotency_key="key-1",
        project_scope_enabled=True,
        run_scope_enabled=True,
    )
    assert (
        gateway.evaluate(TOOL_SUBJECT_PROPOSE_MERGE, context=keyed).decision
        is GateDecision.ALLOWED
    )
    closed = GateContext(
        run_stage=RunStage.CANCELLED,
        expected_revision=None,
        idempotency_key="key-1",
        project_scope_enabled=True,
        run_scope_enabled=True,
    )
    assert (
        gateway.evaluate(TOOL_SUBJECT_INSPECT, context=closed).decision
        is GateDecision.DENIED
    )


def test_inspect_renders_subject_cards(tmp_path: Path) -> None:
    _project, _store, service, _run, source, _target = _service(tmp_path)

    result = service.execute(
        TOOL_SUBJECT_INSPECT, {"subject_ids": [source.id]}, run_id="run-x"
    )

    assert isinstance(result, SubjectToolResult)
    assert "艾瑞克" in result.content
    assert source.id in result.content
    assert "白鸦镇领主" in result.content
    assert result.approval_request_id is None


def test_compare_renders_both_cards_and_preview(tmp_path: Path) -> None:
    _project, _store, service, _run, source, target = _service(tmp_path)

    result = service.execute(
        TOOL_SUBJECT_COMPARE,
        {"source_subject_id": source.id, "target_subject_id": target.id},
        run_id="run-x",
    )

    assert "艾瑞克·温德米尔" in result.content
    assert "共享章节冲突" in result.content


def test_preview_merge_is_read_only(tmp_path: Path) -> None:
    project, _store, service, _run, source, target = _service(tmp_path)

    result = service.execute(
        TOOL_SUBJECT_PREVIEW_MERGE,
        {"source_subject_id": source.id, "target_subject_id": target.id},
        run_id="run-x",
    )

    assert "状态事件数" in result.content
    assert "可逆:True" in result.content
    assert CharacterMemoryRepository(project).get_character(source.id) is not None


def test_propose_merge_creates_pending_approval(tmp_path: Path) -> None:
    project, store, service, run, source, target = _service(tmp_path)

    result = service.execute(
        TOOL_SUBJECT_PROPOSE_MERGE,
        {
            "source_subject_id": source.id,
            "target_subject_id": target.id,
            "reason": "同一人物",
            "idempotency_key": "sm-1",
        },
        run_id=run.id,
    )

    assert result.approval_request_id is not None
    approval = ApprovalRepository(project).get(result.approval_request_id)
    assert approval.kind is ApprovalKind.SUBJECT_MERGE
    assert approval.status is ApprovalStatus.PENDING
    assert approval.payload["source_character_id"] == source.id
    assert approval.payload["target_character_id"] == target.id
    assert approval.payload["reason"] == "同一人物"
    assert approval.payload["preview_snapshot"]["source_canonical_name"] == "艾瑞克"
    assert approval.expected_revisions[0][0] == f"subject.state_events:{source.id}"
    assert store.get_run(run.id).stage is RunStage.WAITING_APPROVAL
    # 零领域写入:两张卡都还在
    memory = CharacterMemoryRepository(project)
    assert memory.get_character(source.id).canonical_name == "艾瑞克"
    assert memory.get_character(target.id).canonical_name == "艾瑞克·温德米尔"


def test_propose_merge_is_idempotent_per_key(tmp_path: Path) -> None:
    _project, _store, service, run, source, target = _service(tmp_path)
    arguments = {
        "source_subject_id": source.id,
        "target_subject_id": target.id,
        "reason": "同一人物",
        "idempotency_key": "sm-1",
    }

    first = service.execute(TOOL_SUBJECT_PROPOSE_MERGE, arguments, run_id=run.id)
    second = service.execute(TOOL_SUBJECT_PROPOSE_MERGE, arguments, run_id=run.id)

    assert first.approval_request_id == second.approval_request_id


def test_propose_merge_unknown_subject_creates_no_approval(tmp_path: Path) -> None:
    project, _store, service, run, _source, target = _service(tmp_path)
    unknown = str(
        __import__("uuid").uuid4()
    )

    with pytest.raises(ValueError):
        service.execute(
            TOOL_SUBJECT_PROPOSE_MERGE,
            {
                "source_subject_id": unknown,
                "target_subject_id": target.id,
                "reason": "同一人物",
                "idempotency_key": "sm-1",
            },
            run_id=run.id,
        )

    assert ApprovalRepository(project).list_for_run(run.id) == ()


def test_tool_validation_errors(tmp_path: Path) -> None:
    _project, _store, service, run, source, target = _service(tmp_path)

    with pytest.raises(ValueError):
        service.execute(
            TOOL_SUBJECT_PROPOSE_MERGE,
            {
                "source_subject_id": source.id,
                "target_subject_id": target.id,
                "reason": "同一人物",
            },
            run_id=run.id,
        )
    with pytest.raises(ValueError):
        service.execute(
            TOOL_SUBJECT_COMPARE,
            {"source_subject_id": source.id, "target_subject_id": source.id},
            run_id=run.id,
        )
    with pytest.raises(KeyError):
        service.execute("subject.commit", {}, run_id=run.id)


def test_inspect_via_subject_repository_ids(tmp_path: Path) -> None:
    _project, _store, service, _run, source, _target = _service(tmp_path)
    subject = SubjectRepository(_project).resolve_character_name("艾瑞克")[0]

    result = service.execute(
        TOOL_SUBJECT_INSPECT, {"subject_ids": [subject.id]}, run_id="run-x"
    )

    assert subject.id in result.content
    assert source.id == subject.id


def test_definitions_have_stable_schemas() -> None:
    by_id = {definition.id: definition for definition in SUBJECT_TOOL_DEFINITIONS}
    assert by_id[TOOL_SUBJECT_INSPECT].version == 1
    assert by_id[TOOL_SUBJECT_PROPOSE_MERGE].input_schema["required"] == [
        "source_subject_id",
        "target_subject_id",
        "reason",
        "idempotency_key",
    ]
