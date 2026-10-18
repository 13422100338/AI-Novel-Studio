import ast
import hashlib
import inspect
import json
import sqlite3
from collections.abc import Iterable

import pytest

import ai_novel_studio.infrastructure.storage.migration_manager as migration_module
import ai_novel_studio.infrastructure.storage.schema_migrations_v25 as migration_v25_module
from ai_novel_studio.application.selection_patch import parse_selection_patch
from ai_novel_studio.harness.approval_execution_receipt import stable_evidence_json
from ai_novel_studio.harness.approval_execution_receipt_repository import (
    ApprovalExecutionReceiptRepository,
)
from ai_novel_studio.infrastructure.storage.migration_manager import (
    LATEST_SCHEMA_VERSION,
    MigrationManager,
)
from ai_novel_studio.infrastructure.storage.schema_migrations import MIGRATIONS


def _migrated_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    MigrationManager(connection).migrate()
    return connection


def test_schema_v21_adds_harness_run_tables() -> None:
    connection = _migrated_connection()

    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    tables = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    indexes = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }

    assert version == LATEST_SCHEMA_VERSION == 25
    assert {"harness_runs", "harness_run_events"} <= tables
    assert "harness_runs_chapter" in indexes
    assert "harness_run_events_run" in indexes


def test_harness_schema_rejects_invalid_stage_and_event_type() -> None:
    connection = _migrated_connection()

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO harness_runs(id, goal, stage, created_at, updated_at) "
            "VALUES ('r1', 'goal', 'BAD_STAGE', 't', 't')"
        )
    connection.execute(
        "INSERT INTO harness_runs(id, goal, stage, created_at, updated_at) "
        "VALUES ('r1', 'goal', 'CREATED', 't', 't')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO harness_run_events("
            "id, run_id, sequence, event_type, schema_version, occurred_at"
            ") VALUES ('e1', 'r1', 1, 'BAD_TYPE', 1, 't')"
        )


def test_harness_schema_enforces_sequence_uniqueness_and_schema_version() -> None:
    connection = _migrated_connection()
    connection.execute(
        "INSERT INTO harness_runs(id, goal, stage, created_at, updated_at) "
        "VALUES ('r1', 'goal', 'CREATED', 't', 't')"
    )
    connection.execute(
        "INSERT INTO harness_run_events("
        "id, run_id, sequence, event_type, schema_version, occurred_at"
        ") VALUES ('e1', 'r1', 1, 'CONTEXT_COMPILED', 1, 't')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO harness_run_events("
            "id, run_id, sequence, event_type, schema_version, occurred_at"
            ") VALUES ('e2', 'r1', 1, 'AUDIT_COMPLETED', 1, 't')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO harness_run_events("
            "id, run_id, sequence, event_type, schema_version, occurred_at"
            ") VALUES ('e3', 'r1', 2, 'AUDIT_COMPLETED', 0, 't')"
        )


def test_harness_events_require_existing_run() -> None:
    connection = _migrated_connection()
    connection.execute("PRAGMA foreign_keys = ON")
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO harness_run_events("
            "id, run_id, sequence, event_type, schema_version, occurred_at"
            ") VALUES ('e1', 'missing', 1, 'AUDIT_COMPLETED', 1, 't')"
        )


def test_schema_v22_adds_harness_approval_table() -> None:
    connection = _migrated_connection()

    tables = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    indexes = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }

    assert "harness_approvals" in tables
    assert "harness_approvals_run" in indexes


def test_harness_approvals_reject_bad_kind_status_and_duplicate_keys() -> None:
    connection = _migrated_connection()
    connection.execute(
        "INSERT INTO harness_runs(id, goal, stage, created_at, updated_at) "
        "VALUES ('r1', 'goal', 'WAITING_APPROVAL', 't', 't')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO harness_approvals("
            "id, run_id, kind, summary, idempotency_key, status, created_at"
            ") VALUES ('a1', 'r1', 'BAD_KIND', 's', 'k1', 'PENDING', 't')"
        )
    connection.execute(
        "INSERT INTO harness_approvals("
        "id, run_id, kind, summary, idempotency_key, status, created_at"
        ") VALUES ('a1', 'r1', 'CHANGESET', 's', 'k1', 'PENDING', 't')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO harness_approvals("
            "id, run_id, kind, summary, idempotency_key, status, created_at"
            ") VALUES ('a2', 'r1', 'CHANGESET', 's', 'k1', 'PENDING', 't')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO harness_approvals("
            "id, run_id, kind, summary, idempotency_key, status, created_at"
            ") VALUES ('a3', 'r1', 'CHANGESET', 's', 'k2', 'BAD_STATUS', 't')"
        )


