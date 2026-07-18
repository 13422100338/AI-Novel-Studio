from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_novel_studio.application.evaluation_service import (
    load_context_baseline_suite,
    run_context_baseline,
)
from ai_novel_studio.domain.evaluation import BaselineProfile
from scripts.run_backend_baseline import main

FIXTURE = Path(__file__).parents[2] / "fixtures" / "backend_baseline_v1.json"
PHASE_3_FIXTURE = Path(__file__).parents[2] / "fixtures" / "backend_baseline_v2.json"
RANKING_FIXTURE = Path(__file__).parents[2] / "fixtures" / "backend_baseline_v3.json"
DEDUPLICATION_FIXTURE = (
    Path(__file__).parents[2] / "fixtures" / "backend_baseline_v4.json"
)
CONFLICT_FIXTURE = Path(__file__).parents[2] / "fixtures" / "backend_baseline_v5.json"


def test_phase_0_context_baseline_runs_ten_fixed_quick_and_normal_tasks() -> None:
    suite = load_context_baseline_suite(FIXTURE)

    report = run_context_baseline(suite)

    assert len(suite.scenarios) == 10
    assert {scenario.profile for scenario in suite.scenarios} == {
        BaselineProfile.QUICK,
        BaselineProfile.NORMAL,
    }
    assert report.total_scenarios == 10
    assert report.matched_scenarios == 10
    assert report.unexpected_error_count == 0
    assert report.forbidden_selection_count == 2
    assert report.average_recall < 1
    assert report.average_precision < 1
    assert all(observation.compile_latency_ms >= 0 for observation in report.observations)
    assert all(observation.estimated_input_tokens > 0 for observation in report.observations)
    assert report.profile_summary(BaselineProfile.QUICK).scenario_count == 5
    assert report.profile_summary(BaselineProfile.NORMAL).scenario_count == 5
    assert report.metric_coverage["context_selection"] is True
    assert report.metric_coverage["model_generation"] is False
    assert report.metric_coverage["human_revision_cost"] is False


def test_phase_3_hard_filters_remove_forbidden_candidates_without_reducing_recall() -> None:
    phase_0 = run_context_baseline(load_context_baseline_suite(FIXTURE))
    phase_3 = run_context_baseline(load_context_baseline_suite(PHASE_3_FIXTURE))

    assert phase_3.suite_version == 2
    assert phase_3.total_scenarios == 10
    assert phase_3.matched_scenarios == 10
    assert phase_3.unexpected_error_count == 0
    assert phase_0.forbidden_selection_count == 2
    assert phase_3.forbidden_selection_count == 0
    assert phase_3.average_recall == phase_0.average_recall
    assert phase_3.average_precision > phase_0.average_precision


def test_phase_3_task_ranking_improves_recall_without_reintroducing_forbidden_context() -> None:
    hard_filter = run_context_baseline(load_context_baseline_suite(PHASE_3_FIXTURE))
    ranked = run_context_baseline(load_context_baseline_suite(RANKING_FIXTURE))

    assert ranked.suite_version == 3
    assert ranked.matched_scenarios == 10
    assert ranked.unexpected_error_count == 0
    assert ranked.forbidden_selection_count == 0
    assert ranked.average_recall > hard_filter.average_recall
    assert ranked.average_precision > hard_filter.average_precision


def test_phase_3_deduplication_improves_precision_without_reducing_recall() -> None:
    ranked = run_context_baseline(load_context_baseline_suite(RANKING_FIXTURE))
    deduplicated = run_context_baseline(
        load_context_baseline_suite(DEDUPLICATION_FIXTURE)
    )

    assert deduplicated.suite_version == 4
    assert deduplicated.matched_scenarios == 10
    assert deduplicated.unexpected_error_count == 0
    assert deduplicated.forbidden_selection_count == 0
    assert deduplicated.average_recall == ranked.average_recall
    assert deduplicated.average_precision > ranked.average_precision


