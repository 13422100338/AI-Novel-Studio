from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from time import perf_counter
from typing import cast

from ai_novel_studio.core.context.context_builder import (
    ContextBlock,
    ContextBuilder,
    ContextBuildRequest,
)
from ai_novel_studio.core.context.token_budget import TokenBudget
from ai_novel_studio.domain.evaluation import (
    BaselineCandidate,
    BaselineProfile,
    BaselineRelevance,
    ContextBaselineObservation,
    ContextBaselineReport,
    ContextBaselineScenario,
    ContextBaselineSuite,
    ExpectedBaselineSelection,
)

MAX_BASELINE_BYTES = 1_000_000


def load_context_baseline_suite(path: Path) -> ContextBaselineSuite:
    if not path.is_file():
        raise ValueError(f"baseline suite does not exist: {path}")
    if path.stat().st_size > MAX_BASELINE_BYTES:
        raise ValueError("baseline suite exceeds the 1 MB safety limit")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid baseline suite: {error}") from error
    root = _mapping(payload, "baseline suite")
    scenarios = tuple(
        _scenario(raw) for raw in _sequence(root.get("scenarios"), "scenarios")
    )
    return ContextBaselineSuite(
        version=_integer(root.get("version"), "version"),
        scenarios=scenarios,
    )


def run_context_baseline(
    suite: ContextBaselineSuite,
    builder: ContextBuilder | None = None,
) -> ContextBaselineReport:
    compiler = builder or ContextBuilder()
    observations = tuple(_run_scenario(scenario, compiler) for scenario in suite.scenarios)
    return ContextBaselineReport(suite.version, observations)


def _run_scenario(
    scenario: ContextBaselineScenario,
    builder: ContextBuilder,
) -> ContextBaselineObservation:
    started = perf_counter()
    selected: tuple[ExpectedBaselineSelection, ...] = ()
    omitted_source_ids: tuple[str, ...] = ()
    estimated_input_tokens = 0
    error_type: str | None = None
    try:
        built = builder.build(
            ContextBuildRequest(
                chapter_id=f"baseline:{scenario.id}",
                run_id=None,
                budget=TokenBudget(
                    scenario.input_token_limit + scenario.output_token_limit,
                    scenario.output_token_limit,
                    0,
                ),
                blocks=tuple(_context_block(item) for item in scenario.candidates),
            )
        )
        selected = tuple(
            ExpectedBaselineSelection(item.source_id, item.used_fallback)
            for item in built.manifest.selected
        )
        omitted_source_ids = tuple(item.source_id for item in built.manifest.omitted)
        estimated_input_tokens = built.manifest.estimated_input_tokens
    except Exception as error:  # The report records unexpected compiler failures.
        error_type = type(error).__name__
    compile_latency_ms = max(0, round((perf_counter() - started) * 1000))

    selected_ids = {item.source_id for item in selected}
    relevance = {item.source_id: item.relevance for item in scenario.candidates}
    return ContextBaselineObservation(
        scenario_id=scenario.id,
        profile=scenario.profile,
        selected=selected,
        omitted_source_ids=omitted_source_ids,
        expected_selected=scenario.expected_selected,
        relevant_source_count=sum(
            item.relevance == BaselineRelevance.RELEVANT for item in scenario.candidates
        ),
        selected_relevant_count=sum(
            relevance[source_id] == BaselineRelevance.RELEVANT
            for source_id in selected_ids
        ),
        selected_irrelevant_count=sum(
            relevance[source_id] == BaselineRelevance.IRRELEVANT
            for source_id in selected_ids
        ),
        selected_forbidden_count=sum(
            relevance[source_id] == BaselineRelevance.FORBIDDEN
            for source_id in selected_ids
        ),
        estimated_input_tokens=estimated_input_tokens,
        input_token_limit=scenario.input_token_limit,
        compile_latency_ms=compile_latency_ms,
        error_type=error_type,
    )


def _context_block(candidate: BaselineCandidate) -> ContextBlock:
    content = "x" * candidate.token_cost * 4
    fallback = (
        "f" * candidate.fallback_token_cost * 4
        if candidate.fallback_token_cost is not None
        else None
    )
    return ContextBlock(
        id=candidate.source_id,
        category=candidate.category,
        content=content,
        priority=candidate.priority,
        required=candidate.required,
        source_type="BASELINE",
        source_id=candidate.source_id,
        source_chapter_id=None,
        source_revision=0,
        source_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        rationale=f"Phase 0 {candidate.relevance.value.lower()} candidate",
        fallback_content=fallback,
    )


def _scenario(value: object) -> ContextBaselineScenario:
    data = _mapping(value, "scenario")
    candidates = tuple(
        _candidate(item) for item in _sequence(data.get("candidates"), "candidates")
    )
    expected = tuple(
        _expected(item)
        for item in _sequence(data.get("expected_selected"), "expected_selected")
    )
    try:
        profile = BaselineProfile(_string(data.get("profile"), "profile"))
    except ValueError as error:
        raise ValueError(f"invalid baseline profile: {data.get('profile')}") from error
    return ContextBaselineScenario(
        id=_string(data.get("id"), "id"),
        profile=profile,
        task_type=_string(data.get("task_type"), "task_type"),
        input_token_limit=_integer(data.get("input_token_limit"), "input_token_limit"),
        output_token_limit=_integer(
            data.get("output_token_limit"), "output_token_limit"
        ),
        candidates=candidates,
        expected_selected=expected,
    )


def _candidate(value: object) -> BaselineCandidate:
    data = _mapping(value, "candidate")
    try:
        relevance = BaselineRelevance(
            _string(data.get("relevance"), "candidate.relevance")
        )
    except ValueError as error:
        raise ValueError(f"invalid candidate relevance: {data.get('relevance')}") from error
    fallback = data.get("fallback_token_cost")
    return BaselineCandidate(
        source_id=_string(data.get("source_id"), "candidate.source_id"),
        category=_string(data.get("category"), "candidate.category"),
        priority=_integer(data.get("priority"), "candidate.priority"),
        required=_boolean(data.get("required"), "candidate.required"),
        token_cost=_integer(data.get("token_cost"), "candidate.token_cost"),
        fallback_token_cost=(
            None
            if fallback is None
            else _integer(fallback, "candidate.fallback_token_cost")
        ),
        relevance=relevance,
    )


def _expected(value: object) -> ExpectedBaselineSelection:
    data = _mapping(value, "expected selection")
    return ExpectedBaselineSelection(
        source_id=_string(data.get("source_id"), "expected.source_id"),
        used_fallback=_boolean(data.get("used_fallback"), "expected.used_fallback"),
    )


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{field} must be an object with string keys")
    return cast(dict[str, object], value)


def _sequence(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    return cast(list[object], value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    return value


def _boolean(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value
