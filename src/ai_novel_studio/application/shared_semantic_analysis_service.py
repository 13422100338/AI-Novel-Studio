from __future__ import annotations

from typing import cast

from ai_novel_studio.core.context.semantic_windowing import SemanticWindow
from ai_novel_studio.core.context.shared_semantic_result import (
    AliasCandidate,
    OccurrenceCandidate,
    ParticipantLinkCandidate,
    SemanticCandidateKind,
    SharedSemanticResult,
    SourceSpan,
    StateChangeCandidate,
    SubjectMentionCandidate,
    ViewDifferenceCandidate,
    WindowSummaryCandidate,
    candidate_source_id,
)
from ai_novel_studio.domain.view import EpistemicStatus, ViewType
from ai_novel_studio.infrastructure.llm.contract_runner import (
    ContractValidationError,
    JsonField,
    JsonObjectContract,
    LLMContractRunner,
)
from ai_novel_studio.infrastructure.llm.schemas import LLMMessage, TaskPurpose

_MAX_OUTPUT_TOKENS = 200_000
_MAX_TOTAL_CANDIDATES = 1_000
_MAX_SPANS = 32
_MAX_TEXT = 4_000
_MAX_QUOTE = 2_000
_RESULT_KEY = "_validated_shared_semantic_result"
_FIELDS = (
    "subject_mentions",
    "aliases",
    "occurrences",
    "participant_links",
    "state_changes",
    "view_differences",
    "summary",
)
_LIMITS = {
    "subject_mentions": 100,
    "aliases": 100,
    "occurrences": 100,
    "participant_links": 500,
    "state_changes": 100,
    "view_differences": 100,
}
_REQUIRED_FIELDS = {
    "subject_mentions": frozenset({"mention", "spans"}),
    "aliases": frozenset({"alias", "spans"}),
    "occurrences": frozenset(
        {"occurrence_type", "title", "summary", "spans"}
    ),
    "participant_links": frozenset(
        {"subject_mention_ordinal", "role", "subject_summary", "spans"}
    ),
    "state_changes": frozenset(
        {"subject_mention_ordinal", "change_type", "detail", "spans"}
    ),
}
_CONTRACT = JsonObjectContract(
    tuple(JsonField(name, list) for name in _FIELDS if name != "summary")
    + (JsonField("summary", (dict, type(None))),)
)


