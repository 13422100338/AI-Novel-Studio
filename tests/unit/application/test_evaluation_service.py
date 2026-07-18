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


def test_backend_baseline_command_emits_machine_readable_report(capsys) -> None:  # type: ignore[no-untyped-def]
    exit_code = main([str(FIXTURE)])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["suite_version"] == 1
    assert payload["total_scenarios"] == 10
    assert payload["matched_scenarios"] == 10
    assert payload["metric_coverage"]["human_revision_cost"] is False
