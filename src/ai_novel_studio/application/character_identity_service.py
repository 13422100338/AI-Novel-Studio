from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from itertools import combinations

from ai_novel_studio.domain.agent import AgentToolName
from ai_novel_studio.domain.character_identity import (
    CharacterIdentityMerge,
    CharacterIdentityReviewDecision,
    CharacterIdentityReviewDecisionType,
)
from ai_novel_studio.domain.memory import Character, CharacterStateEvent
from ai_novel_studio.infrastructure.storage.agent_repository import AgentRepository
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.character_identity_repository import (
    CharacterIdentityRepository,
    CharacterIdentityRepositoryError,
)
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.infrastructure.storage.subject_repository import SubjectRepository


class CharacterIdentityError(RuntimeError):
    pass


class CharacterIdentityCandidateOrigin(StrEnum):
    DETERMINISTIC = "DETERMINISTIC"
    AGENT_PROPOSAL = "AGENT_PROPOSAL"


@dataclass(frozen=True, slots=True)
class CharacterStateEvidence:
    chapter_id: str
    chapter_title: str
    summary: str


@dataclass(frozen=True, slots=True)
class CharacterIdentityCardSnapshot:
    character: Character
    state_count: int
    evidence: tuple[CharacterStateEvidence, ...]


@dataclass(frozen=True, slots=True)
class CharacterIdentityReviewCandidate:
    left: CharacterIdentityCardSnapshot
    right: CharacterIdentityCardSnapshot
    reason: str
    recommended_character_id: str
    origin: CharacterIdentityCandidateOrigin = CharacterIdentityCandidateOrigin.DETERMINISTIC
    proposal_id: str | None = None


@dataclass(frozen=True, slots=True)
class RecentCharacterIdentityMerge:
    merge: CharacterIdentityMerge
    source_name: str
    target_name: str


@dataclass(frozen=True, slots=True)
class ExcludedCharacterIdentityCandidate:
    decision: CharacterIdentityReviewDecision
    left_name: str
    right_name: str


