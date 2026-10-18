from __future__ import annotations

from dataclasses import dataclass

from ai_novel_studio.application.formal_manuscript_evidence_service import EvidenceSet
from ai_novel_studio.core.context.context_builder import ContextBlock

EVIDENCE_CATEGORY = "EXACT_EVIDENCE"
EVIDENCE_SOURCE_TYPE = "FORMAL_MANUSCRIPT"


@dataclass(frozen=True, slots=True)
class EvidenceContextOptions:
    """Assembly options for evidence context blocks."""

    priority: int = 50
    required: bool = False


class EvidenceContextAdapter:
    """R3b-Q2 runtime injection: EvidenceSet -> ContextBlock sequence.

    Each exact evidence hit becomes one bounded context block carrying its
    Formal Manuscript provenance, so the existing ContextBuilder records the
    source revision and hash in the manifest. Retrieval routes and diagnostic
    scores stay human-readable in the rationale; structured manifest fields
    for them belong to R4.
    """

    def __init__(self, options: EvidenceContextOptions | None = None) -> None:
        self._options = options or EvidenceContextOptions()

    def to_blocks(self, evidence: EvidenceSet) -> tuple[ContextBlock, ...]:
        if not isinstance(evidence, EvidenceSet):
            raise TypeError("evidence must be an EvidenceSet")
        return tuple(
            ContextBlock(
                id=f"exact-evidence-{hit.document_id}",
                category=EVIDENCE_CATEGORY,
                content=hit.text,
                priority=self._options.priority,
                required=self._options.required,
                source_type=EVIDENCE_SOURCE_TYPE,
                source_id=hit.source_id,
                source_chapter_id=hit.chapter_id,
                source_revision=hit.source_revision,
                source_hash=hit.source_hash,
                rationale=(
                    f"routes={','.join(hit.retrieval_routes)} "
                    f"total_score={hit.total_score:.3f}"
                ),
            )
            for hit in evidence.hits
        )
