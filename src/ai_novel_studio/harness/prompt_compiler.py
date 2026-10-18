from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum

from ai_novel_studio.harness.model_roles import ModelRole
from ai_novel_studio.infrastructure.llm.schemas import LLMMessage


class ComponentStability(StrEnum):
    """Stability tier of a prompt component (design v0.3 §15)."""

    GLOBAL = "GLOBAL"
    PROJECT = "PROJECT"
    RUN = "RUN"
    TURN = "TURN"


class ComponentKind(StrEnum):
    """Typed prompt component kinds (design v0.3 §15, §15.1)."""

    HARNESS_SYSTEM = "HARNESS_SYSTEM"
    CORE_TOOL_DEFINITIONS = "CORE_TOOL_DEFINITIONS"
    AGENT_EXAMPLES = "AGENT_EXAMPLES"
    PROJECT_CONSTITUTION = "PROJECT_CONSTITUTION"
    PROJECT_POLICY = "PROJECT_POLICY"
    PROJECT_PERSONA = "PROJECT_PERSONA"
    TASK_BLOCK = "TASK_BLOCK"
    SKILL_INSTRUCTIONS = "SKILL_INSTRUCTIONS"
    RUN_TOOL_SCHEMAS = "RUN_TOOL_SCHEMAS"
    OUTPUT_SCHEMA = "OUTPUT_SCHEMA"
    CONVERSATION_SUMMARY = "CONVERSATION_SUMMARY"
    RECENT_CONVERSATION = "RECENT_CONVERSATION"
    CONTEXT_PROJECTION = "CONTEXT_PROJECTION"
    STATE_CAPSULE = "STATE_CAPSULE"
    TOOL_RESULTS = "TOOL_RESULTS"
    CURRENT_INPUT = "CURRENT_INPUT"


class CacheStatus(StrEnum):
    """Accuracy of provider cache statistics (design v0.3 §15.2)."""

    ACCURATE = "ACCURATE"
    ESTIMATED = "ESTIMATED"
    UNKNOWN = "UNKNOWN"


_STABILITY_RANK: dict[ComponentStability, int] = {
    ComponentStability.GLOBAL: 0,
    ComponentStability.PROJECT: 1,
    ComponentStability.RUN: 2,
    ComponentStability.TURN: 3,
}

# These kinds hold run-live or author-live content and must never enter a
# stable prefix (contract §5.2).
_TURN_ONLY_KINDS = frozenset(
    {
        ComponentKind.CONVERSATION_SUMMARY,
        ComponentKind.RECENT_CONVERSATION,
        ComponentKind.CONTEXT_PROJECTION,
        ComponentKind.STATE_CAPSULE,
        ComponentKind.TOOL_RESULTS,
        ComponentKind.CURRENT_INPUT,
    }
)

_VALID_ROLES = frozenset({"system", "user", "assistant"})
_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _required(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} cannot be empty")
    return normalized


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized if normalized else None


def _optional_non_negative(value: int | None, field: str) -> int | None:
    if value is not None and value < 0:
        raise ValueError(f"{field} cannot be negative")
    return value


def _hash_field(value: str, field: str) -> str:
    if not _SHA256_HEX.match(value):
        raise ValueError(f"{field} must be a 64-character sha256 hex digest")
    return value


@dataclass(frozen=True, slots=True)
class PromptComponent:
    """One immutable prompt fragment with cache metadata (design v0.3 §15.1).

    Same revision and content always yield the same content_hash; a hash
    difference for identical content is an implementation error.
    """

    id: str
    kind: ComponentKind
    role: str
    stability: ComponentStability
    revision: int
    content: str
    ordering_priority: int = 100
    cache_eligible: bool = True
    sensitive: bool = False
    content_hash: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _required(self.id, "id"))
        if not isinstance(self.kind, ComponentKind):
            raise ValueError("kind must be a ComponentKind")
        if not isinstance(self.stability, ComponentStability):
            raise ValueError("stability must be a ComponentStability")
        if self.role not in _VALID_ROLES:
            raise ValueError("component role must be system, user or assistant")
        if self.revision < 0:
            raise ValueError("component revision cannot be negative")
        if self.kind in _TURN_ONLY_KINDS and self.stability is not ComponentStability.TURN:
            raise ValueError(f"{self.kind.value} components must have TURN stability")
        object.__setattr__(self, "content_hash", f"sha256:{_sha256(self.content)}")


@dataclass(frozen=True, slots=True)
class CachePlan:
    """Deterministic provider-agnostic cache fingerprint (design v0.3 §15.1)."""

    provider: str
    global_prefix_hash: str
    project_prefix_hash: str
    run_prefix_hash: str
    explicit_breakpoints: tuple[str, ...]
    cache_key: str | None
    cache_retention: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider", _required(self.provider, "provider"))
        for field in (
            "global_prefix_hash",
            "project_prefix_hash",
            "run_prefix_hash",
        ):
            object.__setattr__(self, field, _hash_field(getattr(self, field), field))
        object.__setattr__(
            self, "cache_retention", _required(self.cache_retention, "cache_retention")
        )


