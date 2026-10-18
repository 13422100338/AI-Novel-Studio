"""Read-only character-cognition projection (QP-3B).

Exposes only currently-visible APPROVED/LOCKED View assertions through the
canonical :class:`ViewAssertionService` context path — the same hard filter
the Context Compiler uses. Character/reader rows are merged deterministically,
content is truncated, and the projection performs zero writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ai_novel_studio.application.view_assertion_service import (
    ViewAssertionService,
)
from ai_novel_studio.domain.view import ViewType
from ai_novel_studio.infrastructure.storage.project_repository import (
    ProjectRepository,
)
from ai_novel_studio.infrastructure.storage.subject_repository import (
    SubjectRepository,
)

_MAX_CONTENT_CODEPOINTS = 300
_MAX_ROWS = 200


@dataclass(frozen=True, slots=True)
class CognitionRow:
    assertion_id: str
    view_type: str
    target_subject_id: str
    target_name: str
    viewer_subject_id: str | None
    viewer_name: str | None
    epistemic_status: str | None
    content: str
    content_truncated: bool


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit], True


class CharacterViewReadService:
    def __init__(self, project: ProjectRepository) -> None:
        self._project = project
        self._views = ViewAssertionService(project)

    def views_for(
        self,
        *,
        viewer_subject_id: str | None,
        narrative_sequence: int,
        include_reader: bool = True,
        limit: int = 200,
    ) -> tuple[CognitionRow, ...]:
        if viewer_subject_id is not None and not (
            isinstance(viewer_subject_id, str) and viewer_subject_id.strip()
        ):
            raise ValueError("unknown or inactive viewer subject")
        if (
            isinstance(narrative_sequence, bool)
            or not isinstance(narrative_sequence, int)
            or narrative_sequence < 0
        ):
            raise ValueError("narrative sequence must be a non-negative integer")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= _MAX_ROWS
        ):
            raise ValueError("cognition row limit is invalid")
        subjects = SubjectRepository(self._project)
        # SQL-level bound with a SHARED remaining budget (RC-4 follow-up):
        # character rows are fetched first; reader rows get only the
        # remaining allowance so the merged output never exceeds `limit`.
        assertions: list[Any] = []
        try:
            if viewer_subject_id is not None:
                assertions.extend(
                    self._views.list_for_context(
                        narrative_sequence=narrative_sequence,
                        view_type=ViewType.CHARACTER_VIEW,
                        viewer_subject_id=viewer_subject_id,
                        limit=limit,
                    )
                )
            if include_reader:
                remaining = limit - len(assertions)
                if remaining > 0:
                    assertions.extend(
                        self._views.list_for_context(
                            narrative_sequence=narrative_sequence,
                            view_type=ViewType.READER_VIEW,
                            limit=remaining,
                        )
                    )
        except KeyError as error:
            raise ValueError(str(error)) from None

        name_cache: dict[str, str] = {}

        def display_name(subject_id: str) -> str:
            if subject_id not in name_cache:
                try:
                    name_cache[subject_id] = subjects.get(subject_id).canonical_name
                except KeyError:
                    name_cache[subject_id] = subject_id
            return name_cache[subject_id]

        rows: list[CognitionRow] = []
        for assertion in assertions:
            content, truncated = _truncate(
                assertion.content, _MAX_CONTENT_CODEPOINTS
            )
            rows.append(
                CognitionRow(
                    assertion_id=assertion.id,
                    view_type=assertion.view_type.value,
                    target_subject_id=assertion.subject_id,
                    target_name=display_name(assertion.subject_id),
                    viewer_subject_id=assertion.viewer_subject_id,
                    viewer_name=(
                        display_name(assertion.viewer_subject_id)
                        if assertion.viewer_subject_id is not None
                        else None
                    ),
                    epistemic_status=(
                        assertion.epistemic_status.value
                        if assertion.epistemic_status is not None
                        else None
                    ),
                    content=content,
                    content_truncated=truncated,
                )
            )
        rows.sort(key=lambda row: (row.view_type, row.assertion_id))
        return tuple(rows)
