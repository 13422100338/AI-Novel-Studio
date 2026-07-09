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


@dataclass(frozen=True, slots=True)
class DeterministicAuditRequest:
    chapter_id: str
    target_text: str
    target_revision: int
    target_hash: str
    requirement_content: str

    def __post_init__(self) -> None:
        if not self.chapter_id.strip():
            raise ValueError("chapter_id cannot be empty")
        if self.target_revision < 0:
            raise ValueError("target_revision cannot be negative")
        if not self.target_hash.strip():
            raise ValueError("target_hash cannot be empty")


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
                    confidence=1.0,
                )
            )

        if text.strip():
            findings.extend(_model_residue_findings(text))
            findings.extend(_duplicate_paragraph_findings(text))
            findings.extend(_unbalanced_pair_findings(text))

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
    related: list[dict[str, str]] | None = None,
    confidence: float,
) -> DeterministicFinding:
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
                related=[{"type": "chapter_requirement", "id": "current"}],
                confidence=0.65,
            )
        )
    return tuple(findings)


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
