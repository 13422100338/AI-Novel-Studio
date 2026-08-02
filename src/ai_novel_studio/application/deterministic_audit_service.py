from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass

from ai_novel_studio.domain.audit import (
    AuditFindingCategory,
    AuditFindingSource,
    AuditSeverity,
)

_MODEL_RESIDUE_PATTERNS = (
    re.compile(r"\bof course\b", re.IGNORECASE),
    re.compile(r"\bhere is (the|your) chapter\b", re.IGNORECASE),
    re.compile(r"\bas an ai\b", re.IGNORECASE),
    re.compile(r"^下面是", re.MULTILINE),
    re.compile(r"^当然可以", re.MULTILINE),
)

_REQUIRED_PREFIXES = (
    "must:",
    "must：",
    "必须:",
    "必须：",
    "需要:",
    "需要：",
    "硬性:",
    "硬性：",
)

_QUOTE_PAIRS = (
    ('"', '"'),
    ("“", "”"),
    ("‘", "’"),
    ("「", "」"),
    ("『", "』"),
    ("（", "）"),
    ("(", ")"),
)

_SOURCE_EXCERPT = "SOURCE_EXCERPT"
_EXPECTED_MISSING = "EXPECTED_MISSING"
_DIAGNOSTIC = "DIAGNOSTIC"


def _normalize_conflict_values(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value.strip() for value in values if value.strip()))


