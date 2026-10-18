from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

_APPROVAL_KINDS = {
    "CHANGESET",
    "PROMPT_CHANGE",
    "PROJECT_CONSTITUTION",
    "SUBJECT_MERGE",
    "SKILL_CHANGE",
}
_COMMIT_CAPABLE_KINDS = {"CHANGESET", "SUBJECT_MERGE", "PROJECT_CONSTITUTION"}
_UNSUPPORTED_KINDS = {"PROMPT_CHANGE", "SKILL_CHANGE"}
_CHANGE_OPERATION_KINDS = {
    "CHAPTER_CONTENT_REPLACE",
    "CHAPTER_TITLE_CHANGE",
    "REPAIR_APPLY",
}
_CONTENT_REPLACE_REQUIRED_KEYS = {"content", "source", "reason"}
_CONTENT_REPLACE_ALLOWED_KEYS = _CONTENT_REPLACE_REQUIRED_KEYS | {
    "invalidate_memory",
    "selection_patch",
}
_TITLE_CHANGE_KEYS = {"title"}
_REPAIR_APPLY_KEYS = {"proposal_id"}
_SELECTION_PATCH_FIELDS = {
    "schema_version",
    "chapter_id",
    "base_revision",
    "base_source_hash",
    "selection",
    "before_anchor",
    "after_anchor",
    "replacement_candidate_id",
    "replacement_text",
    "replacement_hash",
    "result_hash",
}
_SELECTION_PATCH_SPAN_FIELDS = {"start", "end", "text", "text_hash"}
_CONSTITUTION_RULE_KEYS = {
    "shared_creative_rules",
    "agent_only_rules",
    "writer_only_rules",
    "overridable_rules",
    "non_overridable_rules",
}
_CONSTITUTION_LIST_KEYS = {
    "source_decisions",
    "excluded_provisional",
    "unresolved",
}
_CONSTITUTION_KEYS = (
    {"base_revision", "behavior_note"} | _CONSTITUTION_RULE_KEYS | _CONSTITUTION_LIST_KEYS
)
_MAX_EVIDENCE_BYTES = 16 * 1024
_MAX_CHANGESET_OPERATIONS = 50
_MAX_LEGACY_PAYLOAD_BYTES = 1024 * 1024
_MAX_SELECTION_PATCH_BYTES = 200_000
_MAX_SELECTION_CODEPOINTS = 20_000
_MAX_REPLACEMENT_CODEPOINTS = 20_000
_MAX_ANCHOR_CODEPOINTS = 64
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