def test_schema_v24_adds_model_request_manifest_table() -> None:
    connection = _migrated_connection()

    tables = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    indexes = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }

    assert "harness_model_request_manifests" in tables
    assert "harness_manifests_run" in indexes


def test_model_request_manifests_reject_bad_role_cache_status_and_run() -> None:
    connection = _migrated_connection()
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        "INSERT INTO harness_runs(id, goal, stage, created_at, updated_at) "
        "VALUES ('r1', 'goal', 'CREATED', 't', 't')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO harness_model_request_manifests("
            "id, run_id, step_id, role, provider_id, model_id, prompt_revision,"
            "global_prefix_hash, project_prefix_hash, run_prefix_hash,"
            "cache_status, created_at"
            ") VALUES ('m1', 'r1', 's1', 'BAD_ROLE', 'p', 'm', 'pr',"
            "'a' * 64, 'a' * 64, 'a' * 64, 'ACCURATE', 't')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO harness_model_request_manifests("
            "id, run_id, step_id, role, provider_id, model_id, prompt_revision,"
            "global_prefix_hash, project_prefix_hash, run_prefix_hash,"
            "cache_status, created_at"
            ") VALUES ('m2', 'r1', 's1', 'AGENT', 'p', 'm', 'pr',"
            "'a' * 64, 'a' * 64, 'a' * 64, 'BAD_STATUS', 't')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO harness_model_request_manifests("
            "id, run_id, step_id, role, provider_id, model_id, prompt_revision,"
            "global_prefix_hash, project_prefix_hash, run_prefix_hash,"
            "cache_status, created_at"
            ") VALUES ('m3', 'missing', 's1', 'AGENT', 'p', 'm', 'pr',"
            "'a' * 64, 'a' * 64, 'a' * 64, 'ACCURATE', 't')"
        )


def _v24_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    with connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        for version in range(1, 25):
            MIGRATIONS[version](connection)
            connection.execute("INSERT INTO schema_migrations(version) VALUES (?)", (version,))
            connection.execute(f"PRAGMA user_version = {version}")
    return connection


def _insert_run(connection: sqlite3.Connection, run_id: str = "run-1") -> None:
    connection.execute(
        """
        INSERT INTO harness_runs(id, goal, stage, created_at, updated_at)
        VALUES (?, 'goal', 'WAITING_APPROVAL', '2026-08-28T00:00:00+00:00',
                '2026-08-28T00:00:00+00:00')
        """,
        (run_id,),
    )


def _insert_approval(
    connection: sqlite3.Connection,
    *,
    approval_id: str,
    kind: str,
    status: str,
    payload_json: str,
    expected_revisions_json: str = "[]",
    run_id: str = "run-1",
) -> None:
    connection.execute(
        """
        INSERT INTO harness_approvals(
            id, run_id, kind, summary, payload_json, expected_revisions_json,
            idempotency_key, status, created_at, resolved_at
        ) VALUES (?, ?, ?, 'summary', ?, ?, ?, ?,
                  '2026-08-28T00:00:00+00:00',
                  CASE WHEN ? = 'PENDING' THEN NULL
                       ELSE '2026-08-28T01:00:00+00:00' END)
        """,
        (
            approval_id,
            run_id,
            kind,
            payload_json,
            expected_revisions_json,
            f"key-{approval_id}",
            status,
            status,
        ),
    )


def _migrate_v24(connection: sqlite3.Connection) -> None:
    MigrationManager(connection).migrate()


