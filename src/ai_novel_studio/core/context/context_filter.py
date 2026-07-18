from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ContextExclusionReason(StrEnum):
    PROJECT_SCOPE = "PROJECT_SCOPE"
    REVISION_INVALID = "REVISION_INVALID"
    TIME_BOUNDARY = "TIME_BOUNDARY"
    VIEW_BOUNDARY = "VIEW_BOUNDARY"
    STALE = "STALE"
    SOURCE_CHANGED = "SOURCE_CHANGED"
    CONFLICTED = "CONFLICTED"
    AUTHORITY_REJECTED = "AUTHORITY_REJECTED"


@dataclass(frozen=True, slots=True)
class ContextEligibility:
    project_scope_matches: bool = True
    revision_current: bool = True
    time_visible: bool = True
    view_allowed: bool = True
    authority_allowed: bool = True
    stale: bool = False
    source_changed: bool = False
    conflicted: bool = False

    def exclusion_reason(self) -> ContextExclusionReason | None:
        checks = (
            (not self.project_scope_matches, ContextExclusionReason.PROJECT_SCOPE),
            (not self.revision_current, ContextExclusionReason.REVISION_INVALID),
            (not self.time_visible, ContextExclusionReason.TIME_BOUNDARY),
            (not self.view_allowed, ContextExclusionReason.VIEW_BOUNDARY),
            (self.stale, ContextExclusionReason.STALE),
            (self.source_changed, ContextExclusionReason.SOURCE_CHANGED),
            (self.conflicted, ContextExclusionReason.CONFLICTED),
            (not self.authority_allowed, ContextExclusionReason.AUTHORITY_REJECTED),
        )
        return next((reason for excluded, reason in checks if excluded), None)
