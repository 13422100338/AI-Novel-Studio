from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ai_novel_studio.domain.generation import AuditPolicy, GenerationProfile
from ai_novel_studio.domain.identifiers import validate_id


class SnapshotState(StrEnum):
    """Frozen editor snapshot classification (design v0.3 §46)."""

    CURRENT = "CURRENT"
    STALE_BUT_REBASABLE = "STALE_BUT_REBASABLE"
    STALE_CONFLICTED = "STALE_CONFLICTED"


class MergeOutcome(StrEnum):
    """Deterministic three-way merge classification (design v0.3 §47)."""

    CLEAN_APPLY = "CLEAN_APPLY"
    NO_CHANGE = "NO_CHANGE"
    NEEDS_REVIEW = "NEEDS_REVIEW"


def _required(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"generation package {field} cannot be empty")
    return normalized


def _normalized_items(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))


@dataclass(frozen=True, slots=True)
class EditorSnapshot:
    """Frozen working-draft snapshot taken before model work (design §46)."""

    chapter_id: str
    content: str
    revision: int
    content_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "chapter_id", validate_id(self.chapter_id))
        if self.revision < 0:
            raise ValueError("editor snapshot revision cannot be negative")
        if not self.content_hash.strip():
            raise ValueError("editor snapshot content hash cannot be empty")


def classify_snapshot(frozen: EditorSnapshot, current: EditorSnapshot) -> SnapshotState:
    if (
        frozen.revision == current.revision
        and frozen.content_hash == current.content_hash
    ):
        return SnapshotState.CURRENT
    if frozen.revision == current.revision:
        return SnapshotState.STALE_CONFLICTED
    return SnapshotState.STALE_BUT_REBASABLE


def classify_three_way(
    base: EditorSnapshot, ours: EditorSnapshot, theirs: EditorSnapshot
) -> MergeOutcome:
    """Base/Ours/Theirs merge classification (design §47, deterministic subset)."""
    if ours.content == base.content:
        return MergeOutcome.CLEAN_APPLY
    if theirs.content == base.content:
        return MergeOutcome.NO_CHANGE
    return MergeOutcome.NEEDS_REVIEW


@dataclass(frozen=True, slots=True)
class GenerationPackage:
    """Task-scoped generation package (design v0.3 §41, harness-owned)."""

    chapter_id: str
    editor_snapshot: EditorSnapshot
    formal_revision: int
    generation_profile: GenerationProfile
    audit_policy: AuditPolicy
    goal: str
    must_happen: tuple[str, ...] = ()
    forbidden: tuple[str, ...] = ()
    scene_plan: tuple[str, ...] = ()
    pov: str | None = None
    story_time: str | None = None
    narrative_sequence_boundary: int | None = None
    involved_subjects: tuple[str, ...] = ()
    character_states: tuple[str, ...] = ()
    knowledge_known: tuple[str, ...] = ()
    knowledge_unaware: tuple[str, ...] = ()
    knowledge_unknown: tuple[str, ...] = ()
    non_revealable_constraints: tuple[str, ...] = ()
    relationship_boundaries: tuple[str, ...] = ()
    project_constitution_revision: int | None = None
    project_constitution_projection_id: str | None = None
    writing_profile_revision: int | None = None
    style_projection_id: str | None = None
    references: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = ()
    context_manifest_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "chapter_id", validate_id(self.chapter_id))
        if not isinstance(self.editor_snapshot, EditorSnapshot):
            raise ValueError("generation package editor snapshot is invalid")
        if self.editor_snapshot.chapter_id != self.chapter_id:
            raise ValueError("generation package snapshot chapter mismatch")
        if self.formal_revision < 0:
            raise ValueError("generation package formal revision is invalid")
        if not isinstance(self.generation_profile, GenerationProfile):
            raise ValueError("generation package profile is invalid")
        if not isinstance(self.audit_policy, AuditPolicy):
            raise ValueError("generation package audit policy is invalid")
        object.__setattr__(self, "goal", _required(self.goal, "goal"))
        for field in (
            "must_happen",
            "forbidden",
            "scene_plan",
            "involved_subjects",
            "character_states",
            "knowledge_known",
            "knowledge_unaware",
            "knowledge_unknown",
            "non_revealable_constraints",
            "relationship_boundaries",
            "references",
            "assumptions",
            "unresolved",
        ):
            object.__setattr__(self, field, _normalized_items(getattr(self, field)))
        for field in (
            "project_constitution_revision",
            "writing_profile_revision",
            "narrative_sequence_boundary",
        ):
            value = getattr(self, field)
            if value is not None and value < 0:
                raise ValueError(f"generation package {field} is invalid")
        if self.pov is not None and not self.pov.strip():
            object.__setattr__(self, "pov", None)
        if self.story_time is not None and not self.story_time.strip():
            object.__setattr__(self, "story_time", None)

    @property
    def draft_blocked_reasons(self) -> tuple[str, ...]:
        """Deterministic reasons the chapter draft model must not run (§41)."""
        reasons: list[str] = []
        if self.unresolved:
            reasons.append("unresolved plot decisions block the draft model")
        if not self.goal:
            reasons.append("generation goal is missing")
        return tuple(reasons)

    @property
    def ready_for_draft_model(self) -> bool:
        return not self.draft_blocked_reasons
