from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.harness.model_roles import (
    ModelRole,
    ModelRoleBinding,
    UsageMeasurement,
)
from ai_novel_studio.infrastructure.llm.usage_tracker import UsageRecord, UsageTracker


@dataclass(frozen=True, slots=True)
class RoleUsage:
    """Per-role usage projection (design v0.3 §66)."""

    role: ModelRole
    call_count: int
    failed_call_count: int
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    reasoning_tokens: int
    cost: float | None
    measurement: UsageMeasurement


class HarnessUsageMeter:
    """Splits the shared UsageTracker into per-role figures.

    Agent and chapter-draft usage must be reported separately (design §66).
    The meter maps the tracker's per-purpose records back to logical roles
    through the run's frozen bindings and always labels measurement accuracy
    as ACCURATE / ESTIMATED / UNKNOWN.
    """

    def __init__(self, tracker: UsageTracker, bindings: tuple[ModelRoleBinding, ...]) -> None:
        self._tracker = tracker
        purposes = [binding.purpose for binding in bindings]
        if len(set(purposes)) != len(purposes):
            raise ValueError("bindings must be unique per purpose")
        self._role_by_purpose = {binding.purpose: binding.role for binding in bindings}

    def snapshot(self) -> tuple[RoleUsage, ...]:
        grouped: dict[ModelRole, list[UsageRecord]] = {
            role: [] for role in self._role_by_purpose.values()
        }
        for record in self._tracker.records:
            role = self._role_by_purpose.get(record.purpose)
            if role is not None:
                grouped[role].append(record)
        return tuple(
            self._project(role, grouped[role]) for role in ModelRole if role in grouped
        )

    @staticmethod
    def _project(role: ModelRole, records: list[UsageRecord]) -> RoleUsage:
        if not records:
            return RoleUsage(role, 0, 0, 0, 0, 0, 0, None, UsageMeasurement.UNKNOWN)
        known_costs = [record.cost for record in records if record.cost is not None]
        measurement = (
            UsageMeasurement.ACCURATE
            if all(not record.usage.estimated for record in records)
            else UsageMeasurement.ESTIMATED
        )
        return RoleUsage(
            role=role,
            call_count=len(records),
            failed_call_count=sum(record.status == "failed" for record in records),
            input_tokens=sum(record.usage.input_tokens or 0 for record in records),
            output_tokens=sum(record.usage.output_tokens or 0 for record in records),
            cached_input_tokens=sum(
                record.usage.cached_input_tokens or 0 for record in records
            ),
            reasoning_tokens=sum(record.usage.reasoning_tokens or 0 for record in records),
            cost=sum(known_costs) if len(known_costs) == len(records) else None,
            measurement=measurement,
        )
