from __future__ import annotations

from pathlib import Path

import pytest

from ai_novel_studio.harness.event_repository import HarnessEventRepository
from ai_novel_studio.harness.event_store import HarnessEventStore
from ai_novel_studio.harness.model_request_manifest_repository import (
    ModelRequestManifestRepository,
)
from ai_novel_studio.harness.model_roles import ModelRole
from ai_novel_studio.harness.prompt_compiler import CacheStatus, ModelRequestManifest
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository

_HASH = "a" * 64


def _repository(tmp_path: Path):
    project = ProjectRepository.create(tmp_path / "novel", "Request manifests")
    store = HarnessEventStore(HarnessEventRepository(project))
    run, _ = store.start_run(goal="记录清单")
    return ModelRequestManifestRepository(project), run


def _manifest(run_id: str, request_id: str = "req-1") -> ModelRequestManifest:
    return ModelRequestManifest(
        request_id=request_id,
        run_id=run_id,
        step_id="draft-1",
        role=ModelRole.CHAPTER_DRAFT,
        provider_id="provider-1",
        model_id="model-1",
        prompt_revision="prose-v1",
        project_constitution_revision=None,
        project_policy_revision=None,
        writing_profile_revision=3,
        toolset_revision=None,
        skill_revisions=("chapter_audit@2",),
        editor_snapshot_revision=0,
        context_manifest_id="manifest-1",
        conversation_summary_revision=None,
        global_prefix_hash=_HASH,
        project_prefix_hash=_HASH,
        run_prefix_hash=_HASH,
        source_artifacts=("sha256:" + "b" * 64,),
        input_token_estimate=1500,
        cached_input_tokens=None,
        cache_status=CacheStatus.ESTIMATED,
    )


def test_save_and_get_round_trips_manifest(tmp_path: Path) -> None:
    repository, run = _repository(tmp_path)
    manifest = _manifest(run.id)

    saved = repository.save(manifest)

    assert saved == manifest
    loaded = repository.get("req-1")
    assert loaded == manifest
    assert loaded.role is ModelRole.CHAPTER_DRAFT
    assert loaded.cache_status is CacheStatus.ESTIMATED
    assert loaded.skill_revisions == ("chapter_audit@2",)
    assert loaded.source_artifacts == ("sha256:" + "b" * 64,)


def test_list_and_latest_per_run(tmp_path: Path) -> None:
    repository, run = _repository(tmp_path)
    repository.save(_manifest(run.id, "req-1"))
    repository.save(_manifest(run.id, "req-2"))

    listed = repository.list_for_run(run.id)
    latest = repository.latest_for_run(run.id)

    assert [item.request_id for item in listed] == ["req-1", "req-2"]
    assert latest is not None
    assert latest.request_id == "req-2"
    assert repository.latest_for_run("no-such-run") is None


def test_unknown_manifest_raises(tmp_path: Path) -> None:
    repository, _run = _repository(tmp_path)

    with pytest.raises(KeyError):
        repository.get("no-such-request")


def test_invalid_manifest_rejected_before_write(tmp_path: Path) -> None:
    repository, run = _repository(tmp_path)

    with pytest.raises(ValueError):
        ModelRequestManifest(
            request_id="req-x",
            run_id=run.id,
            step_id="draft-1",
            role=ModelRole.AGENT,
            provider_id="provider-1",
            model_id="model-1",
            prompt_revision="prose-v1",
            project_constitution_revision=None,
            project_policy_revision=None,
            writing_profile_revision=None,
            toolset_revision=None,
            skill_revisions=(),
            editor_snapshot_revision=None,
            context_manifest_id=None,
            conversation_summary_revision=None,
            global_prefix_hash="not-a-hash",
            project_prefix_hash=_HASH,
            run_prefix_hash=_HASH,
            source_artifacts=(),
            input_token_estimate=None,
            cached_input_tokens=None,
            cache_status=CacheStatus.UNKNOWN,
        )
    assert repository.list_for_run(run.id) == ()
