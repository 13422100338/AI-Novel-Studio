from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite

from ai_novel_studio.domain.identifiers import validate_id
from ai_novel_studio.infrastructure.storage.search_repository import (
    MAX_FORMAL_EVIDENCE_CANDIDATES,
    MAX_FORMAL_EVIDENCE_HIT_CODEPOINTS,
    MAX_FORMAL_EVIDENCE_NEIGHBOR_RADIUS,
    RetrievalRoute,
    SearchRepository,
)

_MAX_SET_CODEPOINTS = 32_000
_ALLOWED_ROUTES = {"EXACT_PHRASE", "KEYWORD", "EMBEDDING", "SUBJECT"}
_SHA256 = re.compile(r"[0-9a-f]{64}")


class EvidenceOutcome(StrEnum):
    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    INSUFFICIENT = "INSUFFICIENT"


class FormalEvidenceIntegrityError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("formal manuscript evidence cannot be validated")


@dataclass(frozen=True, slots=True)
class FormalEvidenceLimits:
    max_candidates: int = 20
    neighbor_radius: int = 1
    max_codepoints_per_hit: int = 4_800
    max_codepoints_per_set: int = 16_000

    def __post_init__(self) -> None:
        _bounded_integer(
            self.max_candidates,
            "candidate limit",
            maximum=MAX_FORMAL_EVIDENCE_CANDIDATES,
        )
        _bounded_integer(
            self.neighbor_radius,
            "neighbor radius",
            minimum=0,
            maximum=MAX_FORMAL_EVIDENCE_NEIGHBOR_RADIUS,
        )
        _bounded_integer(
            self.max_codepoints_per_hit,
            "per-hit code-point limit",
            maximum=MAX_FORMAL_EVIDENCE_HIT_CODEPOINTS,
        )
        _bounded_integer(
            self.max_codepoints_per_set,
            "set code-point limit",
            maximum=_MAX_SET_CODEPOINTS,
        )
        if self.max_codepoints_per_set < self.max_codepoints_per_hit:
            raise ValueError("formal evidence set limit must cover one hit")


@dataclass(frozen=True, slots=True)
class FormalEvidenceCandidate:
    document_id: str
    retrieval_routes: tuple[RetrievalRoute, ...]
    lexical_score: float = 0.0
    semantic_score: float = 0.0
    participant_boost: float = 0.0
    pinned_weight: float = 0.0
    recency_score: float = 0.0
    stale_penalty: float = 0.0
    total_score: float = 0.0

    def __post_init__(self) -> None:
        _validated_id(self.document_id, "candidate document ID")
        _validated_routes(self.retrieval_routes)
        _validated_diagnostic_scores(self)


@dataclass(frozen=True, slots=True)
class FormalEvidenceHydrationRequest:
    target_chapter_id: str
    candidates: tuple[FormalEvidenceCandidate, ...]
    required_hits: int | None = None

    def __post_init__(self) -> None:
        _validated_id(self.target_chapter_id, "target chapter ID")
        if (
            not isinstance(self.candidates, tuple)
            or any(
                not isinstance(candidate, FormalEvidenceCandidate)
                for candidate in self.candidates
            )
            or len(self.candidates) > MAX_FORMAL_EVIDENCE_CANDIDATES
        ):
            raise ValueError("formal evidence candidates are invalid")
        if self.required_hits is not None:
            _bounded_integer(
                self.required_hits,
                "required hit count",
                maximum=MAX_FORMAL_EVIDENCE_CANDIDATES,
            )


@dataclass(frozen=True, slots=True)
class EvidenceHit:
    document_id: str
    source_id: str
    chapter_id: str
    volume_id: str
    source_revision: int
    source_hash: str
    title: str
    source_start: int
    source_end: int
    text: str
    expanded_document_ids: tuple[str, ...]
    retrieval_routes: tuple[RetrievalRoute, ...]
    lexical_score: float
    semantic_score: float
    participant_boost: float
    pinned_weight: float
    recency_score: float
    stale_penalty: float
    total_score: float

    def __post_init__(self) -> None:
        _validated_id(self.document_id, "hit document ID")
        _validated_id(self.chapter_id, "hit chapter ID")
        _validated_id(self.volume_id, "hit volume ID")
        if (
            not isinstance(self.source_id, str)
            or not self.source_id
            or len(self.source_id) > 500
        ):
            raise ValueError("formal evidence hit source ID is invalid")
        _bounded_integer(
            self.source_revision,
            "hit source revision",
            minimum=0,
            maximum=2_147_483_647,
        )
        if not isinstance(self.source_hash, str) or _SHA256.fullmatch(
            self.source_hash
        ) is None:
            raise ValueError("formal evidence hit source hash is invalid")
        if not isinstance(self.title, str) or not isinstance(self.text, str):
            raise ValueError("formal evidence hit text metadata is invalid")
        source_start = _bounded_integer(
            self.source_start,
            "hit range start",
            minimum=0,
            maximum=2_147_483_647,
        )
        source_end = _bounded_integer(
            self.source_end,
            "hit range end",
            maximum=2_147_483_647,
        )
        if source_end <= source_start or len(self.text) != source_end - source_start:
            raise ValueError("formal evidence hit range is invalid")
        if (
            not isinstance(self.expanded_document_ids, tuple)
            or not self.expanded_document_ids
            or len(self.expanded_document_ids)
            != len(set(self.expanded_document_ids))
        ):
            raise ValueError("formal evidence expanded documents are invalid")
        for document_id in self.expanded_document_ids:
            _validated_id(document_id, "expanded document ID")
        if self.document_id not in self.expanded_document_ids:
            raise ValueError("formal evidence primary document is not expanded")
        _validated_routes(self.retrieval_routes)
        _validated_diagnostic_scores(self)