_RECEIPT_TABLE_SQL = """
CREATE TABLE harness_approval_execution_receipts (
    approval_request_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL CHECK(length(trim(idempotency_key)) > 0),
    kind TEXT NOT NULL CHECK(kind IN (
        'CHANGESET', 'PROMPT_CHANGE', 'PROJECT_CONSTITUTION',
        'SUBJECT_MERGE', 'SKILL_CHANGE'
    )),
    decision TEXT CHECK(decision IS NULL OR decision IN ('APPROVED', 'REJECTED')),
    execution_state TEXT NOT NULL CHECK(execution_state IN (
        'PENDING_DECISION', 'READY', 'EXECUTING', 'RECOVERY_REQUIRED', 'FINALIZED'
    )),
    disposition TEXT CHECK(
        disposition IS NULL OR disposition IN ('APPLIED', 'DISCARDED', 'STALE', 'FAILED')
    ),
    commit_target_kind TEXT NOT NULL CHECK(commit_target_kind IN (
        'CHANGESET', 'SUBJECT_MERGE', 'PROJECT_CONSTITUTION',
        'UNSUPPORTED_APPROVAL', 'LEGACY_UNRESOLVED'
    )),
    commit_target_id TEXT NOT NULL CHECK(length(trim(commit_target_id)) > 0),
    target_identity_json TEXT NOT NULL CHECK(
        length(CAST(target_identity_json AS BLOB)) BETWEEN 2 AND 16384
    ),
    domain_receipt_id TEXT,
    result_evidence_json TEXT NOT NULL DEFAULT '[]' CHECK(
        length(CAST(result_evidence_json AS BLOB)) BETWEEN 2 AND 16384
    ),
    failure_class TEXT CHECK(
        failure_class IS NULL OR (
            length(failure_class) BETWEEN 1 AND 64
            AND failure_class NOT GLOB '*[^A-Z0-9_]*'
            AND failure_class IN (
                'STALE_CONFLICT', 'VALIDATION', 'SERIALIZATION',
                'UNSUPPORTED', 'INTEGRITY', 'PERSISTENCE'
            )
        )
    ),
    failure_code TEXT CHECK(
        failure_code IS NULL OR (
            length(failure_code) BETWEEN 1 AND 64
            AND failure_code NOT GLOB '*[^A-Z0-9_]*'
            AND failure_code IN (
                'REVISION_CONFLICT', 'CONTENT_HASH_CONFLICT',
                'PATCH_REPLAY_CONFLICT', 'VALIDATION_FAILED',
                'SERIALIZATION_FAILED', 'UNSUPPORTED_KIND',
                'IDEMPOTENCY_IDENTITY_MISMATCH', 'DATABASE_ERROR',
                'MISSING_OUTCOME', 'PARTIAL_OUTCOME',
                'MISSING_TARGET_IDENTITY'
            )
        )
    ),
    failure_summary TEXT CHECK(
        failure_summary IS NULL OR length(failure_summary) <= 512
    ),
    created_at TEXT NOT NULL CHECK(length(trim(created_at)) > 0),
    updated_at TEXT NOT NULL CHECK(length(trim(updated_at)) > 0),
    started_at TEXT,
    finalized_at TEXT,
    revision INTEGER NOT NULL CHECK(
        typeof(revision) = 'integer' AND revision >= 0
    ),
    CHECK(COALESCE(
        (
            (failure_class IS NULL AND failure_code IS NULL)
            OR (
                failure_class = 'STALE_CONFLICT'
                AND failure_code IN (
                    'REVISION_CONFLICT',
                    'CONTENT_HASH_CONFLICT',
                    'PATCH_REPLAY_CONFLICT'
                )
            )
            OR (
                failure_class = 'VALIDATION'
                AND failure_code = 'VALIDATION_FAILED'
            )
            OR (
                failure_class = 'SERIALIZATION'
                AND failure_code = 'SERIALIZATION_FAILED'
            )
            OR (
                failure_class = 'UNSUPPORTED'
                AND failure_code = 'UNSUPPORTED_KIND'
            )
            OR (
                failure_class = 'INTEGRITY'
                AND failure_code IN (
                    'IDEMPOTENCY_IDENTITY_MISMATCH',
                    'MISSING_OUTCOME',
                    'PARTIAL_OUTCOME',
                    'MISSING_TARGET_IDENTITY'
                )
            )
            OR (
                failure_class = 'PERSISTENCE'
                AND failure_code = 'DATABASE_ERROR'
            )
        ),
        0
    )),
    UNIQUE(run_id, idempotency_key),
    FOREIGN KEY(approval_request_id, run_id, idempotency_key, kind)
        REFERENCES harness_approvals(id, run_id, idempotency_key, kind),
    CHECK(COALESCE(
        (
            (
                (commit_target_kind = 'CHANGESET' AND kind = 'CHANGESET')
                OR (
                    commit_target_kind = 'SUBJECT_MERGE'
                    AND kind = 'SUBJECT_MERGE'
                )
                OR (
                    commit_target_kind = 'PROJECT_CONSTITUTION'
                    AND kind = 'PROJECT_CONSTITUTION'
                )
            )
            AND (
                (
                    execution_state = 'PENDING_DECISION'
                    AND decision IS NULL
                    AND disposition IS NULL
                    AND started_at IS NULL
                    AND finalized_at IS NULL
                    AND domain_receipt_id IS NULL
                    AND result_evidence_json = '[]'
                    AND failure_class IS NULL
                    AND failure_code IS NULL
                    AND failure_summary IS NULL
                )
                OR (
                    execution_state = 'READY'
                    AND decision = 'APPROVED'
                    AND disposition IS NULL
                    AND started_at IS NULL
                    AND finalized_at IS NULL
                    AND domain_receipt_id IS NULL
                    AND result_evidence_json = '[]'
                    AND failure_class IS NULL
                    AND failure_code IS NULL
                    AND failure_summary IS NULL
                )
                OR (
                    execution_state = 'EXECUTING'
                    AND decision = 'APPROVED'
                    AND disposition IS NULL
                    AND started_at IS NOT NULL
                    AND finalized_at IS NULL
                    AND domain_receipt_id IS NULL
                    AND result_evidence_json = '[]'
                    AND failure_class IS NULL
                    AND failure_code IS NULL
                    AND failure_summary IS NULL
                )
                OR (
                    execution_state = 'RECOVERY_REQUIRED'
                    AND decision = 'APPROVED'
                    AND disposition IS NULL
                    AND finalized_at IS NULL
                    AND domain_receipt_id IS NULL
                    AND result_evidence_json = '[]'
                    AND failure_class IS NULL
                    AND failure_code IS NULL
                    AND failure_summary IS NULL
                )
                OR (
                    execution_state = 'FINALIZED'
                    AND finalized_at IS NOT NULL
                    AND (
                        (
                            decision = 'REJECTED'
                            AND disposition = 'DISCARDED'
                            AND started_at IS NULL
                            AND domain_receipt_id IS NULL
                            AND result_evidence_json = '[]'
                            AND failure_class IS NULL
                            AND failure_code IS NULL
                            AND failure_summary IS NULL
                        )
                        OR (
                            decision = 'APPROVED'
                            AND disposition = 'APPLIED'
                            AND started_at IS NOT NULL
                            AND domain_receipt_id IS NOT NULL
                            AND result_evidence_json <> '[]'
                            AND failure_class IS NULL
                            AND failure_code IS NULL
                            AND failure_summary IS NULL
                        )
                        OR (
                            decision = 'APPROVED'
                            AND disposition = 'STALE'
                            AND failure_class = 'STALE_CONFLICT'
                            AND failure_code IN (
                                'REVISION_CONFLICT',
                                'CONTENT_HASH_CONFLICT',
                                'PATCH_REPLAY_CONFLICT'
                            )
                        )
                        OR (
                            decision = 'APPROVED'
                            AND disposition = 'FAILED'
                            AND failure_class IS NOT NULL
                            AND failure_class <> 'STALE_CONFLICT'
                            AND failure_code IS NOT NULL
                        )
                    )
                )
            )
        )
        OR (
            commit_target_kind = 'LEGACY_UNRESOLVED'
            AND kind IN ('CHANGESET', 'SUBJECT_MERGE', 'PROJECT_CONSTITUTION')
            AND commit_target_id = approval_request_id
            AND started_at IS NULL
            AND domain_receipt_id IS NULL
            AND result_evidence_json = '[]'
            AND (
                (
                    execution_state = 'PENDING_DECISION'
                    AND decision IS NULL
                    AND disposition IS NULL
                    AND finalized_at IS NULL
                    AND failure_class IS NULL
                    AND failure_code IS NULL
                    AND failure_summary IS NULL
                )
                OR (
                    execution_state = 'RECOVERY_REQUIRED'
                    AND decision = 'APPROVED'
                    AND disposition IS NULL
                    AND finalized_at IS NULL
                    AND failure_class IS NULL
                    AND failure_code IS NULL
                    AND failure_summary IS NULL
                )
                OR (
                    execution_state = 'FINALIZED'
                    AND finalized_at IS NOT NULL
                    AND (
                        (
                            decision = 'REJECTED'
                            AND disposition = 'DISCARDED'
                            AND failure_class IS NULL
                            AND failure_code IS NULL
                            AND failure_summary IS NULL
                        )
                        OR (
                            decision = 'APPROVED'
                            AND disposition = 'FAILED'
                            AND failure_class = 'INTEGRITY'
                            AND failure_code = 'MISSING_TARGET_IDENTITY'
                        )
                    )
                )
            )
        )
        OR (
            commit_target_kind = 'UNSUPPORTED_APPROVAL'
            AND kind IN ('PROMPT_CHANGE', 'SKILL_CHANGE')
            AND commit_target_id = approval_request_id
            AND started_at IS NULL
            AND domain_receipt_id IS NULL
            AND result_evidence_json = '[]'
            AND (
                (
                    execution_state = 'PENDING_DECISION'
                    AND decision IS NULL
                    AND disposition IS NULL
                    AND finalized_at IS NULL
                    AND failure_class IS NULL
                    AND failure_code IS NULL
                    AND failure_summary IS NULL
                )
                OR (
                    execution_state = 'FINALIZED'
                    AND finalized_at IS NOT NULL
                    AND (
                        (
                            decision = 'REJECTED'
                            AND disposition = 'DISCARDED'
                            AND failure_class IS NULL
                            AND failure_code IS NULL
                            AND failure_summary IS NULL
                        )
                        OR (
                            decision = 'APPROVED'
                            AND disposition = 'FAILED'
                            AND failure_class = 'UNSUPPORTED'
                            AND failure_code = 'UNSUPPORTED_KIND'
                        )
                    )
                )
            )
        ),
        0
    ))
)
"""