def _receipt_rows(connection: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    return {
        row["approval_request_id"]: row
        for row in connection.execute(
            """
            SELECT *
            FROM harness_approval_execution_receipts
            ORDER BY approval_request_id
            """
        ).fetchall()
    }


def _valid_changeset_payload(secret: str = "MANUSCRIPT_BODY_MUST_NOT_COPY") -> str:
    return json.dumps(
        {
            "change_set_id": "change-set-1",
            "operations": [
                {
                    "operation_id": "operation-1",
                    "kind": "CHAPTER_CONTENT_REPLACE",
                    "chapter_id": "chapter-1",
                    "expected_revision": 3,
                    "payload": {
                        "content": secret,
                        "source": "agent",
                        "reason": "approved rewrite",
                    },
                }
            ],
        },
        ensure_ascii=False,
    )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _valid_selection_changeset_payload() -> tuple[str, str]:
    before = "BEFORE"
    selected = "SELECTED_TEXT_MUST_NOT_COPY"
    after = "AFTER"
    replacement = "REPLACEMENT_TEXT_MUST_NOT_COPY"
    source = before + selected + after
    result = before + replacement + after
    base_source_hash = _sha256(source)
    replacement_hash = _sha256(replacement)
    selection_start = len(before)
    selection_end = selection_start + len(selected)
    patch = {
        "schema_version": "selection-patch-v1",
        "chapter_id": "chapter-1",
        "base_revision": 3,
        "base_source_hash": base_source_hash,
        "selection": {
            "start": selection_start,
            "end": selection_end,
            "text": selected,
            "text_hash": _sha256(selected),
        },
        "before_anchor": {
            "start": 0,
            "end": selection_start,
            "text": before,
            "text_hash": _sha256(before),
        },
        "after_anchor": {
            "start": selection_end,
            "end": selection_end + len(after),
            "text": after,
            "text_hash": _sha256(after),
        },
        "replacement_candidate_id": f"sha256:{replacement_hash}",
        "replacement_text": replacement,
        "replacement_hash": replacement_hash,
        "result_hash": _sha256(result),
    }
    parse_selection_patch(patch)
    return (
        json.dumps(
            {
                "change_set_id": "selection-change-set-1",
                "operations": [
                    {
                        "operation_id": "selection-operation-1",
                        "kind": "CHAPTER_CONTENT_REPLACE",
                        "chapter_id": "chapter-1",
                        "expected_revision": 3,
                        "payload": {
                            "content": patch["result_hash"],
                            "source": "agent",
                            "reason": "selection rewrite",
                            "selection_patch": patch,
                        },
                    }
                ],
            },
            ensure_ascii=False,
        ),
        base_source_hash,
    )


def _valid_subject_merge_payload() -> str:
    return json.dumps(
        {
            "source_character_id": "subject-source",
            "target_character_id": "subject-target",
            "reason": "same subject",
        }
    )


def _valid_constitution_payload(secret: str = "PROPOSAL_TEXT_MUST_NOT_COPY") -> str:
    return json.dumps(
        {
            "base_revision": 2,
            "shared_creative_rules": [{"rule_id": "rule-1", "text": secret}],
            "agent_only_rules": [],
            "writer_only_rules": [],
            "overridable_rules": [],
            "non_overridable_rules": [],
            "source_decisions": [],
            "excluded_provisional": [],
            "unresolved": [],
            "behavior_note": "do not copy this proposal note",
        },
        ensure_ascii=False,
    )


def test_schema_v25_fresh_database_adds_receipts_indexes_and_event_vocabulary() -> None:
    connection = _migrated_connection()

    assert int(connection.execute("PRAGMA user_version").fetchone()[0]) == 25
    tables = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    indexes = {
        row["name"]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }
    assert "harness_approval_execution_receipts" in tables
    assert {
        "harness_approval_receipts_run",
        "harness_approval_receipts_recovery",
        "harness_approvals_receipt_identity",
        "harness_run_events_run",
    } <= indexes

    _insert_run(connection)
    connection.execute(
        """
        INSERT INTO harness_run_events(
            id, run_id, sequence, event_type, schema_version, occurred_at, payload_json
        ) VALUES ('execution-event', 'run-1', 0, 'APPROVAL_EXECUTION_FINALIZED',
                  1, '2026-08-28T00:00:00+00:00', '{}')
        """
    )
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO harness_run_events(
                id, run_id, sequence, event_type, schema_version, occurred_at
            ) VALUES ('bad-event', 'run-1', 1, 'UNKNOWN_EVENT', 1, 't')
            """
        )


def test_v25_migration_module_is_self_contained_from_runtime_packages() -> None:
    tree = ast.parse(inspect.getsource(migration_v25_module))
    project_imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            project_imports.extend(
                alias.name for alias in node.names if alias.name.startswith("ai_novel_studio")
            )
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.module.startswith("ai_novel_studio")
        ):
            project_imports.append(node.module)

    assert project_imports == []


def test_v25_backfill_identity_json_is_readable_by_current_strict_repository() -> None:
    connection = _v24_connection()
    connection.execute(
        """
        INSERT INTO projects(id, title, format_version, created_at, updated_at)
        VALUES ('project-1', 'Project', 1, 't', 't')
        """
    )
    _insert_run(connection)
    approvals = (
        ("changeset", "CHANGESET", _valid_changeset_payload()),
        ("merge", "SUBJECT_MERGE", _valid_subject_merge_payload()),
        ("constitution", "PROJECT_CONSTITUTION", _valid_constitution_payload()),
        ("legacy", "CHANGESET", "null"),
        ("unsupported", "PROMPT_CHANGE", '{"raw":"not-evidence"}'),
    )
    for approval_id, kind, payload_json in approvals:
        _insert_approval(
            connection,
            approval_id=approval_id,
            kind=kind,
            status="PENDING",
            payload_json=payload_json,
            expected_revisions_json=(
                '[["subject.state_events:subject-source",3]]' if kind == "SUBJECT_MERGE" else "[]"
            ),
        )
    connection.commit()

    _migrate_v24(connection)

    rows = connection.execute(
        """
        SELECT receipt.*,
               approval.run_id AS approval_run_id,
               approval.idempotency_key AS approval_idempotency_key,
               approval.kind AS approval_kind
        FROM harness_approval_execution_receipts AS receipt
        JOIN harness_approvals AS approval
          ON approval.id = receipt.approval_request_id
        ORDER BY receipt.approval_request_id
        """
    ).fetchall()
    parsed = tuple(ApprovalExecutionReceiptRepository._from_row(row) for row in rows)
    assert len(parsed) == len(approvals)
    assert tuple(stable_evidence_json(item.target_identity) for item in parsed) == tuple(
        row["target_identity_json"] for row in rows
    )


def test_v25_selection_patch_backfill_extracts_only_exact_base_source_hash() -> None:
    connection = _v24_connection()
    _insert_run(connection)
    payload_json, base_source_hash = _valid_selection_changeset_payload()
    _insert_approval(
        connection,
        approval_id="selection-approval",
        kind="CHANGESET",
        status="PENDING",
        payload_json=payload_json,
    )
    connection.commit()

    _migrate_v24(connection)

    row = connection.execute(
        """
        SELECT receipt.*,
               approval.run_id AS approval_run_id,
               approval.idempotency_key AS approval_idempotency_key,
               approval.kind AS approval_kind
        FROM harness_approval_execution_receipts AS receipt
        JOIN harness_approvals AS approval
          ON approval.id = receipt.approval_request_id
        WHERE receipt.approval_request_id = 'selection-approval'
        """
    ).fetchone()
    identity = json.loads(row["target_identity_json"])
    assert row["commit_target_kind"] == "CHANGESET"
    assert identity["operations"][0]["source_hash"] == base_source_hash
    for forbidden in (
        "SELECTED_TEXT_MUST_NOT_COPY",
        "REPLACEMENT_TEXT_MUST_NOT_COPY",
        "MANUSCRIPT_BODY_MUST_NOT_COPY",
        "selection_patch",
    ):
        assert forbidden not in row["target_identity_json"]
    parsed = ApprovalExecutionReceiptRepository._from_row(row)
    assert stable_evidence_json(parsed.target_identity) == row["target_identity_json"]


@pytest.mark.parametrize(
    "invalid_case",
    [
        "operation_unknown_field",
        "patch_unknown_field",
        "replacement_hash_mismatch",
        "chapter_mismatch",
        "revision_mismatch",
        "content_result_hash_mismatch",
        "title_unknown_field",
        "repair_unknown_field",
    ],
)
def test_invalid_selection_patch_backfill_degrades_without_raw_leak(
    invalid_case: str,
) -> None:
    connection = _v24_connection()
    _insert_run(connection)
    payload_json, _base_source_hash = _valid_selection_changeset_payload()
    payload = json.loads(payload_json)
    operation = payload["operations"][0]
    operation_payload = operation["payload"]
    patch = operation_payload["selection_patch"]
    if invalid_case == "title_unknown_field":
        operation["kind"] = "CHAPTER_TITLE_CHANGE"
        operation["payload"] = {
            "title": "New title",
            "unknown_field": "RAW_UNKNOWN_MUST_NOT_COPY",
        }
    elif invalid_case == "repair_unknown_field":
        operation["kind"] = "REPAIR_APPLY"
        operation["payload"] = {
            "proposal_id": "proposal-1",
            "unknown_field": "RAW_UNKNOWN_MUST_NOT_COPY",
        }
    elif invalid_case == "operation_unknown_field":
        operation_payload["unknown_field"] = "RAW_UNKNOWN_MUST_NOT_COPY"
    elif invalid_case == "patch_unknown_field":
        patch["unknown_field"] = "RAW_UNKNOWN_MUST_NOT_COPY"
    elif invalid_case == "replacement_hash_mismatch":
        patch["replacement_hash"] = "0" * 64
    elif invalid_case == "chapter_mismatch":
        patch["chapter_id"] = "other-chapter"
    elif invalid_case == "revision_mismatch":
        patch["base_revision"] = 4
    else:
        operation_payload["content"] = "f" * 64
    _insert_approval(
        connection,
        approval_id="selection-invalid",
        kind="CHANGESET",
        status="PENDING",
        payload_json=json.dumps(payload, ensure_ascii=False),
    )
    connection.commit()

    _migrate_v24(connection)

    receipt = _receipt_rows(connection)["selection-invalid"]
    assert (
        receipt["commit_target_kind"],
        receipt["commit_target_id"],
        receipt["execution_state"],
    ) == (
        "LEGACY_UNRESOLVED",
        "selection-invalid",
        "PENDING_DECISION",
    )
    assert json.loads(receipt["target_identity_json"]) == {
        "approval_kind": "CHANGESET",
        "approval_request_id": "selection-invalid",
        "reason_code": "MISSING_OR_INVALID_TARGET_IDENTITY",
        "schema_version": "legacy-unresolved-v1",
    }
    for forbidden in (
        "SELECTED_TEXT_MUST_NOT_COPY",
        "REPLACEMENT_TEXT_MUST_NOT_COPY",
        "RAW_UNKNOWN_MUST_NOT_COPY",
        "selection_patch",
    ):
        assert forbidden not in receipt["target_identity_json"]


def test_v24_to_v25_preserves_historical_event_rows_field_for_field() -> None:
    connection = _v24_connection()
    _insert_run(connection)
    historical = (
        "event-1",
        "run-1",
        7,
        "APPROVAL_RESOLVED",
        1,
        "2026-08-28T02:03:04+00:00",
        "cause-1",
        "approval-1",
        '{"request_id":"approval-1","approved":true,"exact":"  spacing  "}',
    )
    connection.execute(
        """
        INSERT INTO harness_run_events(
            id, run_id, sequence, event_type, schema_version, occurred_at,
            causation_id, correlation_id, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        historical,
    )
    before = tuple(connection.execute("SELECT * FROM harness_run_events").fetchone())
    connection.commit()

    _migrate_v24(connection)

    after = tuple(connection.execute("SELECT * FROM harness_run_events").fetchone())
    assert int(connection.execute("PRAGMA user_version").fetchone()[0]) == 25
    assert after == before
    assert connection.execute("SELECT COUNT(*) FROM harness_run_events").fetchone()[0] == 1
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM harness_run_events "
            "WHERE event_type = 'APPROVAL_EXECUTION_FINALIZED'"
        ).fetchone()[0]
        == 0
    )


