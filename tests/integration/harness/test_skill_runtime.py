from __future__ import annotations

from pathlib import Path

import pytest

from ai_novel_studio.harness.event_repository import HarnessEventRepository
from ai_novel_studio.harness.event_store import HarnessEventStore
from ai_novel_studio.harness.run_state import RunEventType, RunStage
from ai_novel_studio.harness.skill_catalog import Skill, SkillCatalog
from ai_novel_studio.harness.skill_runtime import SkillRuntimeService
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def _skill(catalog: SkillCatalog, skill_id: str = "chapter_audit") -> None:
    catalog.register(
        Skill(
            skill_id,
            2,
            "检查章节事实与知识边界",
            "逐条核对事实、人物状态与知识边界。",
            ("recent_chapter_texts",),
            ("subject.inspect",),
            {"type": "object"},
        )
    )


def _runtime(tmp_path: Path):
    project = ProjectRepository.create(tmp_path / "novel", "Skill runtime")
    store = HarnessEventStore(HarnessEventRepository(project))
    catalog = SkillCatalog()
    _skill(catalog)
    run, _ = store.start_run(goal="加载技能")
    return store, SkillRuntimeService(store, catalog), run


def test_load_records_event_and_returns_full_skill(tmp_path: Path) -> None:
    store, runtime, run = _runtime(tmp_path)

    skill = runtime.load_for_run(run.id, "chapter_audit")

    assert skill.id == "chapter_audit"
    assert skill.version == 2
    assert runtime.loaded_ids(run.id) == ("chapter_audit",)
    events = store.replay(run.id)
    loaded = [event for event in events if event.event_type is RunEventType.SKILL_LOADED]
    assert len(loaded) == 1
    assert loaded[0].payload == {"skill_id": "chapter_audit", "version": 2}


def test_unknown_skill_raises_before_any_event(tmp_path: Path) -> None:
    store, runtime, run = _runtime(tmp_path)

    with pytest.raises(KeyError):
        runtime.load_for_run(run.id, "no_such_skill")

    events = store.replay(run.id)
    assert all(event.event_type is not RunEventType.SKILL_LOADED for event in events)


def test_unload_drops_cache_but_keeps_record(tmp_path: Path) -> None:
    _store, runtime, run = _runtime(tmp_path)
    runtime.load_for_run(run.id, "chapter_audit")

    runtime.unload(run.id)

    assert runtime.loaded_ids(run.id) == ("chapter_audit",)


def test_closed_run_rejects_loading(tmp_path: Path) -> None:
    store, runtime, run = _runtime(tmp_path)
    store.transition(run.id, RunStage.COMPLETED)

    from ai_novel_studio.harness.event_store import HarnessRunClosedError

    with pytest.raises(HarnessRunClosedError):
        runtime.load_for_run(run.id, "chapter_audit")
