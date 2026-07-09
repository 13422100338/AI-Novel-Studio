from ai_novel_studio.application.deterministic_audit_service import (
    DeterministicAuditRequest,
    DeterministicAuditService,
)
from ai_novel_studio.domain.audit import (
    AuditFindingCategory,
    AuditFindingSource,
    AuditSeverity,
)


def _run(target_text: str, requirement: str = "must: find the letter"):
    request = DeterministicAuditRequest(
        chapter_id="chapter-1",
        target_text=target_text,
        target_revision=2,
        target_hash="target-hash",
        requirement_content=requirement,
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