class CharacterIdentityService:
    """Applies only explicit, user-confirmed character identity decisions."""

    def __init__(self, project: ProjectRepository) -> None:
        self.project = project
        self.repository = CharacterIdentityRepository(project)
        self.memory_repository = CharacterMemoryRepository(project)
        self.agent_repository = AgentRepository(project)
        self.subject_repository = SubjectRepository(project)

    def merge(
        self,
        source_character_id: str,
        target_character_id: str,
        *,
        reason: str,
        confirmed_by_user: bool,
    ) -> CharacterIdentityMerge:
        if not confirmed_by_user:
            raise PermissionError("人物归并必须由用户明确确认")
        if source_character_id == target_character_id:
            raise CharacterIdentityError("不能把同一张人物卡归并到自身")
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise CharacterIdentityError("人物归并原因不能为空")
        try:
            return self.repository.apply_merge(
                source_character_id,
                target_character_id,
                reason=normalized_reason,
            )
        except (KeyError, CharacterIdentityRepositoryError) as error:
            raise CharacterIdentityError(str(error)) from error

    def undo(self, merge_id: str, *, confirmed_by_user: bool) -> CharacterIdentityMerge:
        if not confirmed_by_user:
            raise PermissionError("撤销人物归并必须由用户明确确认")
        try:
            return self.repository.reverse_merge(merge_id)
        except (KeyError, CharacterIdentityRepositoryError) as error:
            raise CharacterIdentityError(str(error)) from error

    def list_review_candidates(self) -> tuple[CharacterIdentityReviewCandidate, ...]:
        characters = self.memory_repository.list_characters()
        histories = self.memory_repository.state_histories(
            tuple(character.id for character in characters)
        )
        chapter_titles = {
            chapter.id: chapter.title
            for chapter in ChapterRepository(self.project).list_chapters()
        }
        snapshots = {
            character.id: self._snapshot(
                character,
                histories.get(character.id, ()),
                chapter_titles,
            )
            for character in characters
        }
        excluded_pairs = {
            frozenset((decision.first_character_id, decision.second_character_id))
            for decision in self.repository.list_active_review_decisions()
        }
        candidates = [
            candidate
            for candidate in self._agent_review_candidates(characters, snapshots)
            if frozenset(
                (candidate.left.character.id, candidate.right.character.id)
            ) not in excluded_pairs
        ]
        seen_pairs = {
            frozenset((candidate.left.character.id, candidate.right.character.id))
            for candidate in candidates
        }
        for left, right in combinations(characters, 2):
            pair = frozenset((left.id, right.id))
            if pair in seen_pairs or pair in excluded_pairs:
                continue
            reason = self._name_relation(left, right)
            if reason is None:
                continue
            candidates.append(
                CharacterIdentityReviewCandidate(
                    left=snapshots[left.id],
                    right=snapshots[right.id],
                    reason=reason,
                    recommended_character_id=self._recommended_character_id(left, right),
                )
            )
            seen_pairs.add(pair)
        return tuple(candidates)

    def decide_review_candidate(
        self,
        first_character_id: str,
        second_character_id: str,
        decision: CharacterIdentityReviewDecisionType,
        *,
        confirmed_by_user: bool,
        reason: str = "",
    ) -> CharacterIdentityReviewDecision:
        if not confirmed_by_user:
            raise PermissionError("人物冲突审查决定必须由用户明确确认")
        if decision not in {
            CharacterIdentityReviewDecisionType.DISTINCT,
            CharacterIdentityReviewDecisionType.DEFERRED,
        }:
            raise CharacterIdentityError("只能选择不是同一人物或暂缓处理")
        try:
            return self.repository.set_review_decision(
                first_character_id,
                second_character_id,
                decision,
                reason=reason,
            )
        except (KeyError, CharacterIdentityRepositoryError) as error:
            raise CharacterIdentityError(str(error)) from error

    def reopen_review_candidate(
        self,
        first_character_id: str,
        second_character_id: str,
        *,
        confirmed_by_user: bool,
    ) -> CharacterIdentityReviewDecision:
        if not confirmed_by_user:
            raise PermissionError("重新加入人物冲突审查必须由用户明确确认")
        try:
            self.repository.get_review_decision(first_character_id, second_character_id)
            return self.repository.set_review_decision(
                first_character_id,
                second_character_id,
                CharacterIdentityReviewDecisionType.REOPENED,
                reason="用户重新加入审查",
            )
        except (KeyError, CharacterIdentityRepositoryError) as error:
            raise CharacterIdentityError(str(error)) from error

    def list_excluded_review_candidates(
        self,
    ) -> tuple[ExcludedCharacterIdentityCandidate, ...]:
        excluded: list[ExcludedCharacterIdentityCandidate] = []
        for decision in self.repository.list_active_review_decisions():
            try:
                left = self.memory_repository.get_character(decision.first_character_id)
                right = self.memory_repository.get_character(decision.second_character_id)
            except KeyError:
                continue
            excluded.append(
                ExcludedCharacterIdentityCandidate(
                    decision=decision,
                    left_name=left.canonical_name,
                    right_name=right.canonical_name,
                )
            )
        return tuple(excluded)

    def _agent_review_candidates(
        self,
        characters: tuple[Character, ...],
        snapshots: dict[str, CharacterIdentityCardSnapshot],
    ) -> tuple[CharacterIdentityReviewCandidate, ...]:
        candidates: list[CharacterIdentityReviewCandidate] = []
        seen_pairs: set[frozenset[str]] = set()
        calls = self.agent_repository.list_recent_executed_tool_calls(
            AgentToolName.PROPOSE_CHARACTER_IDENTITY_MERGE
        )
        for call in calls:
            try:
                arguments = json.loads(call.arguments_json)
            except (TypeError, ValueError):
                continue
            if not isinstance(arguments, dict):
                continue
            source_name = arguments.get("source_character_name")
            target_name = arguments.get("target_character_name")
            reason = arguments.get("reason")
            values = (source_name, target_name, reason)
            if not all(isinstance(value, str) and value.strip() for value in values):
                continue
            source = self._character_by_name(characters, str(source_name))
            target = self._character_by_name(characters, str(target_name))
            if source is None or target is None or source.id == target.id:
                continue
            pair = frozenset((source.id, target.id))
            if pair in seen_pairs:
                continue
            candidates.append(
                CharacterIdentityReviewCandidate(
                    left=snapshots[source.id],
                    right=snapshots[target.id],
                    reason=str(reason).strip(),
                    recommended_character_id=target.id,
                    origin=CharacterIdentityCandidateOrigin.AGENT_PROPOSAL,
                    proposal_id=call.id,
                )
            )
            seen_pairs.add(pair)
        return tuple(candidates)

    def _character_by_name(
        self, characters: tuple[Character, ...], name: str
    ) -> Character | None:
        subjects = self.subject_repository.resolve_character_name(name)
        if len(subjects) != 1:
            return None
        character_by_id = {character.id: character for character in characters}
        return character_by_id.get(subjects[0].id)

    def list_recent_applied_merges(
        self, *, limit: int = 20
    ) -> tuple[RecentCharacterIdentityMerge, ...]:
        recent: list[RecentCharacterIdentityMerge] = []
        for merge in self.repository.list_recent_applied(limit=limit):
            target = self.memory_repository.get_character(merge.target_character_id)
            recent.append(
                RecentCharacterIdentityMerge(
                    merge=merge,
                    source_name=merge.source_canonical_name,
                    target_name=target.canonical_name,
                )
            )
        return tuple(recent)

    @staticmethod
    def _snapshot(
        character: Character,
        history: tuple[CharacterStateEvent, ...],
        chapter_titles: dict[str, str],
    ) -> CharacterIdentityCardSnapshot:
        evidence = tuple(
            CharacterStateEvidence(
                chapter_id=event.chapter_id,
                chapter_title=chapter_titles.get(event.chapter_id, event.chapter_id),
                summary=CharacterIdentityService._state_summary(event),
            )
            for event in history[-3:]
        )
        return CharacterIdentityCardSnapshot(character, len(history), evidence)

    @staticmethod
    def _state_summary(event: CharacterStateEvent) -> str:
        parts = tuple(
            value.strip()
            for value in (
                event.recent_activity,
                event.current_goal,
                event.relationships,
                event.psychology,
            )
            if value.strip()
        )
        return "；".join(parts) if parts else "该章仅有空白状态记录"

    @classmethod
    def _name_relation(cls, left: Character, right: Character) -> str | None:
        left_names = cls._normalized_names(left)
        right_names = cls._normalized_names(right)
        shared = sorted(set(left_names) & set(right_names), key=lambda value: (-len(value), value))
        if shared:
            display = left_names[shared[0]]
            return f"名称或别名“{display}”完全一致"
        for left_value, left_display in left_names.items():
            for right_value, right_display in right_names.items():
                shorter, longer = sorted((left_value, right_value), key=len)
                if len(shorter) < 2 or shorter not in longer:
                    continue
                short_display = left_display if shorter == left_value else right_display
                long_display = right_display if longer == right_value else left_display
                return f"“{short_display}”可能是“{long_display}”的简称"
        return None

    @staticmethod
    def _normalized_names(character: Character) -> dict[str, str]:
        values: dict[str, str] = {}
        for name in (character.canonical_name, *character.aliases):
            normalized = "".join(char.casefold() for char in name if char.isalnum())
            if normalized:
                values.setdefault(normalized, name)
        return values

    @classmethod
    def _recommended_character_id(cls, left: Character, right: Character) -> str:
        def score(character: Character) -> tuple[int, int, int, str]:
            normalized = cls._normalized_names(character)
            canonical_length = len(
                "".join(
                    char.casefold()
                    for char in character.canonical_name
                    if char.isalnum()
                )
            )
            return canonical_length, len(normalized), len(character.profile.strip()), character.id

        return max((left, right), key=score).id
