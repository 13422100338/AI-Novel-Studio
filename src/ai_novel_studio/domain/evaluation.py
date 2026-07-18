from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

MAX_BASELINE_CANDIDATES = 100
MAX_BASELINE_TOKEN_COST = 4_096
MAX_BASELINE_QUERY_LENGTH = 20_000


class BaselineProfile(StrEnum):
    QUICK = "QUICK"
    NORMAL = "NORMAL"


class BaselineRelevance(StrEnum):
    RELEVANT = "RELEVANT"
    IRRELEVANT = "IRRELEVANT"
    FORBIDDEN = "FORBIDDEN"


def _required(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} cannot be empty")
    return normalized


@dataclass(frozen=True, slots=True)
class BaselineEligibility:
    project_scope_matches: bool = True
    revision_current: bool = True
    time_visible: bool = True
    view_allowed: bool = True
    authority_allowed: bool = True
    stale: bool = False
    source_changed: bool = False
    conflicted: bool = False

    def __post_init__(self) -> None:
        field_names = (
            "project_scope_matches",
            "revision_current",
            "time_visible",
            "view_allowed",
            "authority_allowed",
            "stale",
            "source_changed",
            "conflicted",
        )
        for name in field_names:
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"eligibility.{name} must be a boolean")


@dataclass(frozen=True, slots=True)
class BaselineCandidate:
    source_id: str
    category: str
    priority: int
    required: bool
    token_cost: int
    relevance: BaselineRelevance
    fallback_token_cost: int | None = None
    eligibility: BaselineEligibility = field(default_factory=BaselineEligibility)
    ranking_text: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _required(self.source_id, "source_id"))
        object.__setattr__(self, "category", _required(self.category, "category"))
        if self.priority < 0:
            raise ValueError("priority cannot be negative")
        if self.token_cost <= 0:
            raise ValueError("token_cost must be greater than zero")
        if self.token_cost > MAX_BASELINE_TOKEN_COST:
            raise ValueError(
                f"token_cost cannot exceed {MAX_BASELINE_TOKEN_COST} synthetic Tokens"
            )
        if self.fallback_token_cost is not None and self.fallback_token_cost <= 0:
            raise ValueError("fallback_token_cost must be greater than zero")
        if (
            self.fallback_token_cost is not None
            and self.fallback_token_cost > MAX_BASELINE_TOKEN_COST
        ):
            raise ValueError(
                "fallback_token_cost cannot exceed "
                f"{MAX_BASELINE_TOKEN_COST} synthetic Tokens"
            )
        if self.required and self.fallback_token_cost is not None:
            raise ValueError("required candidates cannot define a fallback")
        if self.required and self.relevance == BaselineRelevance.FORBIDDEN:
            raise ValueError("forbidden candidates cannot be required")
        if not isinstance(self.ranking_text, str):
            raise ValueError("ranking_text must be a string")
        ranking_text = self.ranking_text.strip()
        if len(ranking_text) > self.token_cost * 4:
            raise ValueError("ranking_text cannot exceed synthetic candidate content")
        object.__setattr__(self, "ranking_text", ranking_text)


@dataclass(frozen=True, slots=True)
class ExpectedBaselineSelection:
    source_id: str
    used_fallback: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _required(self.source_id, "source_id"))