_EVENT_TABLE_V25_SQL = """
CREATE TABLE harness_run_events_v25 (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES harness_runs(id),
    sequence INTEGER NOT NULL CHECK(sequence >= 0),
    event_type TEXT NOT NULL CHECK(event_type IN (
        'RUN_CREATED', 'RUN_STARTED', 'RUN_CANCELLED', 'RUN_INTERRUPTED',
        'RUN_FAILED', 'RUN_COMPLETED', 'CONTEXT_COMPILATION_STARTED',
        'CONTEXT_COMPILED', 'CONTEXT_INVALIDATED',
        'CONTEXT_EXTENSION_REQUESTED', 'CONTEXT_RECOMPILE_REQUESTED',
        'CONTEXT_HEALTH_CHANGED', 'MANUAL_CONTEXT_PIN_ADDED',
        'MANUAL_CONTEXT_PIN_REMOVED', 'COMPACTION_STARTED',
        'COMPACTION_COMPLETED', 'SKILL_DISCOVERED', 'SKILL_LOADED',
        'TOOL_SCHEMA_LOADED', 'TOOL_CALL_STARTED', 'TOOL_CALL_COMPLETED',
        'TOOL_CALL_FAILED', 'GENERATION_PACKAGE_READY',
        'CHAPTER_STREAM_STARTED', 'CHAPTER_STREAM_DELTA',
        'CHAPTER_STREAM_CHECKPOINT_SAVED', 'CHAPTER_STREAM_COMPLETED',
        'AUDIT_STARTED', 'AUDIT_COMPLETED', 'CHANGESET_READY',
        'CHANGESET_REBASED', 'CHANGESET_CONFLICTED',
        'APPROVAL_REQUESTED', 'APPROVAL_RESOLVED',
        'APPROVAL_EXECUTION_FINALIZED'
    )),
    schema_version INTEGER NOT NULL CHECK(schema_version >= 1),
    occurred_at TEXT NOT NULL,
    causation_id TEXT,
    correlation_id TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(run_id, sequence)
)
"""

