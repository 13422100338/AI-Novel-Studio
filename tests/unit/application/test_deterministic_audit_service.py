import json

import pytest

from ai_novel_studio.application.deterministic_audit_service import (
    DeterministicAuditRequest,
    DeterministicAuditService,
    ReaderViewAuditSource,
)
from ai_novel_studio.domain.audit import (
    AuditFindingCategory,
    AuditFindingSource,
    AuditSeverity,
)


def _run(
    target_text: str,
    requirement: str = "must: find the letter",
    *,
    chapter_sequence: int = 1,
    reader_view_sources: tuple[ReaderViewAuditSource, ...] = (),
):
    request = DeterministicAuditRequest(
        chapter_id="chapter-1",
        target_text=target_text,
        target_revision=2,
        target_hash="target-hash",
        requirement_content=requirement,
        chapter_sequence=chapter_sequence,
        reader_view_sources=reader_view_sources,
    )
    return DeterministicAuditService().run(request)


def test_empty_target_text_creates_blocker_format_finding() -> None:
    findings = _run("   ")

    assert len(findings) == 1
    assert findings[0].category == AuditFindingCategory.FORMAT
    assert findings[0].severity == AuditSeverity.BLOCKER
    assert findings[0].source == AuditFindingSource.DETERMINISTIC
    assert "empty" in findings[0].explanation.lower()


def test_empty_requirement_creates_blocker_requirement_finding() -> None:
    findings = _run("The protagonist finds the letter.", requirement=" ")

    assert len(findings) == 1
    assert findings[0].category == AuditFindingCategory.REQUIREMENT
    assert findings[0].severity == AuditSeverity.BLOCKER


def test_model_residue_is_reported_as_format_warning() -> None:
    findings = _run("Of course, here is the chapter:\nThe protagonist finds the letter.")

    assert any(
        finding.category == AuditFindingCategory.FORMAT
        and finding.severity == AuditSeverity.WARNING
        and "model residue" in finding.explanation.lower()
        for finding in findings
    )


def test_duplicate_non_trivial_paragraph_is_reported() -> None:
    paragraph = "The old archive smelled of rain and iron. The letter waited there."
    findings = _run(f"{paragraph}\n\n{paragraph}")

    assert any(
        finding.category == AuditFindingCategory.FORMAT
        and finding.severity == AuditSeverity.WARNING
        and "duplicate" in finding.explanation.lower()
        for finding in findings
    )


def test_unbalanced_quote_pair_is_reported() -> None:
    findings = _run('The protagonist whispered, "I found the letter.')

    assert any(
        finding.category == AuditFindingCategory.FORMAT
        and finding.severity == AuditSeverity.WARNING
        and "unbalanced" in finding.explanation.lower()
        for finding in findings
    )


def test_missing_required_requirement_phrase_is_reported() -> None:
    findings = _run(
        "The protagonist searches the empty archive.",
        requirement="must: find the letter",
    )

    assert any(
        finding.category == AuditFindingCategory.REQUIREMENT
        and finding.severity == AuditSeverity.WARNING
        and "find the letter" in finding.evidence
        for finding in findings
    )


def test_required_requirement_phrase_is_not_reported_when_present() -> None:
    findings = _run("The protagonist finds the letter in the archive.")

    assert not any(
        finding.category == AuditFindingCategory.REQUIREMENT
        and "find the letter" in finding.evidence
        for finding in findings
    )


def test_findings_persist_deterministic_evidence_kinds() -> None:
    source_findings = _run("Of course, the protagonist finds the letter.")
    missing_findings = _run(
        "The protagonist searches the archive.", requirement="must: find the letter"
    )
    diagnostic_findings = _run('The protagonist said, "find the letter.')

    assert {
        json.loads(finding.location_json)["evidence_kind"] for finding in source_findings
    } == {"SOURCE_EXCERPT"}
    assert {
        json.loads(finding.location_json)["evidence_kind"] for finding in missing_findings
    } == {"EXPECTED_MISSING"}
    assert {
        json.loads(finding.location_json)["evidence_kind"] for finding in diagnostic_findings
    } == {"DIAGNOSTIC"}


def test_future_reader_view_exact_exposure_has_precise_provenance() -> None:
    target = "The letter is found. The crown is hollow. The crown is hollow."
    findings = _run(
        target,
        reader_view_sources=(
            ReaderViewAuditSource(
                assertion_id="view-1",
                content="  The crown is hollow.  ",
                visible_from_sequence=3,
            ),
        ),
    )

    knowledge = [
        finding
        for finding in findings
        if finding.category == AuditFindingCategory.KNOWLEDGE
    ]
    assert len(knowledge) == 1
    finding = knowledge[0]
    assert finding.severity == AuditSeverity.WARNING
    assert finding.source == AuditFindingSource.DETERMINISTIC
    assert finding.confidence == 1.0
    assert finding.evidence == "The crown is hollow."
    assert json.loads(finding.location_json) == {
        "current_sequence": 1,
        "evidence_kind": "SOURCE_EXCERPT",
        "quote": "The crown is hollow.",
        "start": target.index("The crown is hollow."),
        "visible_from_sequence": 3,
    }
    assert json.loads(finding.related_source_json) == [
        {"id": "view-1", "type": "view_assertion"}
    ]


@pytest.mark.parametrize(
    ("target", "chapter_sequence", "visible_from_sequence"),
    (
        ("The letter is found.", 1, 3),
        ("The Crown Is Hollow.", 1, 3),
        ("The crown only looks hollow.", 1, 3),
        ("The crown is hollow.", 3, 3),
        ("The crown is hollow.", 4, 3),
    ),
)
def test_reader_view_exposure_requires_early_case_sensitive_exact_match(
    target: str,
    chapter_sequence: int,
    visible_from_sequence: int,
) -> None:
    findings = _run(
        target,
        chapter_sequence=chapter_sequence,
        reader_view_sources=(
            ReaderViewAuditSource(
                assertion_id="view-1",
                content="The crown is hollow.",
                visible_from_sequence=visible_from_sequence,
            ),
        ),
    )

    assert not any(
        finding.category == AuditFindingCategory.KNOWLEDGE for finding in findings
    )