@dataclass(frozen=True, slots=True)
class ModelRequestManifest:
    """Local record of what a model request actually contained (design §15.2)."""

    request_id: str
    run_id: str
    step_id: str
    role: ModelRole
    provider_id: str
    model_id: str
    prompt_revision: str
    project_constitution_revision: int | None
    project_policy_revision: int | None
    writing_profile_revision: int | None
    toolset_revision: int | None
    skill_revisions: tuple[str, ...]
    editor_snapshot_revision: int | None
    context_manifest_id: str | None
    conversation_summary_revision: int | None
    global_prefix_hash: str
    project_prefix_hash: str
    run_prefix_hash: str
    source_artifacts: tuple[str, ...]
    input_token_estimate: int | None
    cached_input_tokens: int | None
    cache_status: CacheStatus

    def __post_init__(self) -> None:
        for field in ("request_id", "run_id", "step_id", "prompt_revision"):
            object.__setattr__(self, field, _required(getattr(self, field), field))
        object.__setattr__(self, "provider_id", _required(self.provider_id, "provider_id"))
        object.__setattr__(self, "model_id", _required(self.model_id, "model_id"))
        if not isinstance(self.role, ModelRole):
            raise ValueError("role must be a ModelRole")
        if not isinstance(self.cache_status, CacheStatus):
            raise ValueError("cache_status must be a CacheStatus")
        for field in (
            "project_constitution_revision",
            "project_policy_revision",
            "writing_profile_revision",
            "toolset_revision",
            "editor_snapshot_revision",
            "conversation_summary_revision",
            "input_token_estimate",
            "cached_input_tokens",
        ):
            object.__setattr__(
                self, field, _optional_non_negative(getattr(self, field), field)
            )
        object.__setattr__(
            self, "context_manifest_id", _optional_text(self.context_manifest_id)
        )
        for field in ("global_prefix_hash", "project_prefix_hash", "run_prefix_hash"):
            object.__setattr__(self, field, _hash_field(getattr(self, field), field))


@dataclass(frozen=True, slots=True)
class PromptAssembly:
    """Deterministic physical request produced by the compiler."""

    messages: tuple[LLMMessage, ...]
    cache_plan: CachePlan


class PromptCompiler:
    """Deterministic physical request assembly (design v0.3 §15, contract §5.2).

    Logical context is never concatenated ad hoc: the compiler orders
    components by (stability tier, ordering_priority, id), always places
    CURRENT_INPUT last, and fingerprints only cache-eligible GLOBAL/PROJECT/RUN
    content, so capsules, tool results and author input never pollute the
    stable prefix.
    """

    def __init__(self, components: tuple[PromptComponent, ...] = ()) -> None:
        identifiers = [component.id for component in components]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("component ids must be unique")
        self._components = components

    def compile(self, *, provider: str = "generic") -> PromptAssembly:
        ordered = self._ordered()
        messages = tuple(
            LLMMessage(component.role, component.content) for component in ordered
        )
        return PromptAssembly(
            messages=messages, cache_plan=self._cache_plan(ordered, provider)
        )

    @staticmethod
    def _ordered_components(
        components: tuple[PromptComponent, ...],
    ) -> tuple[PromptComponent, ...]:
        def sort_key(component: PromptComponent) -> tuple[int, int, int, str]:
            last = 1 if component.kind is ComponentKind.CURRENT_INPUT else 0
            return (
                _STABILITY_RANK[component.stability],
                last,
                component.ordering_priority,
                component.id,
            )

        return tuple(sorted(components, key=sort_key))

    def _ordered(self) -> tuple[PromptComponent, ...]:
        return self._ordered_components(self._components)

    @staticmethod
    def _prefix_hash(components: tuple[PromptComponent, ...]) -> str:
        payload = "\n".join(
            f"{component.kind.value}\n{component.role}\n{component.revision}\n"
            f"{component.content}"
            for component in components
        )
        return _sha256(payload)

    @staticmethod
    def _eligible(
        components: tuple[PromptComponent, ...], stability: ComponentStability
    ) -> tuple[PromptComponent, ...]:
        return tuple(
            component
            for component in components
            if component.stability is stability and component.cache_eligible
        )

    def _cache_plan(
        self, ordered: tuple[PromptComponent, ...], provider: str
    ) -> CachePlan:
        global_prefix = self._eligible(ordered, ComponentStability.GLOBAL)
        project_prefix = global_prefix + self._eligible(
            ordered, ComponentStability.PROJECT
        )
        run_prefix = project_prefix + self._eligible(ordered, ComponentStability.RUN)
        run_prefix_hash = self._prefix_hash(run_prefix)
        return CachePlan(
            provider=provider,
            global_prefix_hash=self._prefix_hash(global_prefix),
            project_prefix_hash=self._prefix_hash(project_prefix),
            run_prefix_hash=run_prefix_hash,
            explicit_breakpoints=(),
            cache_key=run_prefix_hash,
            cache_retention="provider_default",
        )
