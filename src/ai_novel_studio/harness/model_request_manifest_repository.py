from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from ai_novel_studio.harness.model_roles import ModelRole
from ai_novel_studio.harness.prompt_compiler import CacheStatus, ModelRequestManifest
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class ModelRequestManifestRepository:
    """SQLite persistence for ModelRequestManifest records (schema v24).

    Every model request keeps a local manifest for reproduction, diagnosis,
    cache analysis and audit (design v0.3 §15.2). The manifest dataclass
    validates itself on construction; this repository only maps rows.
    """

    def __init__(self, project: ProjectRepository) -> None:
        self.project = project

    def save(self, manifest: ModelRequestManifest) -> ModelRequestManifest:
        if not isinstance(manifest, ModelRequestManifest):
            raise TypeError("model request manifest is invalid")
        now = datetime.now(UTC).isoformat()
        with self.project.database.connect() as connection, connection:
            connection.execute(
                """
                INSERT INTO harness_model_request_manifests(
                    id, run_id, step_id, role, provider_id, model_id,
                    prompt_revision, project_constitution_revision,
                    project_policy_revision, writing_profile_revision,
                    toolset_revision, skill_revisions_json,
                    editor_snapshot_revision, context_manifest_id,
                    conversation_summary_revision, global_prefix_hash,
                    project_prefix_hash, run_prefix_hash,
                    source_artifacts_json, input_token_estimate,
                    cached_input_tokens, cache_status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    manifest.request_id,
                    manifest.run_id,
                    manifest.step_id,
                    manifest.role.value,
                    manifest.provider_id,
                    manifest.model_id,
                    manifest.prompt_revision,
                    manifest.project_constitution_revision,
                    manifest.project_policy_revision,
                    manifest.writing_profile_revision,
                    manifest.toolset_revision,
                    json.dumps(manifest.skill_revisions, ensure_ascii=False),
                    manifest.editor_snapshot_revision,
                    manifest.context_manifest_id,
                    manifest.conversation_summary_revision,
                    manifest.global_prefix_hash,
                    manifest.project_prefix_hash,
                    manifest.run_prefix_hash,
                    json.dumps(manifest.source_artifacts, ensure_ascii=False),
                    manifest.input_token_estimate,
                    manifest.cached_input_tokens,
                    manifest.cache_status.value,
                    now,
                ),
            )
        return manifest

    def get(self, request_id: str) -> ModelRequestManifest:
        with self.project.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM harness_model_request_manifests WHERE id = ?",
                (request_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown model request manifest: {request_id}")
        return self._manifest(row)

    def list_for_run(self, run_id: str) -> tuple[ModelRequestManifest, ...]:
        with self.project.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM harness_model_request_manifests
                WHERE run_id = ? ORDER BY created_at, id
                """,
                (run_id,),
            ).fetchall()
        return tuple(self._manifest(row) for row in rows)

    def latest_for_run(self, run_id: str) -> ModelRequestManifest | None:
        with self.project.database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM harness_model_request_manifests
                WHERE run_id = ? ORDER BY created_at DESC, id DESC LIMIT 1
                """,
                (run_id,),
            ).fetchone()
        return None if row is None else self._manifest(row)

    @staticmethod
    def _manifest(row: sqlite3.Row) -> ModelRequestManifest:
        return ModelRequestManifest(
            request_id=row["id"],
            run_id=row["run_id"],
            step_id=row["step_id"],
            role=ModelRole(row["role"]),
            provider_id=row["provider_id"],
            model_id=row["model_id"],
            prompt_revision=row["prompt_revision"],
            project_constitution_revision=row["project_constitution_revision"],
            project_policy_revision=row["project_policy_revision"],
            writing_profile_revision=row["writing_profile_revision"],
            toolset_revision=row["toolset_revision"],
            skill_revisions=tuple(json.loads(row["skill_revisions_json"])),
            editor_snapshot_revision=row["editor_snapshot_revision"],
            context_manifest_id=row["context_manifest_id"],
            conversation_summary_revision=row["conversation_summary_revision"],
            global_prefix_hash=row["global_prefix_hash"],
            project_prefix_hash=row["project_prefix_hash"],
            run_prefix_hash=row["run_prefix_hash"],
            source_artifacts=tuple(json.loads(row["source_artifacts_json"])),
            input_token_estimate=row["input_token_estimate"],
            cached_input_tokens=row["cached_input_tokens"],
            cache_status=CacheStatus(row["cache_status"]),
        )