class SharedSemanticAnalysisService:
    def __init__(
        self,
        runner: LLMContractRunner,
        *,
        output_token_limit: int | None = None,
    ) -> None:
        if output_token_limit is not None and (
            isinstance(output_token_limit, bool)
            or not isinstance(output_token_limit, int)
            or not 1 <= output_token_limit <= _MAX_OUTPUT_TOKENS
        ):
            raise ValueError("semantic analysis output limit is invalid")
        self._runner = runner
        self._output_token_limit = output_token_limit or 6_000

    def extract(self, window: SemanticWindow) -> SharedSemanticResult:
        if not isinstance(window, SemanticWindow):
            raise TypeError("semantic analysis window is invalid")
        if not window.text.strip():
            raise ValueError("semantic analysis window is empty")
        payload = self._runner.run_json(
            TaskPurpose.MEMORY_EXTRACTION,
            self._messages(window),
            self._output_token_limit,
            _CONTRACT,
            lambda value: self._validate(value, window),
        )
        result = payload.get(_RESULT_KEY)
        if not isinstance(result, SharedSemanticResult):
            raise ContractValidationError("semantic analysis result is invalid")
        return result

    @staticmethod
    def _messages(window: SemanticWindow) -> tuple[LLMMessage, ...]:
        return (
            LLMMessage(
                "system",
                "Analyze exactly one semantic window and return JSON only. Formal "
                "Manuscript is authoritative and every candidate remains REVIEW. "
                "Do not guess identity, create or resolve Subjects, or return candidate, "
                "subject, provenance, source, authority, review, score, confidence, or "
                "reverse-child IDs. Use zero-based array ordinals for references and "
                "zero-based half-open local code-point spans. The exact top-level schema "
                "is {subject_mentions,aliases,occurrences,participant_links,state_changes,"
                "view_differences,summary}. Mentions are {mention,spans}; aliases are "
                "{alias,spans}; occurrences are {occurrence_type,title,summary,spans}; "
                "participant links are {subject_mention_ordinal,role,subject_summary,"
                "spans,occurrence_ordinal?}; state changes are "
                "{subject_mention_ordinal,change_type,detail,spans,occurrence_ordinal?}. "
                "A CHARACTER_VIEW is {view_type,observer_mention_ordinal,"
                "target_mention_ordinal,epistemic_status,content,spans,"
                "occurrence_ordinal?}; a READER_VIEW omits observer_mention_ordinal and "
                "epistemic_status. Summary is exactly null or {content,spans}; each span "
                "is exactly {start,end}. Represent one shared event once and attach many "
                "participant links. State means a real change; View means only a sparse "
                "epistemic difference, never an ordinary participation matrix.",
            ),
            LLMMessage(
                "user",
                f"window_id={window.source_id}\n"
                f"window_ordinal={window.window_ordinal}\n"
                f"narrative_sequence={window.narrative_sequence}\n"
                f"source_range=[{window.source_start},{window.source_end})\n"
                f"<window_text>\n{window.text}\n</window_text>",
            ),
        )

    @classmethod
    def _validate(
        cls,
        payload: dict[str, object],
        window: SemanticWindow,
    ) -> dict[str, object]:
        try:
            if set(payload) != set(_FIELDS):
                raise ValueError
            total = 0
            for field, limit in _LIMITS.items():
                values = payload[field]
                if not isinstance(values, list) or len(values) > limit:
                    raise ValueError
                total += len(values)
            summary = payload["summary"]
            total += 1 if summary is not None else 0
            if total > _MAX_TOTAL_CANDIDATES:
                raise ValueError
            for field in _LIMITS:
                values = cast(list[object], payload[field])
                for value in values:
                    cls._validate_item(field, value, window)
            if summary is not None:
                cls._validate_item("summary", summary, window)
            result = cls._build(payload, window)
        except (KeyError, TypeError, ValueError):
            raise ContractValidationError(
                "semantic analysis model output is invalid"
            ) from None
        return {_RESULT_KEY: result}

    @classmethod
    def _validate_item(
        cls,
        field: str,
        value: object,
        window: SemanticWindow,
    ) -> None:
        item = cls._item(value)
        if field == "view_differences":
            view_type = item.get("view_type")
            if view_type == ViewType.CHARACTER_VIEW.value:
                required = frozenset(
                    {
                        "view_type",
                        "observer_mention_ordinal",
                        "target_mention_ordinal",
                        "epistemic_status",
                        "content",
                        "spans",
                    }
                )
            elif view_type == ViewType.READER_VIEW.value:
                required = frozenset(
                    {
                        "view_type",
                        "target_mention_ordinal",
                        "content",
                        "spans",
                    }
                )
            else:
                raise ValueError
            cls._require_exact_fields(item, required, optional_occurrence=True)
        elif field == "summary":
            cls._require_exact_fields(
                item,
                frozenset({"content", "spans"}),
                optional_occurrence=False,
            )
        else:
            cls._require_exact_fields(
                item,
                _REQUIRED_FIELDS[field],
                optional_occurrence=field
                in {"participant_links", "state_changes"},
            )
        for name, item_value in item.items():
            if name == "spans":
                cls._validate_span_input(item_value, window)
            elif name.endswith("_ordinal"):
                if (
                    isinstance(item_value, bool)
                    or not isinstance(item_value, int)
                    or item_value < 0
                ):
                    raise ValueError
            elif name in {"view_type", "epistemic_status"}:
                if not isinstance(item_value, str):
                    raise ValueError
            elif (
                not isinstance(item_value, str)
                or not item_value.strip()
                or len(item_value) > _MAX_TEXT
            ):
                raise ValueError

    @staticmethod
    def _require_exact_fields(
        item: dict[str, object],
        required: frozenset[str],
        *,
        optional_occurrence: bool,
    ) -> None:
        actual = frozenset(item)
        if actual == required:
            return
        if optional_occurrence and actual == required | {"occurrence_ordinal"}:
            return
        raise ValueError

    @staticmethod
    def _validate_span_input(value: object, window: SemanticWindow) -> None:
        if not isinstance(value, list) or not 1 <= len(value) <= _MAX_SPANS:
            raise ValueError
        for raw in value:
            item = SharedSemanticAnalysisService._item(raw)
            if set(item) != {"start", "end"}:
                raise ValueError
            start = item["start"]
            end = item["end"]
            if (
                isinstance(start, bool)
                or isinstance(end, bool)
                or not isinstance(start, int)
                or not isinstance(end, int)
                or start < 0
                or end <= start
                or end > len(window.text)
                or end - start > _MAX_QUOTE
            ):
                raise ValueError

    @staticmethod
    def _item(value: object) -> dict[str, object]:
        if not isinstance(value, dict):
            raise ValueError
        return cast(dict[str, object], value)

    @staticmethod
    def _text(item: dict[str, object], field: str) -> str:
        value = item[field]
        if not isinstance(value, str):
            raise ValueError
        return value

    @staticmethod
    def _spans(value: object, window: SemanticWindow) -> tuple[SourceSpan, ...]:
        if not isinstance(value, list):
            raise ValueError
        spans: list[SourceSpan] = []
        for raw in value:
            item = SharedSemanticAnalysisService._item(raw)
            start = item["start"]
            end = item["end"]
            if not isinstance(start, int) or not isinstance(end, int):
                raise ValueError
            spans.append(SourceSpan(start, end, window.text[start:end]))
        return tuple(spans)

    @staticmethod
    def _ordinal(
        item: dict[str, object],
        field: str,
        size: int,
        *,
        required: bool,
    ) -> int | None:
        if field not in item:
            if required:
                raise ValueError
            return None
        value = item[field]
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value < size
        ):
            raise ValueError
        return value

    @classmethod
    def _reference(
        cls,
        item: dict[str, object],
        field: str,
        ids: tuple[str, ...],
        *,
        required: bool,
    ) -> str | None:
        ordinal = cls._ordinal(item, field, len(ids), required=required)
        return None if ordinal is None else ids[ordinal]

    @classmethod
    def _build(
        cls,
        payload: dict[str, object],
        window: SemanticWindow,
    ) -> SharedSemanticResult:
        mention_values = cast(list[object], payload["subject_mentions"])
        mentions = tuple(
            SubjectMentionCandidate(
                candidate_id=candidate_source_id(
                    window, SemanticCandidateKind.SUBJECT_MENTION, index
                ),
                mention=cls._text(item, "mention"),
                spans=cls._spans(item["spans"], window),
            )
            for index, raw in enumerate(mention_values)
            for item in (cls._item(raw),)
        )
        mention_ids = tuple(item.candidate_id for item in mentions)

        alias_values = cast(list[object], payload["aliases"])
        aliases = tuple(
            AliasCandidate(
                candidate_id=candidate_source_id(
                    window, SemanticCandidateKind.ALIAS, index
                ),
                alias=cls._text(item, "alias"),
                spans=cls._spans(item["spans"], window),
            )
            for index, raw in enumerate(alias_values)
            for item in (cls._item(raw),)
        )

        occurrence_values = cast(list[object], payload["occurrences"])
        occurrences = tuple(
            OccurrenceCandidate(
                candidate_id=candidate_source_id(
                    window, SemanticCandidateKind.OCCURRENCE, index
                ),
                occurrence_type=cls._text(item, "occurrence_type"),
                title=cls._text(item, "title"),
                summary=cls._text(item, "summary"),
                spans=cls._spans(item["spans"], window),
            )
            for index, raw in enumerate(occurrence_values)
            for item in (cls._item(raw),)
        )
        occurrence_ids = tuple(item.candidate_id for item in occurrences)

        link_values = cast(list[object], payload["participant_links"])
        links = tuple(
            cls._build_link(
                raw, window, mention_ids, occurrence_ids, index
            )
            for index, raw in enumerate(link_values)
        )
        state_values = cast(list[object], payload["state_changes"])
        states = tuple(
            cls._build_state(
                raw, window, mention_ids, occurrence_ids, index
            )
            for index, raw in enumerate(state_values)
        )
        view_values = cast(list[object], payload["view_differences"])
        views = tuple(
            cls._build_view(
                raw, window, mention_ids, occurrence_ids, index
            )
            for index, raw in enumerate(view_values)
        )
        summary_raw = payload["summary"]
        return SharedSemanticResult(
            window=window,
            subject_mentions=mentions,
            aliases=aliases,
            occurrences=occurrences,
            participant_links=links,
            state_changes=states,
            view_differences=views,
            summary=(
                None
                if summary_raw is None
                else cls._build_summary(summary_raw, window)
            ),
        )

    @classmethod
    def _build_link(
        cls,
        raw: object,
        window: SemanticWindow,
        mention_ids: tuple[str, ...],
        occurrence_ids: tuple[str, ...],
        index: int,
    ) -> ParticipantLinkCandidate:
        item = cls._item(raw)
        mention = cls._reference(
            item,
            "subject_mention_ordinal",
            mention_ids,
            required=True,
        )
        if mention is None:
            raise ValueError
        return ParticipantLinkCandidate(
            candidate_id=candidate_source_id(
                window, SemanticCandidateKind.PARTICIPANT_LINK, index
            ),
            subject=None,
            role=cls._text(item, "role"),
            subject_summary=cls._text(item, "subject_summary"),
            spans=cls._spans(item["spans"], window),
            occurrence_candidate_id=cls._reference(
                item,
                "occurrence_ordinal",
                occurrence_ids,
                required=False,
            ),
            subject_mention_candidate_id=mention,
        )

    @classmethod
    def _build_state(
        cls,
        raw: object,
        window: SemanticWindow,
        mention_ids: tuple[str, ...],
        occurrence_ids: tuple[str, ...],
        index: int,
    ) -> StateChangeCandidate:
        item = cls._item(raw)
        mention = cls._reference(
            item,
            "subject_mention_ordinal",
            mention_ids,
            required=True,
        )
        if mention is None:
            raise ValueError
        return StateChangeCandidate(
            candidate_id=candidate_source_id(
                window, SemanticCandidateKind.STATE_CHANGE, index
            ),
            subject=None,
            change_type=cls._text(item, "change_type"),
            detail=cls._text(item, "detail"),
            spans=cls._spans(item["spans"], window),
            occurrence_candidate_id=cls._reference(
                item,
                "occurrence_ordinal",
                occurrence_ids,
                required=False,
            ),
            subject_mention_candidate_id=mention,
        )

    @classmethod
    def _build_view(
        cls,
        raw: object,
        window: SemanticWindow,
        mention_ids: tuple[str, ...],
        occurrence_ids: tuple[str, ...],
        index: int,
    ) -> ViewDifferenceCandidate:
        item = cls._item(raw)
        view_type = ViewType(cls._text(item, "view_type"))
        target = cls._reference(
            item,
            "target_mention_ordinal",
            mention_ids,
            required=True,
        )
        if target is None:
            raise ValueError
        observer = cls._reference(
            item,
            "observer_mention_ordinal",
            mention_ids,
            required=view_type is ViewType.CHARACTER_VIEW,
        )
        status = (
            EpistemicStatus(cls._text(item, "epistemic_status"))
            if view_type is ViewType.CHARACTER_VIEW
            else None
        )
        return ViewDifferenceCandidate(
            candidate_id=candidate_source_id(
                window, SemanticCandidateKind.VIEW_DIFFERENCE, index
            ),
            view_type=view_type,
            observer=None,
            target=None,
            epistemic_status=status,
            content=cls._text(item, "content"),
            spans=cls._spans(item["spans"], window),
            occurrence_candidate_id=cls._reference(
                item,
                "occurrence_ordinal",
                occurrence_ids,
                required=False,
            ),
            observer_mention_candidate_id=observer,
            target_mention_candidate_id=target,
        )

    @classmethod
    def _build_summary(
        cls,
        raw: object,
        window: SemanticWindow,
    ) -> WindowSummaryCandidate:
        item = cls._item(raw)
        return WindowSummaryCandidate(
            candidate_id=candidate_source_id(
                window, SemanticCandidateKind.WINDOW_SUMMARY, 0
            ),
            content=cls._text(item, "content"),
            spans=cls._spans(item["spans"], window),
        )