def test_phase_3_conflict_filter_reaches_full_precision_without_reducing_recall() -> None:
    deduplicated = run_context_baseline(
        load_context_baseline_suite(DEDUPLICATION_FIXTURE)
    )
    conflict_safe = run_context_baseline(load_context_baseline_suite(CONFLICT_FIXTURE))

    assert conflict_safe.suite_version == 5
    assert conflict_safe.matched_scenarios == 10
    assert conflict_safe.unexpected_error_count == 0
    assert conflict_safe.forbidden_selection_count == 0
    assert conflict_safe.average_recall == deduplicated.average_recall
    assert conflict_safe.average_precision == 1


def test_baseline_loader_rejects_suite_outside_the_phase_0_task_count(
    tmp_path: Path,
) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["scenarios"] = payload["scenarios"][:9]
    invalid = tmp_path / "too-small.json"
    invalid.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="10 to 20 scenarios"):
        load_context_baseline_suite(invalid)


def test_baseline_loader_requires_quick_and_normal_profiles(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for scenario in payload["scenarios"]:
        scenario["profile"] = "QUICK"
    invalid = tmp_path / "one-profile.json"
    invalid.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="QUICK and NORMAL"):
        load_context_baseline_suite(invalid)


def test_baseline_loader_rejects_unbounded_synthetic_token_cost(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["scenarios"][0]["candidates"][0]["token_cost"] = 1_000_000_000
    invalid = tmp_path / "unbounded-token-cost.json"
    invalid.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="token_cost cannot exceed"):
        load_context_baseline_suite(invalid)


@pytest.mark.parametrize(
    ("eligibility", "message"),
    [
        ({"time_visible": "false"}, "must be a boolean"),
        ({"untrusted_flag": True}, "unknown candidate eligibility fields"),
    ],
)
def test_baseline_loader_validates_hard_filter_metadata(
    tmp_path: Path, eligibility: dict[str, object], message: str
) -> None:
    payload = json.loads(PHASE_3_FIXTURE.read_text(encoding="utf-8"))
    payload["scenarios"][0]["candidates"][0]["eligibility"] = eligibility
    invalid = tmp_path / "invalid-eligibility.json"
    invalid.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_context_baseline_suite(invalid)


def test_baseline_loader_bounds_task_ranking_metadata(tmp_path: Path) -> None:
    oversized_query = json.loads(RANKING_FIXTURE.read_text(encoding="utf-8"))
    oversized_query["scenarios"][-1]["query_text"] = "x" * 20_001
    invalid_query = tmp_path / "invalid-ranking-query.json"
    invalid_query.write_text(json.dumps(oversized_query), encoding="utf-8")

    with pytest.raises(ValueError, match="query_text cannot exceed"):
        load_context_baseline_suite(invalid_query)

    oversized_candidate = json.loads(RANKING_FIXTURE.read_text(encoding="utf-8"))
    oversized_candidate["scenarios"][-1]["candidates"][-1]["ranking_text"] = (
        "x" * 41
    )
    invalid_candidate = tmp_path / "invalid-ranking-candidate.json"
    invalid_candidate.write_text(
        json.dumps(oversized_candidate),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="synthetic candidate content"):
        load_context_baseline_suite(invalid_candidate)

    invalid_deduplication = json.loads(
        DEDUPLICATION_FIXTURE.read_text(encoding="utf-8")
    )
    invalid_deduplication["scenarios"][2]["deduplicate"] = "true"
    invalid_deduplication_path = tmp_path / "invalid-deduplication.json"
    invalid_deduplication_path.write_text(
        json.dumps(invalid_deduplication),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="deduplicate must be a boolean"):
        load_context_baseline_suite(invalid_deduplication_path)


def test_backend_baseline_command_emits_machine_readable_report(capsys) -> None:  # type: ignore[no-untyped-def]
    exit_code = main([str(FIXTURE)])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["suite_version"] == 1
    assert payload["total_scenarios"] == 10
    assert payload["matched_scenarios"] == 10
    assert payload["metric_coverage"]["human_revision_cost"] is False