@dataclass(frozen=True, slots=True)
class EvidenceSet:
    outcome: EvidenceOutcome
    hits: tuple[EvidenceHit, ...]
    total_codepoints: int

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, EvidenceOutcome):
            raise TypeError("formal evidence outcome is invalid")
        if not isinstance(self.hits, tuple) or any(
            not isinstance(hit, EvidenceHit) for hit in self.hits
        ):
            raise TypeError("formal evidence hits are invalid")
        if self.total_codepoints != sum(len(hit.text) for hit in self.hits):
            raise ValueError("formal evidence character count is invalid")
        if (self.outcome == EvidenceOutcome.NOT_FOUND) != (not self.hits):
            raise ValueError("formal evidence outcome does not match hits")


class FormalManuscriptEvidenceService:
    def __init__(
        self,
        repository: SearchRepository,
        *,
        limits: FormalEvidenceLimits | None = None,
    ) -> None:
        if not isinstance(repository, SearchRepository):
            raise TypeError("formal evidence repository is invalid")
        if limits is None:
            limits = FormalEvidenceLimits()
        if not isinstance(limits, FormalEvidenceLimits):
            raise TypeError("formal evidence limits are invalid")
        self.repository = repository
        self.limits = limits

    def hydrate(self, request: FormalEvidenceHydrationRequest) -> EvidenceSet:
        if not isinstance(request, FormalEvidenceHydrationRequest):
            raise TypeError("formal evidence hydration request is invalid")
        if len(request.candidates) > self.limits.max_candidates:
            raise ValueError("formal evidence candidate limit exceeded")
        unique_candidates: list[FormalEvidenceCandidate] = []
        seen_document_ids: set[str] = set()
        for candidate in request.candidates:
            if candidate.document_id not in seen_document_ids:
                unique_candidates.append(candidate)
                seen_document_ids.add(candidate.document_id)
        try:
            projections = self.repository.hydrate_formal_manuscript_candidates(
                request.target_chapter_id,
                tuple(candidate.document_id for candidate in unique_candidates),
                neighbor_radius=self.limits.neighbor_radius,
                max_codepoints_per_hit=self.limits.max_codepoints_per_hit,
            )
        except (
            KeyError,
            OSError,
            RuntimeError,
            UnicodeError,
            ValueError,
            sqlite3.Error,
        ):
            raise FormalEvidenceIntegrityError() from None

        candidates_by_id = {
            candidate.document_id: candidate for candidate in unique_candidates
        }
        hits: list[EvidenceHit] = []
        seen_ranges: set[tuple[str, int, str, int, int]] = set()
        total_codepoints = 0
        for projection in projections:
            candidate = candidates_by_id[projection.document_id]
            range_key = (
                projection.chapter_id,
                projection.source_revision,
                projection.source_hash,
                projection.source_start,
                projection.source_end,
            )
            if range_key in seen_ranges:
                continue
            hit_codepoints = len(projection.text)
            if total_codepoints + hit_codepoints > self.limits.max_codepoints_per_set:
                break
            seen_ranges.add(range_key)
            hits.append(
                EvidenceHit(
                    projection.document_id,
                    projection.source_id,
                    projection.chapter_id,
                    projection.volume_id,
                    projection.source_revision,
                    projection.source_hash,
                    projection.title,
                    projection.source_start,
                    projection.source_end,
                    projection.text,
                    projection.expanded_document_ids,
                    candidate.retrieval_routes,
                    candidate.lexical_score,
                    candidate.semantic_score,
                    candidate.participant_boost,
                    candidate.pinned_weight,
                    candidate.recency_score,
                    candidate.stale_penalty,
                    candidate.total_score,
                )
            )
            total_codepoints += hit_codepoints

        if not hits:
            outcome = EvidenceOutcome.NOT_FOUND
        elif request.required_hits is not None and len(hits) < request.required_hits:
            outcome = EvidenceOutcome.INSUFFICIENT
        else:
            outcome = EvidenceOutcome.FOUND
        return EvidenceSet(outcome, tuple(hits), total_codepoints)


def _validated_id(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"formal evidence {field} is invalid")
    try:
        return validate_id(value)
    except ValueError:
        raise ValueError(f"formal evidence {field} is invalid") from None


def _finite_score(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"formal evidence {field} must be finite")
    score = float(value)
    if not isfinite(score):
        raise ValueError(f"formal evidence {field} must be finite")
    return score


def _validated_routes(routes: object) -> None:
    if (
        not isinstance(routes, tuple)
        or not routes
        or len(routes) != len(set(routes))
        or any(route not in _ALLOWED_ROUTES for route in routes)
    ):
        raise ValueError("formal evidence retrieval routes are invalid")


def _validated_diagnostic_scores(
    value: FormalEvidenceCandidate | EvidenceHit,
) -> None:
    for field, score in (
        ("lexical score", value.lexical_score),
        ("semantic score", value.semantic_score),
        ("participant boost", value.participant_boost),
        ("pinned weight", value.pinned_weight),
        ("recency score", value.recency_score),
        ("stale penalty", value.stale_penalty),
        ("total score", value.total_score),
    ):
        _finite_score(score, field)


def _bounded_integer(
    value: object,
    field: str,
    *,
    minimum: int = 1,
    maximum: int,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise ValueError(f"formal evidence {field} is invalid")
    return value