_EVENT_COLUMNS = (
    "id",
    "run_id",
    "sequence",
    "event_type",
    "schema_version",
    "occurred_at",
    "causation_id",
    "correlation_id",
    "payload_json",
)


@dataclass(frozen=True, slots=True)
class _LegacyApproval:
    approval_request_id: str
    run_id: str
    kind: str
    payload_json: str
    expected_revisions_json: str
    idempotency_key: str
    status: str
    created_at: str
    resolved_at: str | None


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is invalid")
    return value.strip()


def _non_negative_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} is invalid")
    return value


def _optional_digest(value: object, field: str) -> str | None:
    if value is None:
        return None
    normalized = _required_string(value, field)
    if _DIGEST_RE.fullmatch(normalized) is None:
        raise ValueError(f"{field} is invalid")
    return normalized


def _required_digest(value: object, field: str) -> str:
    normalized = _optional_digest(value, field)
    if normalized is None:
        raise ValueError(f"{field} is invalid")
    return normalized


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stable_identity_json(value: dict[str, object]) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if len(serialized.encode("utf-8")) > _MAX_EVIDENCE_BYTES:
        raise ValueError("target identity is too large")
    return serialized


def _payload_object(payload_json: str) -> dict[str, object]:
    if len(payload_json.encode("utf-8")) > _MAX_LEGACY_PAYLOAD_BYTES:
        raise ValueError("legacy payload is too large")
    value = json.loads(payload_json)
    if not isinstance(value, dict) or not value:
        raise ValueError("legacy payload is not a non-empty object")
    return value


def _parse_expected_revisions(serialized: str) -> tuple[tuple[str, int], ...]:
    value = json.loads(serialized)
    if not isinstance(value, list):
        raise ValueError("expected revisions are invalid")
    revisions: list[tuple[str, int]] = []
    for item in value:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError("expected revision item is invalid")
        revisions.append(
            (
                _required_string(item[0], "expected revision key"),
                _non_negative_integer(item[1], "expected revision"),
            )
        )
    if len({key for key, _ in revisions}) != len(revisions):
        raise ValueError("expected revision keys are duplicated")
    return tuple(revisions)