@pytest.mark.parametrize(
    ("status", "state", "decision", "disposition"),
    [
        ("PENDING", "PENDING_DECISION", None, None),
        ("REJECTED", "FINALIZED", "REJECTED", "DISCARDED"),
        ("APPROVED", "RECOVERY_REQUIRED", "APPROVED", None),
    ],
)
def test_v25_backfills_normal_changeset_status_branches(
    status: str,
    state: str,
    decision: str | None,
    disposition: str | None,
) -> None:
    connection = _v24_connection()
    _insert_run(connection)
    _insert_approval(
        connection,
        approval_id="approval-1",
        kind="CHANGESET",
        status=status,
        payload_json=_valid_changeset_payload(),
    )
    connection.commit()

    _migrate_v24(connection)

    receipt = _receipt_rows(connection)["approval-1"]
    assert (
        receipt["commit_target_kind"],
        receipt["commit_target_id"],
        receipt["execution_state"],
        receipt["decision"],
        receipt["disposition"],
    ) == ("CHANGESET", "change-set-1", state, decision, disposition)


@pytest.mark.parametrize(
    ("payload_json", "status", "state", "decision", "disposition"),
    [
        ("null", "PENDING", "PENDING_DECISION", None, None),
        ("{}", "REJECTED", "FINALIZED", "REJECTED", "DISCARDED"),
        ("{malformed", "APPROVED", "RECOVERY_REQUIRED", "APPROVED", None),
        (
            '{"unknown":"shape"}',
            "PENDING",
            "PENDING_DECISION",
            None,
            None,
        ),
    ],
)
def test_bad_legacy_payload_degrades_one_row_without_aborting_or_copying_raw(
    payload_json: str,
    status: str,
    state: str,
    decision: str | None,
    disposition: str | None,
) -> None:
    connection = _v24_connection()
    _insert_run(connection)
    _insert_approval(
        connection,
        approval_id="approval-bad",
        kind="CHANGESET",
        status=status,
        payload_json=payload_json,
    )
    _insert_approval(
        connection,
        approval_id="approval-valid",
        kind="CHANGESET",
        status="PENDING",
        payload_json=_valid_changeset_payload(),
    )
    connection.commit()

    _migrate_v24(connection)

    rows = _receipt_rows(connection)
    assert set(rows) == {"approval-bad", "approval-valid"}
    bad = rows["approval-bad"]
    assert (
        bad["commit_target_kind"],
        bad["commit_target_id"],
        bad["execution_state"],
        bad["decision"],
        bad["disposition"],
    ) == (
        "LEGACY_UNRESOLVED",
        "approval-bad",
        state,
        decision,
        disposition,
    )
    assert json.loads(bad["target_identity_json"]) == {
        "approval_kind": "CHANGESET",
        "approval_request_id": "approval-bad",
        "reason_code": "MISSING_OR_INVALID_TARGET_IDENTITY",
        "schema_version": "legacy-unresolved-v1",
    }
    assert payload_json not in bad["target_identity_json"]
    assert rows["approval-valid"]["commit_target_kind"] == "CHANGESET"