def _normalize_event_ids(event_ids: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(sorted({event_id.strip() for event_id in event_ids if event_id.strip()}))


@dataclass(frozen=True, slots=True)
class ReaderViewAuditSource:
    assertion_id: str
    content: str
    visible_from_sequence: int

    def __post_init__(self) -> None:
        assertion_id = self.assertion_id.strip()
        content = self.content.strip()
        if not assertion_id:
            raise ValueError("assertion_id cannot be empty")
        if not content:
            raise ValueError("content cannot be empty")
        if self.visible_from_sequence < 0:
            raise ValueError("visible_from_sequence cannot be negative")
        object.__setattr__(self, "assertion_id", assertion_id)
        object.__setattr__(self, "content", content)


@dataclass(frozen=True, slots=True)
class CharacterLocationConflictAuditSource:
    character_id: str
    source_boundary_chapter_id: str
    locations: tuple[str, ...]
    state_event_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        character_id = self.character_id.strip()
        source_boundary_chapter_id = self.source_boundary_chapter_id.strip()
        if not character_id:
            raise ValueError("character_id cannot be empty")
        if not source_boundary_chapter_id:
            raise ValueError("source_boundary_chapter_id cannot be empty")
        locations = _normalize_conflict_values(self.locations)
        state_event_ids = _normalize_event_ids(self.state_event_ids)
        if not state_event_ids:
            raise ValueError("state_event_ids cannot be empty")
        object.__setattr__(self, "character_id", character_id)
        object.__setattr__(
            self,
            "source_boundary_chapter_id",
            source_boundary_chapter_id,
        )
        object.__setattr__(self, "locations", locations)
        object.__setattr__(self, "state_event_ids", state_event_ids)


@dataclass(frozen=True, slots=True)
class CharacterInjuryConflictAuditSource:
    character_id: str
    source_boundary_chapter_id: str
    injury_statuses: tuple[str, ...]
    state_event_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        character_id = self.character_id.strip()
        source_boundary_chapter_id = self.source_boundary_chapter_id.strip()
        if not character_id:
            raise ValueError("character_id cannot be empty")
        if not source_boundary_chapter_id:
            raise ValueError("source_boundary_chapter_id cannot be empty")
        injury_statuses = _normalize_conflict_values(self.injury_statuses)
        state_event_ids = _normalize_event_ids(self.state_event_ids)
        if not state_event_ids:
            raise ValueError("state_event_ids cannot be empty")
        object.__setattr__(self, "character_id", character_id)
        object.__setattr__(
            self,
            "source_boundary_chapter_id",
            source_boundary_chapter_id,
        )
        object.__setattr__(self, "injury_statuses", injury_statuses)
        object.__setattr__(self, "state_event_ids", state_event_ids)


@dataclass(frozen=True, slots=True)
class DeterministicAuditRequest:
    chapter_id: str
    target_text: str
    target_revision: int
    target_hash: str
    requirement_content: str
    chapter_sequence: int = 0
    reader_view_sources: tuple[ReaderViewAuditSource, ...] = ()
    character_location_conflict_sources: tuple[
        CharacterLocationConflictAuditSource, ...
    ] = ()
    character_injury_conflict_sources: tuple[
        CharacterInjuryConflictAuditSource, ...
    ] = ()

    def __post_init__(self) -> None:
        if not self.chapter_id.strip():
            raise ValueError("chapter_id cannot be empty")
        if self.target_revision < 0:
            raise ValueError("target_revision cannot be negative")
        if not self.target_hash.strip():
            raise ValueError("target_hash cannot be empty")
        if self.chapter_sequence < 0:
            raise ValueError("chapter_sequence cannot be negative")


@dataclass(frozen=True, slots=True)
class DeterministicFinding:
    category: AuditFindingCategory
    severity: AuditSeverity
    source: AuditFindingSource
    location_json: str
    evidence: str
    explanation: str
    related_source_json: str
    confidence: float

    def __post_init__(self) -> None:
        if self.confidence < 0 or self.confidence > 1:
            raise ValueError("confidence must be between 0 and 1")


class DeterministicAuditService:
    def run(self, request: DeterministicAuditRequest) -> tuple[DeterministicFinding, ...]:
        findings: list[DeterministicFinding] = []
        text = request.target_text
        requirement = request.requirement_content

        if not text.strip():
            findings.append(
                _finding(
                    AuditFindingCategory.FORMAT,
                    AuditSeverity.BLOCKER,
                    "target text is empty",
                    "The audited chapter text is empty.",
                    location={"scope": "target_text"},
                    evidence_kind=_DIAGNOSTIC,
                    confidence=1.0,
                )
            )

        if not requirement.strip():
            findings.append(
                _finding(
                    AuditFindingCategory.REQUIREMENT,
                    AuditSeverity.BLOCKER,
                    "current chapter requirement is empty",
                    "The audit cannot check chapter intent without a current chapter requirement.",
                    location={"scope": "requirement"},
                    evidence_kind=_DIAGNOSTIC,
                    confidence=1.0,
                )
            )

        if text.strip():
            findings.extend(_model_residue_findings(text))
            findings.extend(_duplicate_paragraph_findings(text))
            findings.extend(_unbalanced_pair_findings(text))
            findings.extend(
                _premature_reader_view_exposure_findings(
                    text,
                    chapter_sequence=request.chapter_sequence,
                    sources=request.reader_view_sources,
                )
            )
            findings.extend(
                _contested_character_location_findings(
                    text,
                    sources=request.character_location_conflict_sources,
                )
            )
            findings.extend(
                _contested_character_injury_status_findings(
                    text,
                    sources=request.character_injury_conflict_sources,
                )
            )

        if text.strip() and requirement.strip():
            findings.extend(_missing_required_phrase_findings(text, requirement))

        return tuple(findings)


def _finding(
    category: AuditFindingCategory,
    severity: AuditSeverity,
    evidence: str,
    explanation: str,
    *,
    location: dict[str, object],
    evidence_kind: str,
    related: list[dict[str, str]] | None = None,
    confidence: float,
) -> DeterministicFinding:
    location = {**location, "evidence_kind": evidence_kind}
    return DeterministicFinding(
        category=category,
        severity=severity,
        source=AuditFindingSource.DETERMINISTIC,
        location_json=json.dumps(location, ensure_ascii=False, sort_keys=True),
        evidence=evidence,
        explanation=explanation,
        related_source_json=json.dumps(related or [], ensure_ascii=False, sort_keys=True),
        confidence=confidence,
    )


def _model_residue_findings(text: str) -> tuple[DeterministicFinding, ...]:
    findings: list[DeterministicFinding] = []
    for pattern in _MODEL_RESIDUE_PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue
        findings.append(
            _finding(
                AuditFindingCategory.FORMAT,
                AuditSeverity.WARNING,
                match.group(0),
                "Possible model residue found in chapter text.",
                location={"quote": match.group(0), "start": match.start()},
                evidence_kind=_SOURCE_EXCERPT,
                confidence=0.95,
            )
        )
        break
    return tuple(findings)


def _duplicate_paragraph_findings(text: str) -> tuple[DeterministicFinding, ...]:
    paragraphs = [_normalize_space(part) for part in re.split(r"\n\s*\n", text)]
    candidates = [part for part in paragraphs if len(part) >= 40]
    counts = Counter(candidates)
    findings: list[DeterministicFinding] = []
    for paragraph, count in counts.items():
        if count < 2:
            continue
        findings.append(
            _finding(
                AuditFindingCategory.FORMAT,
                AuditSeverity.WARNING,
                paragraph,
                "Duplicate non-trivial paragraph detected.",
                location={"quote": paragraph[:120], "count": count},
                evidence_kind=_SOURCE_EXCERPT,
                confidence=1.0,
            )
        )
    return tuple(findings)


def _unbalanced_pair_findings(text: str) -> tuple[DeterministicFinding, ...]:
    findings: list[DeterministicFinding] = []
    for opener, closer in _QUOTE_PAIRS:
        if opener == closer:
            if text.count(opener) % 2 != 0:
                findings.append(
                    _finding(
                        AuditFindingCategory.FORMAT,
                        AuditSeverity.WARNING,
                        opener,
                        f"Unbalanced punctuation pair detected: {opener}{closer}",
                        location={"punctuation": opener},
                        evidence_kind=_DIAGNOSTIC,
                        confidence=0.9,
                    )
                )
            continue
        if text.count(opener) != text.count(closer):
            findings.append(
                _finding(
                    AuditFindingCategory.FORMAT,
                    AuditSeverity.WARNING,
                    f"{opener}{closer}",
                    f"Unbalanced punctuation pair detected: {opener}{closer}",
                    location={"punctuation": f"{opener}{closer}"},
                    evidence_kind=_DIAGNOSTIC,
                    confidence=0.9,
                )
            )
    return tuple(findings)


def _missing_required_phrase_findings(
    text: str, requirement: str
) -> tuple[DeterministicFinding, ...]:
    normalized_text = _normalize_for_match(text)
    findings: list[DeterministicFinding] = []
    for phrase in _required_phrases(requirement):
        if _normalize_for_match(phrase) in normalized_text:
            continue
        findings.append(
            _finding(
                AuditFindingCategory.REQUIREMENT,
                AuditSeverity.WARNING,
                phrase,
                "Required requirement phrase was not found by deterministic coarse match.",
                location={"scope": "requirement", "phrase": phrase},
                evidence_kind=_EXPECTED_MISSING,
                related=[{"type": "chapter_requirement", "id": "current"}],
                confidence=0.65,
            )
        )
    return tuple(findings)


def _premature_reader_view_exposure_findings(
    text: str,
    *,
    chapter_sequence: int,
    sources: tuple[ReaderViewAuditSource, ...],
) -> tuple[DeterministicFinding, ...]:
    findings: list[DeterministicFinding] = []
    for source in sources:
        if source.visible_from_sequence <= chapter_sequence:
            continue
        start = text.find(source.content)
        if start < 0:
            continue
        findings.append(
            _finding(
                AuditFindingCategory.KNOWLEDGE,
                AuditSeverity.WARNING,
                source.content,
                "Approved Reader View content appears before its narrative visibility sequence.",
                location={
                    "quote": source.content,
                    "start": start,
                    "current_sequence": chapter_sequence,
                    "visible_from_sequence": source.visible_from_sequence,
                },
                evidence_kind=_SOURCE_EXCERPT,
                related=[{"type": "view_assertion", "id": source.assertion_id}],
                confidence=1.0,
            )
        )
    return tuple(findings)


def _contested_character_location_findings(
    text: str,
    *,
    sources: tuple[CharacterLocationConflictAuditSource, ...],
) -> tuple[DeterministicFinding, ...]:
    findings: list[DeterministicFinding] = []
    matched_character_ids: set[str] = set()
    for source in sources:
        if source.character_id in matched_character_ids:
            continue
        finding = _character_state_conflict_finding(
            text,
            character_id=source.character_id,
            source_boundary_chapter_id=source.source_boundary_chapter_id,
            state_field="location",
            values=source.locations,
            state_event_ids=source.state_event_ids,
            category=AuditFindingCategory.TIMELINE,
            explanation=(
                "The audited text uses one location branch from an unresolved "
                "same-boundary Character State conflict."
            ),
        )
        if finding is None:
            continue
        findings.append(finding)
        matched_character_ids.add(source.character_id)
    return tuple(findings)


def _contested_character_injury_status_findings(
    text: str,
    *,
    sources: tuple[CharacterInjuryConflictAuditSource, ...],
) -> tuple[DeterministicFinding, ...]:
    findings: list[DeterministicFinding] = []
    matched_character_ids: set[str] = set()
    for source in sources:
        if source.character_id in matched_character_ids:
            continue
        finding = _character_state_conflict_finding(
            text,
            character_id=source.character_id,
            source_boundary_chapter_id=source.source_boundary_chapter_id,
            state_field="injury_status",
            values=source.injury_statuses,
            state_event_ids=source.state_event_ids,
            category=AuditFindingCategory.CHARACTER,
            explanation=(
                "The audited text uses one injury-status branch from an unresolved "
                "same-boundary Character State conflict."
            ),
        )
        if finding is None:
            continue
        findings.append(finding)
        matched_character_ids.add(source.character_id)
    return tuple(findings)


def _character_state_conflict_finding(
    text: str,
    *,
    character_id: str,
    source_boundary_chapter_id: str,
    state_field: str,
    values: tuple[str, ...],
    state_event_ids: tuple[str, ...],
    category: AuditFindingCategory,
    explanation: str,
) -> DeterministicFinding | None:
    if len(values) < 2:
        return None
    matches = (
        (start, value)
        for value in values
        if (start := text.find(value)) >= 0
    )
    match = min(matches, default=None)
    if match is None:
        return None
    start, quote = match
    return _finding(
        category,
        AuditSeverity.WARNING,
        quote,
        explanation,
        location={
            "quote": quote,
            "start": start,
            "character_id": character_id,
            "state_field": state_field,
            "source_boundary_chapter_id": source_boundary_chapter_id,
        },
        evidence_kind=_SOURCE_EXCERPT,
        related=[
            {"type": "character_state_event", "id": event_id}
            for event_id in sorted(state_event_ids)
        ],
        confidence=1.0,
    )


def _required_phrases(requirement: str) -> tuple[str, ...]:
    phrases: list[str] = []
    for raw_line in requirement.splitlines():
        line = raw_line.strip().lstrip("-*0123456789.、 ")
        lowered = line.lower()
        for prefix in _REQUIRED_PREFIXES:
            if lowered.startswith(prefix.lower()):
                phrase = line[len(prefix):].strip()
                if phrase:
                    phrases.append(phrase)
                break
    return tuple(dict.fromkeys(phrases))


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _normalize_for_match(value: str) -> str:
    words = re.findall(r"\w+", value.lower())
    return " ".join(_simple_stem(word) for word in words)


def _simple_stem(word: str) -> str:
    if len(word) > 4 and word.endswith("s"):
        return word[:-1]
    return word
