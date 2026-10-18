from __future__ import annotations

import pytest

from ai_novel_studio.harness.approvals import ApprovalKind, ApprovalRequest, ApprovalStatus


def _request(**overrides: object) -> ApprovalRequest:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    fields: dict[str, object] = dict(
        request_id="req-1",
        run_id="run-1",
        kind=ApprovalKind.CHANGESET,
        summary="replace the opening scene",
        payload={"changes": []},
        expected_revisions=(("chapter", 3),),
        idempotency_key="key-1",
        status=ApprovalStatus.PENDING,
        created_at=now,
        resolved_at=None,
        resolution_note=None,
    )
    fields.update(overrides)
    return ApprovalRequest(**fields)


def test_kind_and_status_vocabulary() -> None:
    assert {kind.value for kind in ApprovalKind} == {
        "CHANGESET",
        "PROMPT_CHANGE",
        "PROJECT_CONSTITUTION",
        "SUBJECT_MERGE",
        "SKILL_CHANGE",
    }
    assert {status.value for status in ApprovalStatus} == {
        "PENDING",
        "APPROVED",
        "REJECTED",
    }


def test_request_requires_ids_summary_and_key() -> None:
    with pytest.raises(ValueError):
        _request(request_id=" ")
    with pytest.raises(ValueError):
        _request(run_id=" ")
    with pytest.raises(ValueError):
        _request(summary=" ")
    with pytest.raises(ValueError):
        _request(idempotency_key=" ")


def test_request_rejects_bad_enums_payload_and_revisions() -> None:
    with pytest.raises(ValueError):
        _request(kind="CHANGESET")
    with pytest.raises(ValueError):
        _request(status="PENDING")
    with pytest.raises(ValueError):
        _request(payload={"bad": object()})
    with pytest.raises(ValueError):
        _request(expected_revisions=(("chapter", -1),))
    with pytest.raises(ValueError):
        _request(expected_revisions=((" ", 1),))


def test_request_normalizes_note() -> None:
    request = _request(resolution_note="  ")
    assert request.resolution_note is None
    assert _request(resolution_note="  ok  ").resolution_note == "ok"