@pytest.mark.parametrize(
    ("status", "state", "decision", "disposition"),
    [
        ("PENDING", "PENDING_DECISION", None, None),
        ("REJECTED", "FINALIZED", "REJECTED", "DISCARDED"),
        ("APPROVED", "RECOVERY_REQUIRED", "APPROVED", None),
    ],
)
def test_legacy_unresolved_backfill_covers_all_three_statuses(
    status: str,
    state: str,
    decision: str | None,
    disposition: str | None,
) -> None:
    connection = _v24_connection()
    _insert_run(connection)
    _insert_approval(
        connection,
        approval_id="approval-1",
        kind="SUBJECT_MERGE",
        status=status,
        payload_json="null",
    )
    connection.commit()

    _migrate_v24(connection)

    receipt = _receipt_rows(connection)["approval-1"]
    assert (
        receipt["commit_target_kind"],
        receipt["execution_state"],
        receipt["decision"],
        receipt["disposition"],
    ) == ("LEGACY_UNRESOLVED", state, decision, disposition)


@pytest.mark.parametrize("kind", ["PROMPT_CHANGE", "SKILL_CHANGE"])
@pytest.mark.parametrize(
    ("status", "state", "decision", "disposition", "failure_class", "failure_code"),
    [
        ("PENDING", "PENDING_DECISION", None, None, None, None),
        ("REJECTED", "FINALIZED", "REJECTED", "DISCARDED", None, None),
        (
            "APPROVED",
            "FINALIZED",
            "APPROVED",
            "FAILED",
            "UNSUPPORTED",
            "UNSUPPORTED_KIND",
        ),
    ],
)
def test_unsupported_approval_backfill_is_fixed_and_never_executable(
    kind: str,
    status: str,
    state: str,
    decision: str | None,
    disposition: str | None,
    failure_class: str | None,
    failure_code: str | None,
) -> None:
    connection = _v24_connection()
    _insert_run(connection)
    _insert_approval(
        connection,
        approval_id="approval-1",
        kind=kind,
        status=status,
        payload_json='{"raw":"must-not-copy"}',
    )
    connection.commit()

    _migrate_v24(connection)

    receipt = _receipt_rows(connection)["approval-1"]
    assert (
        receipt["commit_target_kind"],
        receipt["commit_target_id"],
        receipt["execution_state"],
        receipt["decision"],
        receipt["disposition"],
        receipt["failure_class"],
        receipt["failure_code"],
    ) == (
        "UNSUPPORTED_APPROVAL",
        "approval-1",
        state,
        decision,
        disposition,
        failure_class,
        failure_code,
    )
    assert json.loads(receipt["target_identity_json"]) == {
        "approval_kind": kind,
        "approval_request_id": "approval-1",
        "reason_code": "UNSUPPORTED_KIND",
        "schema_version": "unsupported-approval-v1",
    }
    assert "must-not-copy" not in receipt["target_identity_json"]