def _strict_dict(value: object, fields: set[str], field: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{field} shape is invalid")
    return cast(dict[str, object], value)


def _json_size(value: dict[str, object]) -> int:
    try:
        return len(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
    except (TypeError, ValueError):
        raise ValueError("selection patch JSON is invalid") from None


def _selection_patch_span(
    value: object,
    *,
    maximum: int,
    field: str,
) -> tuple[int, int, str]:
    span = _strict_dict(value, _SELECTION_PATCH_SPAN_FIELDS, field)
    start = _non_negative_integer(span["start"], f"{field}.start")
    end = _non_negative_integer(span["end"], f"{field}.end")
    text = span["text"]
    if (
        not isinstance(text, str)
        or end < start
        or end - start != len(text)
        or len(text) > maximum
        or _required_digest(span["text_hash"], f"{field}.text_hash") != _sha256(text)
    ):
        raise ValueError(f"{field} is invalid")
    return start, end, text


def _selection_patch_source_hash(
    value: object,
    *,
    chapter_id: str,
    expected_revision: int,
    expected_result_hash: str,
) -> str:
    patch = _strict_dict(value, _SELECTION_PATCH_FIELDS, "selection patch")
    if _json_size(patch) > _MAX_SELECTION_PATCH_BYTES:
        raise ValueError("selection patch is too large")
    if patch["schema_version"] != "selection-patch-v1":
        raise ValueError("selection patch schema is invalid")
    if _required_string(patch["chapter_id"], "selection patch chapter_id") != chapter_id:
        raise ValueError("selection patch chapter identity is invalid")
    if (
        _non_negative_integer(patch["base_revision"], "selection patch base_revision")
        != expected_revision
    ):
        raise ValueError("selection patch revision is invalid")
    base_source_hash = _required_digest(
        patch["base_source_hash"], "selection patch base_source_hash"
    )
    selection_start, selection_end, selection_text = _selection_patch_span(
        patch["selection"],
        maximum=_MAX_SELECTION_CODEPOINTS,
        field="selection",
    )
    _before_start, before_end, _before_text = _selection_patch_span(
        patch["before_anchor"],
        maximum=_MAX_ANCHOR_CODEPOINTS,
        field="before_anchor",
    )
    after_start, _after_end, _after_text = _selection_patch_span(
        patch["after_anchor"],
        maximum=_MAX_ANCHOR_CODEPOINTS,
        field="after_anchor",
    )
    if not selection_text or before_end != selection_start or after_start != selection_end:
        raise ValueError("selection patch spans are invalid")
    candidate_id = _required_string(patch["replacement_candidate_id"], "replacement_candidate_id")
    replacement_text = patch["replacement_text"]
    if (
        _ARTIFACT_ID_RE.fullmatch(candidate_id) is None
        or not isinstance(replacement_text, str)
        or not replacement_text.strip()
        or len(replacement_text) > _MAX_REPLACEMENT_CODEPOINTS
    ):
        raise ValueError("selection patch replacement is invalid")
    replacement_hash = _required_digest(patch["replacement_hash"], "replacement_hash")
    if (
        replacement_hash != _sha256(replacement_text)
        or candidate_id != f"sha256:{replacement_hash}"
    ):
        raise ValueError("selection patch replacement identity is invalid")
    result_hash = _required_digest(patch["result_hash"], "result_hash")
    if result_hash != expected_result_hash:
        raise ValueError("selection patch result identity is invalid")
    return base_source_hash


def _validate_change_operation_payload(
    kind: str,
    payload: object,
    *,
    chapter_id: str,
    expected_revision: int,
) -> str | None:
    if not isinstance(payload, dict):
        raise ValueError("change operation payload is invalid")
    parsed = cast(dict[str, object], payload)
    if kind == "CHAPTER_CONTENT_REPLACE":
        if (
            not _CONTENT_REPLACE_REQUIRED_KEYS <= set(parsed)
            or not set(parsed) <= _CONTENT_REPLACE_ALLOWED_KEYS
        ):
            raise ValueError("chapter content replacement payload shape is invalid")
        for field in _CONTENT_REPLACE_REQUIRED_KEYS:
            _required_string(parsed[field], field)
        invalidate_memory = parsed.get("invalidate_memory", True)
        if not isinstance(invalidate_memory, bool):
            raise ValueError("invalidate_memory is invalid")
        selection_patch = parsed.get("selection_patch")
        if selection_patch is None:
            return None
        return _selection_patch_source_hash(
            selection_patch,
            chapter_id=chapter_id,
            expected_revision=expected_revision,
            expected_result_hash=_required_digest(parsed["content"], "content result hash"),
        )
    if kind == "CHAPTER_TITLE_CHANGE":
        title_payload = _strict_dict(parsed, _TITLE_CHANGE_KEYS, "chapter title payload")
        _required_string(title_payload["title"], "title")
        return None
    if kind == "REPAIR_APPLY":
        repair_payload = _strict_dict(parsed, _REPAIR_APPLY_KEYS, "repair payload")
        _required_string(repair_payload["proposal_id"], "proposal_id")
        return None
    raise ValueError("unknown change operation kind")


def _changeset_identity(payload: dict[str, object]) -> tuple[str, str]:
    if set(payload) != {"change_set_id", "operations"}:
        raise ValueError("change set payload shape is invalid")
    operations_value = payload["operations"]
    if (
        not isinstance(operations_value, list)
        or not operations_value
        or len(operations_value) > _MAX_CHANGESET_OPERATIONS
    ):
        raise ValueError("change set operations are invalid")
    operations: list[dict[str, object]] = []
    operation_ids: set[str] = set()
    for raw_operation in operations_value:
        if not isinstance(raw_operation, dict) or set(raw_operation) != {
            "operation_id",
            "kind",
            "chapter_id",
            "expected_revision",
            "payload",
        }:
            raise ValueError("change set operation shape is invalid")
        kind = _required_string(raw_operation["kind"], "operation kind")
        if kind not in _CHANGE_OPERATION_KINDS:
            raise ValueError("change operation kind is invalid")
        chapter_id = _required_string(raw_operation["chapter_id"], "chapter_id")
        expected_revision = _non_negative_integer(
            raw_operation["expected_revision"], "expected_revision"
        )
        source_hash = _validate_change_operation_payload(
            kind,
            raw_operation["payload"],
            chapter_id=chapter_id,
            expected_revision=expected_revision,
        )
        operation_id = _required_string(raw_operation["operation_id"], "operation_id")
        if operation_id in operation_ids:
            raise ValueError("change set operation ids are duplicated")
        operation_ids.add(operation_id)
        operations.append(
            {
                "operation_id": operation_id,
                "operation_kind": kind,
                "target_id": chapter_id,
                "expected_revision": expected_revision,
                "source_hash": source_hash,
            }
        )
    change_set_id = _required_string(payload["change_set_id"], "change_set_id")
    return change_set_id, _stable_identity_json(
        {
            "schema_version": "changeset-target-v1",
            "change_set_id": change_set_id,
            "operations": operations,
        }
    )


def _subject_merge_identity(
    approval: _LegacyApproval,
    payload: dict[str, object],
) -> str:
    allowed_keys = {
        "source_character_id",
        "target_character_id",
        "reason",
        "preview_snapshot",
    }
    required_keys = {"source_character_id", "target_character_id", "reason"}
    if not required_keys <= set(payload) or not set(payload) <= allowed_keys:
        raise ValueError("subject merge payload shape is invalid")
    _required_string(payload["reason"], "reason")
    source_subject_id = _required_string(payload["source_character_id"], "source_character_id")
    target_subject_id = _required_string(payload["target_character_id"], "target_character_id")
    if source_subject_id == target_subject_id:
        raise ValueError("subject merge source and target must differ")
    expected_revisions = _parse_expected_revisions(approval.expected_revisions_json)
    return _stable_identity_json(
        {
            "schema_version": "subject-merge-target-v1",
            "approval_request_id": approval.approval_request_id,
            "source_subject_id": source_subject_id,
            "target_subject_id": target_subject_id,
            "expected_revisions": [
                {"key": key, "revision": revision} for key, revision in expected_revisions
            ],
        }
    )


def _validated_constitution_payload(payload: dict[str, object]) -> dict[str, object]:
    if set(payload) != _CONSTITUTION_KEYS:
        raise ValueError("constitution payload shape is invalid")
    _non_negative_integer(payload["base_revision"], "base_revision")
    if not isinstance(payload["behavior_note"], str):
        raise ValueError("behavior_note is invalid")
    for key in _CONSTITUTION_RULE_KEYS:
        rules = payload[key]
        if not isinstance(rules, list):
            raise ValueError("constitution rules are invalid")
        for rule in rules:
            if not isinstance(rule, dict) or set(rule) != {"rule_id", "text"}:
                raise ValueError("constitution rule shape is invalid")
            _required_string(rule["rule_id"], "rule_id")
            _required_string(rule["text"], "rule text")
    for key in _CONSTITUTION_LIST_KEYS:
        items = payload[key]
        if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
            raise ValueError("constitution list is invalid")
    return payload


def _project_id(connection: sqlite3.Connection) -> str:
    rows = connection.execute("SELECT id FROM projects ORDER BY id LIMIT 2").fetchall()
    if len(rows) != 1:
        raise ValueError("project identity is unavailable")
    return _required_string(rows[0][0], "project_id")


def _constitution_identity(
    connection: sqlite3.Connection,
    approval: _LegacyApproval,
    payload: dict[str, object],
) -> str:
    validated = _validated_constitution_payload(payload)
    canonical = json.dumps(
        validated,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _stable_identity_json(
        {
            "schema_version": "project-constitution-target-v1",
            "approval_request_id": approval.approval_request_id,
            "project_id": _project_id(connection),
            "base_revision": _non_negative_integer(validated["base_revision"], "base_revision"),
            "proposal_digest": hashlib.sha256(canonical).hexdigest(),
        }
    )


def _normal_target(
    connection: sqlite3.Connection,
    approval: _LegacyApproval,
) -> tuple[str, str, str]:
    payload = _payload_object(approval.payload_json)
    if approval.kind == "CHANGESET":
        change_set_id, identity_json = _changeset_identity(payload)
        return "CHANGESET", change_set_id, identity_json
    if approval.kind == "SUBJECT_MERGE":
        return (
            "SUBJECT_MERGE",
            approval.approval_request_id,
            _subject_merge_identity(approval, payload),
        )
    if approval.kind == "PROJECT_CONSTITUTION":
        return (
            "PROJECT_CONSTITUTION",
            approval.approval_request_id,
            _constitution_identity(connection, approval, payload),
        )
    raise ValueError("approval kind is not commit-capable")


def _target(
    connection: sqlite3.Connection,
    approval: _LegacyApproval,
) -> tuple[str, str, str]:
    if approval.kind in _UNSUPPORTED_KINDS:
        return (
            "UNSUPPORTED_APPROVAL",
            approval.approval_request_id,
            _stable_identity_json(
                {
                    "schema_version": "unsupported-approval-v1",
                    "approval_request_id": approval.approval_request_id,
                    "approval_kind": approval.kind,
                    "reason_code": "UNSUPPORTED_KIND",
                }
            ),
        )
    try:
        return _normal_target(connection, approval)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        if approval.kind not in _COMMIT_CAPABLE_KINDS:
            raise
        return (
            "LEGACY_UNRESOLVED",
            approval.approval_request_id,
            _stable_identity_json(
                {
                    "schema_version": "legacy-unresolved-v1",
                    "approval_request_id": approval.approval_request_id,
                    "approval_kind": approval.kind,
                    "reason_code": "MISSING_OR_INVALID_TARGET_IDENTITY",
                }
            ),
        )


def _state_values(
    approval: _LegacyApproval,
    target_kind: str,
) -> tuple[str | None, str, str | None, str | None, str | None, str | None]:
    if target_kind == "UNSUPPORTED_APPROVAL" and approval.status == "APPROVED":
        return (
            "APPROVED",
            "FINALIZED",
            "FAILED",
            "UNSUPPORTED",
            "UNSUPPORTED_KIND",
            approval.resolved_at or approval.created_at,
        )
    if approval.status == "PENDING":
        return None, "PENDING_DECISION", None, None, None, None
    if approval.status == "REJECTED":
        return (
            "REJECTED",
            "FINALIZED",
            "DISCARDED",
            None,
            None,
            approval.resolved_at or approval.created_at,
        )
    return "APPROVED", "RECOVERY_REQUIRED", None, None, None, None


def _approval_rows(connection: sqlite3.Connection) -> tuple[_LegacyApproval, ...]:
    rows = connection.execute(
        """
        SELECT id, run_id, kind, payload_json, expected_revisions_json,
               idempotency_key, status, created_at, resolved_at
        FROM harness_approvals
        ORDER BY created_at, id
        """
    ).fetchall()
    approvals: list[_LegacyApproval] = []
    for row in rows:
        kind = _required_string(row[2], "approval kind")
        if kind not in _APPROVAL_KINDS:
            raise ValueError("approval kind is invalid")
        approvals.append(
            _LegacyApproval(
                approval_request_id=_required_string(row[0], "approval_request_id"),
                run_id=_required_string(row[1], "run_id"),
                kind=kind,
                payload_json=_required_string(row[3], "payload_json"),
                expected_revisions_json=_required_string(row[4], "expected_revisions_json"),
                idempotency_key=_required_string(row[5], "idempotency_key"),
                status=_required_string(row[6], "status"),
                created_at=_required_string(row[7], "created_at"),
                resolved_at=row[8],
            )
        )
    return tuple(approvals)


def _backfill_receipts(connection: sqlite3.Connection) -> None:
    for approval in _approval_rows(connection):
        target_kind, target_id, target_json = _target(connection, approval)
        (
            decision,
            execution_state,
            disposition,
            failure_class,
            failure_code,
            finalized_at,
        ) = _state_values(approval, target_kind)
        updated_at = approval.resolved_at or approval.created_at
        connection.execute(
            """
            INSERT INTO harness_approval_execution_receipts(
                approval_request_id, run_id, idempotency_key, kind, decision,
                execution_state, disposition, commit_target_kind, commit_target_id,
                target_identity_json, domain_receipt_id, result_evidence_json,
                failure_class, failure_code, failure_summary, created_at, updated_at,
                started_at, finalized_at, revision
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, '[]', ?, ?, NULL, ?, ?,
                      NULL, ?, 0)
            """,
            (
                approval.approval_request_id,
                approval.run_id,
                approval.idempotency_key,
                approval.kind,
                decision,
                execution_state,
                disposition,
                target_kind,
                target_id,
                target_json,
                failure_class,
                failure_code,
                approval.created_at,
                updated_at,
                finalized_at,
            ),
        )


def _rebuild_event_table(connection: sqlite3.Connection) -> None:
    columns = ", ".join(_EVENT_COLUMNS)
    connection.execute(_EVENT_TABLE_V25_SQL)
    connection.execute(
        f"INSERT INTO harness_run_events_v25({columns}) SELECT {columns} FROM harness_run_events"
    )
    old_count = connection.execute("SELECT COUNT(*) FROM harness_run_events").fetchone()[0]
    new_count = connection.execute("SELECT COUNT(*) FROM harness_run_events_v25").fetchone()[0]
    if old_count != new_count:
        raise RuntimeError("v25 event rebuild row count mismatch")
    old_minus_new = connection.execute(
        f"SELECT {columns} FROM harness_run_events "
        f"EXCEPT SELECT {columns} FROM harness_run_events_v25 LIMIT 1"
    ).fetchone()
    new_minus_old = connection.execute(
        f"SELECT {columns} FROM harness_run_events_v25 "
        f"EXCEPT SELECT {columns} FROM harness_run_events LIMIT 1"
    ).fetchone()
    if old_minus_new is not None or new_minus_old is not None:
        raise RuntimeError("v25 event rebuild row data mismatch")
    connection.execute("DROP TABLE harness_run_events")
    connection.execute("ALTER TABLE harness_run_events_v25 RENAME TO harness_run_events")
    connection.execute(
        "CREATE INDEX harness_run_events_run ON harness_run_events(run_id, sequence)"
    )


def _verify_receipts(connection: sqlite3.Connection) -> None:
    approval_count = connection.execute("SELECT COUNT(*) FROM harness_approvals").fetchone()[0]
    receipt_count = connection.execute(
        "SELECT COUNT(*) FROM harness_approval_execution_receipts"
    ).fetchone()[0]
    if approval_count != receipt_count:
        raise RuntimeError("v25 receipt backfill row count mismatch")
    identity_mismatch = connection.execute(
        """
        SELECT 1
        FROM harness_approval_execution_receipts AS receipt
        JOIN harness_approvals AS approval
          ON approval.id = receipt.approval_request_id
        WHERE receipt.run_id <> approval.run_id
           OR receipt.idempotency_key <> approval.idempotency_key
           OR receipt.kind <> approval.kind
        LIMIT 1
        """
    ).fetchone()
    duplicate = connection.execute(
        """
        SELECT 1
        FROM harness_approval_execution_receipts
        GROUP BY run_id, idempotency_key
        HAVING COUNT(*) > 1
        LIMIT 1
        """
    ).fetchone()
    foreign_key_violation = connection.execute(
        "PRAGMA foreign_key_check(harness_approval_execution_receipts)"
    ).fetchone()
    if identity_mismatch is not None or duplicate is not None or foreign_key_violation is not None:
        raise RuntimeError("v25 receipt verification failed")


def _migration_25(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE UNIQUE INDEX harness_approvals_receipt_identity
        ON harness_approvals(id, run_id, idempotency_key, kind)
        """
    )
    connection.execute(_RECEIPT_TABLE_SQL)
    connection.execute(
        """
        CREATE INDEX harness_approval_receipts_run
        ON harness_approval_execution_receipts(run_id, execution_state, created_at)
        """
    )
    connection.execute(
        """
        CREATE INDEX harness_approval_receipts_recovery
        ON harness_approval_execution_receipts(execution_state, updated_at)
        """
    )
    _backfill_receipts(connection)
    _rebuild_event_table(connection)
    _verify_receipts(connection)


MIGRATIONS_V25: dict[int, Callable[[sqlite3.Connection], None]] = {25: _migration_25}

__all__ = ["MIGRATIONS_V25"]