@dataclass(frozen=True, slots=True)
class ContextBaselineScenario:
    id: str
    profile: BaselineProfile
    task_type: str
    input_token_limit: int
    output_token_limit: int
    candidates: tuple[BaselineCandidate, ...]
    expected_selected: tuple[ExpectedBaselineSelection, ...]
    query_text: str | None = None
    deduplicate: bool = False
    minimum_category_coverage: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _required(self.id, "id"))
        object.__setattr__(self, "task_type", _required(self.task_type, "task_type"))
        if self.query_text is not None:
            if not isinstance(self.query_text, str):
                raise ValueError("query_text must be a string")
            query_text = self.query_text.strip()
            if not query_text:
                raise ValueError("query_text cannot be blank")
            if len(query_text) > MAX_BASELINE_QUERY_LENGTH:
                raise ValueError(
                    f"query_text cannot exceed {MAX_BASELINE_QUERY_LENGTH} characters"
                )
            object.__setattr__(self, "query_text", query_text)
        if not isinstance(self.deduplicate, bool):
            raise ValueError("deduplicate must be a boolean")
        normalized_coverage = tuple(
            _required(category, "minimum_category_coverage")
            for category in self.minimum_category_coverage
        )
        if len(normalized_coverage) != len(set(normalized_coverage)):
            raise ValueError("minimum_category_coverage cannot contain duplicates")
        object.__setattr__(
            self,
            "minimum_category_coverage",
            normalized_coverage,
        )
        if self.input_token_limit <= 0 or self.output_token_limit <= 0:
            raise ValueError("input and output Token limits must be greater than zero")
        if not self.candidates:
            raise ValueError("baseline scenario must contain candidates")
        if len(self.candidates) > MAX_BASELINE_CANDIDATES:
            raise ValueError(
                f"baseline scenario cannot exceed {MAX_BASELINE_CANDIDATES} candidates"
            )
        source_ids = tuple(candidate.source_id for candidate in self.candidates)
        if len(source_ids) != len(set(source_ids)):
            raise ValueError(f"duplicate candidate source_id in scenario {self.id}")
        expected_ids = tuple(item.source_id for item in self.expected_selected)
        if len(expected_ids) != len(set(expected_ids)):
            raise ValueError(f"duplicate expected source_id in scenario {self.id}")
        unknown = set(expected_ids) - set(source_ids)
        if unknown:
            raise ValueError(
                f"unknown expected source IDs in scenario {self.id}: {sorted(unknown)}"
            )


@dataclass(frozen=True, slots=True)
class ContextBaselineSuite:
    version: int
    scenarios: tuple[ContextBaselineScenario, ...]

    def __post_init__(self) -> None:
        if self.version not in {1, 2, 3, 4, 5, 6}:
            raise ValueError(f"unsupported baseline suite version: {self.version}")
        if not 10 <= len(self.scenarios) <= 20:
            raise ValueError("baseline must contain 10 to 20 scenarios")
        scenario_ids = tuple(scenario.id for scenario in self.scenarios)
        if len(scenario_ids) != len(set(scenario_ids)):
            raise ValueError("baseline scenario IDs must be unique")
        profiles = {scenario.profile for scenario in self.scenarios}
        if profiles != {BaselineProfile.QUICK, BaselineProfile.NORMAL}:
            raise ValueError("baseline must cover both QUICK and NORMAL profiles")


@dataclass(frozen=True, slots=True)
class ContextBaselineObservation:
    scenario_id: str
    profile: BaselineProfile
    selected: tuple[ExpectedBaselineSelection, ...]
    omitted_source_ids: tuple[str, ...]
    expected_selected: tuple[ExpectedBaselineSelection, ...]
    relevant_source_count: int
    selected_relevant_count: int
    selected_irrelevant_count: int
    selected_forbidden_count: int
    estimated_input_tokens: int
    input_token_limit: int
    compile_latency_ms: int
    error_type: str | None

    @property
    def matches_baseline(self) -> bool:
        return self.error_type is None and self.selected == self.expected_selected

    @property
    def recall(self) -> float:
        if self.relevant_source_count == 0:
            return 1.0
        return self.selected_relevant_count / self.relevant_source_count

    @property
    def precision(self) -> float:
        if not self.selected:
            return 1.0 if self.relevant_source_count == 0 else 0.0
        return self.selected_relevant_count / len(self.selected)

    @property
    def token_utilization(self) -> float:
        return self.estimated_input_tokens / self.input_token_limit