@pytest.mark.parametrize(
    ("kind", "payload_json", "expected_target_kind"),
    [
        ("CHANGESET", _valid_changeset_payload(), "CHANGESET"),
        ("SUBJECT_MERGE", _valid_subject_merge_payload(), "SUBJECT_MERGE"),
        (
            "PROJECT_CONSTITUTION",
            _valid_constitution_payload(),
            "PROJECT_CONSTITUTION",
        ),
    ],
)
def test_valid_commit_capable_payloads_backfill_normal_allowlisted_identity(
    kind: str,
    payload_json: str,
    expected_target_kind: str,
) -> None:
    connection = _v24_connection()
    if kind == "PROJECT_CONSTITUTION":
        connection.execute(
            """
            INSERT INTO projects(id, title, format_version, created_at, updated_at)
            VALUES ('project-1', 'Project', 1, 't', 't')
            """
        )
    _insert_run(connection)
    _insert_approval(
        connection,
        approval_id="approval-1",
        kind=kind,
        status="PENDING",
        payload_json=payload_json,
        expected_revisions_json=(
            '[["subject.state_events:subject-source",3]]' if kind == "SUBJECT_MERGE" else "[]"
        ),
    )
    connection.commit()

    _migrate_v24(connection)

    receipt = _receipt_rows(connection)["approval-1"]
    identity = json.loads(receipt["target_identity_json"])
    assert receipt["commit_target_kind"] == expected_target_kind
    assert identity["schema_version"] in {
        "changeset-target-v1",
        "subject-merge-target-v1",
        "project-constitution-target-v1",
    }
    assert "MANUSCRIPT_BODY_MUST_NOT_COPY" not in receipt["target_identity_json"]
    assert "PROPOSAL_TEXT_MUST_NOT_COPY" not in receipt["target_identity_json"]
    assert "do not copy this proposal note" not in receipt["target_identity_json"]


