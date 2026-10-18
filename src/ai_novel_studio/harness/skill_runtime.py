from __future__ import annotations

from ai_novel_studio.harness.event_store import HarnessEventStore
from ai_novel_studio.harness.run_state import RunEventType
from ai_novel_studio.harness.skill_catalog import Skill, SkillCatalog


class SkillRuntimeService:
    """On-demand skill loading scoped to one run (design v0.3 §32).

    Loading appends the SKILL_LOADED event (the durable record) and keeps
    the full skill body in memory for the run; unloading drops the body and
    leaves only the record. After a restart the event log is authoritative,
    so loaded_ids never depends on process memory.
    """

    def __init__(self, store: HarnessEventStore, catalog: SkillCatalog) -> None:
        self._store = store
        self._catalog = catalog
        self._loaded: dict[str, dict[str, Skill]] = {}

    def load_for_run(
        self, run_id: str, skill_id: str, version: int | None = None
    ) -> Skill:
        skill = self._catalog.load(skill_id, version)
        self._store.append(
            run_id,
            RunEventType.SKILL_LOADED,
            {"skill_id": skill.id, "version": skill.version},
        )
        self._loaded.setdefault(run_id, {})[skill.id] = skill
        return skill

    def loaded_ids(self, run_id: str) -> tuple[str, ...]:
        seen: list[str] = []
        for event in self._store.replay(run_id):
            if event.event_type is not RunEventType.SKILL_LOADED:
                continue
            value = event.payload.get("skill_id")
            if isinstance(value, str) and value.strip() and value not in seen:
                seen.append(value)
        return tuple(seen)

    def unload(self, run_id: str) -> None:
        self._loaded.pop(run_id, None)