@dataclass(frozen=True, slots=True)
class BaselineProfileSummary:
    profile: BaselineProfile
    scenario_count: int
    average_recall: float
    average_precision: float
    forbidden_selection_count: int
    average_token_utilization: float


@dataclass(frozen=True, slots=True)
class ContextBaselineReport:
    suite_version: int
    observations: tuple[ContextBaselineObservation, ...]

    @property
    def total_scenarios(self) -> int:
        return len(self.observations)

    @property
    def matched_scenarios(self) -> int:
        return sum(item.matches_baseline for item in self.observations)

    @property
    def unexpected_error_count(self) -> int:
        return sum(item.error_type is not None for item in self.observations)

    @property
    def forbidden_selection_count(self) -> int:
        return sum(item.selected_forbidden_count for item in self.observations)

    @property
    def average_recall(self) -> float:
        return self._average(tuple(item.recall for item in self.observations))

    @property
    def average_precision(self) -> float:
        return self._average(tuple(item.precision for item in self.observations))

    @property
    def metric_coverage(self) -> dict[str, bool]:
        return {
            "context_selection": True,
            "estimated_input_tokens": True,
            "context_compile_latency": True,
            "model_generation": False,
            "actual_model_usage": False,
            "human_revision_cost": False,
        }

    def profile_summary(self, profile: BaselineProfile) -> BaselineProfileSummary:
        observations = tuple(item for item in self.observations if item.profile == profile)
        return BaselineProfileSummary(
            profile=profile,
            scenario_count=len(observations),
            average_recall=self._average(tuple(item.recall for item in observations)),
            average_precision=self._average(tuple(item.precision for item in observations)),
            forbidden_selection_count=sum(
                item.selected_forbidden_count for item in observations
            ),
            average_token_utilization=self._average(
                tuple(item.token_utilization for item in observations)
            ),
        )

    def to_dict(self) -> dict[str, object]:
        profiles = (BaselineProfile.QUICK, BaselineProfile.NORMAL)
        return {
            "suite_version": self.suite_version,
            "total_scenarios": self.total_scenarios,
            "matched_scenarios": self.matched_scenarios,
            "unexpected_error_count": self.unexpected_error_count,
            "forbidden_selection_count": self.forbidden_selection_count,
            "average_recall": self.average_recall,
            "average_precision": self.average_precision,
            "metric_coverage": self.metric_coverage,
            "profiles": {
                profile.value: self._profile_to_dict(self.profile_summary(profile))
                for profile in profiles
            },
            "observations": [self._observation_to_dict(item) for item in self.observations],
        }

    @staticmethod
    def _average(values: tuple[float, ...]) -> float:
        return sum(values) / len(values) if values else 0.0

    @staticmethod
    def _profile_to_dict(summary: BaselineProfileSummary) -> dict[str, object]:
        return {
            "scenario_count": summary.scenario_count,
            "average_recall": summary.average_recall,
            "average_precision": summary.average_precision,
            "forbidden_selection_count": summary.forbidden_selection_count,
            "average_token_utilization": summary.average_token_utilization,
        }

    @staticmethod
    def _observation_to_dict(item: ContextBaselineObservation) -> dict[str, object]:
        return {
            "scenario_id": item.scenario_id,
            "profile": item.profile.value,
            "matches_baseline": item.matches_baseline,
            "selected": [
                {"source_id": selected.source_id, "used_fallback": selected.used_fallback}
                for selected in item.selected
            ],
            "omitted_source_ids": list(item.omitted_source_ids),
            "recall": item.recall,
            "precision": item.precision,
            "selected_forbidden_count": item.selected_forbidden_count,
            "estimated_input_tokens": item.estimated_input_tokens,
            "input_token_limit": item.input_token_limit,
            "token_utilization": item.token_utilization,
            "compile_latency_ms": item.compile_latency_ms,
            "error_type": item.error_type,
        }