def test_receipt_foreign_keys_and_sql_matrix_reject_identity_and_state_drift() -> None:
    connection = _migrated_connection()
    connection.execute("PRAGMA foreign_keys = ON")
    _insert_run(connection)
    _insert_approval(
        connection,
        approval_id="approval-1",
        kind="CHANGESET",
        status="PENDING",
        payload_json=_valid_changeset_payload(),
    )
    connection.commit()
    target_identity_json = json.dumps(
        {
            "change_set_id": "change-set-1",
            "operations": [
                {
                    "expected_revision": 3,
                    "operation_id": "operation-1",
                    "operation_kind": "CHAPTER_CONTENT_REPLACE",
                    "source_hash": None,
                    "target_id": "chapter-1",
                }
            ],
            "schema_version": "changeset-target-v1",
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    connection.execute(
        """
        INSERT INTO harness_approval_execution_receipts(
            approval_request_id, run_id, idempotency_key, kind, decision,
            execution_state, disposition, commit_target_kind, commit_target_id,
            target_identity_json, result_evidence_json, created_at, updated_at, revision
        ) VALUES (?, ?, ?, ?, NULL, ?, NULL, ?, ?, ?, '[]', ?, ?, 0)
        """,
        (
            "approval-1",
            "run-1",
            "key-approval-1",
            "CHANGESET",
            "PENDING_DECISION",
            "CHANGESET",
            "change-set-1",
            target_identity_json,
            "2026-08-28T00:00:00+00:00",
            "2026-08-28T00:00:00+00:00",
        ),
    )
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    invalid_rows: Iterable[tuple[str, tuple[object, ...]]] = (
        (
            """
            UPDATE harness_approval_execution_receipts
            SET execution_state = 'READY', decision = NULL
            WHERE approval_request_id = ?
            """,
            ("approval-1",),
        ),
        (
            """
            UPDATE harness_approval_execution_receipts
            SET commit_target_kind = 'LEGACY_UNRESOLVED',
                execution_state = 'READY', decision = 'APPROVED'
            WHERE approval_request_id = ?
            """,
            ("approval-1",),
        ),
        (
            """
            UPDATE harness_approval_execution_receipts
            SET disposition = 'APPLIED'
            WHERE approval_request_id = ?
            """,
            ("approval-1",),
        ),
        (
            """
            UPDATE harness_approval_execution_receipts
            SET decision = 'APPROVED', execution_state = 'FINALIZED',
                disposition = 'FAILED', failure_class = 'VALIDATION',
                failure_code = 'DATABASE_ERROR', finalized_at = 't'
            WHERE approval_request_id = ?
            """,
            ("approval-1",),
        ),
    )
    for sql, parameters in invalid_rows:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(sql, parameters)

    connection.execute(
        """
        UPDATE harness_approval_execution_receipts
        SET decision = 'APPROVED', execution_state = 'FINALIZED',
            disposition = 'FAILED', failure_class = 'VALIDATION',
            failure_code = 'VALIDATION_FAILED', finalized_at = 't'
        WHERE approval_request_id = 'approval-1'
        """
    )
    assert tuple(
        connection.execute(
            """
            SELECT failure_class, failure_code
            FROM harness_approval_execution_receipts
            WHERE approval_request_id = 'approval-1'
            """
        ).fetchone()
    ) == ("VALIDATION", "VALIDATION_FAILED")

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO harness_approval_execution_receipts(
                approval_request_id, run_id, idempotency_key, kind, execution_state,
                commit_target_kind, commit_target_id, target_identity_json,
                result_evidence_json, created_at, updated_at, revision
            ) VALUES ('missing', 'run-1', 'missing-key', 'CHANGESET',
                      'PENDING_DECISION', 'CHANGESET', 'change-set-2', '{}', '[]',
                      't', 't', 0)
            """
        )


def test_v25_failure_rolls_back_receipt_event_rebuild_and_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _v24_connection()
    _insert_run(connection)
    connection.execute(
        """
        INSERT INTO harness_run_events(
            id, run_id, sequence, event_type, schema_version, occurred_at, payload_json
        ) VALUES ('event-1', 'run-1', 0, 'APPROVAL_RESOLVED', 1, 't',
                  '{"request_id":"approval-1","approved":true}')
        """
    )
    before = tuple(connection.execute("SELECT * FROM harness_run_events").fetchone())
    connection.commit()
    real_migration = migration_module.MIGRATIONS[25]

    def fail_after_v25_work(current: sqlite3.Connection) -> None:
        real_migration(current)
        raise RuntimeError("injected v25 failure")

    monkeypatch.setitem(migration_module.MIGRATIONS, 25, fail_after_v25_work)
    with pytest.raises(RuntimeError, match="injected v25 failure"):
        MigrationManager(connection).migrate()

    assert int(connection.execute("PRAGMA user_version").fetchone()[0]) == 24
    assert (
        connection.execute("SELECT COUNT(*) FROM schema_migrations WHERE version = 25").fetchone()[
            0
        ]
        == 0
    )
    assert (
        connection.execute(
            """
        SELECT COUNT(*) FROM sqlite_master
        WHERE type = 'table' AND name = 'harness_approval_execution_receipts'
        """
        ).fetchone()[0]
        == 0
    )
    assert tuple(connection.execute("SELECT * FROM harness_run_events").fetchone()) == before
