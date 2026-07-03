from datetime import UTC, datetime

import pytest

from ai_novel_studio.domain.memory import (
    Authority,
    Character,
    CharacterStateEvent,
    ClueAction,
    ClueType,
    KnowledgeState,
    KnowledgeSubject,
    MemoryStatus,
    ReviewStatus,
    SourceType,
    StyleScope,
    SummaryLevel,
)


def test_phase_four_enums_expose_stable_storage_values() -> None:
    assert Authority.USER_CONFIRMED.value == "USER_CONFIRMED"
    assert KnowledgeSubject.READER.value == "READER"
    assert KnowledgeState.MISUNDERSTOOD.value == "MISUNDERSTOOD"
    assert ClueType.MISDIRECTION.value == "MISDIRECTION"
    assert ClueAction.REDIRECT.value == "REDIRECT"
    assert SummaryLevel.CHAPTER.value == "L1"
    assert StyleScope.GENRE_OR_SCENE.value == "GENRE_OR_SCENE"
    assert MemoryStatus.STALE.value == "STALE"


def test_authority_rank_is_explicit_and_user_confirmation_is_highest() -> None:
    assert Authority.USER_CONFIRMED.rank > Authority.OUTLINE.rank
    assert Authority.OUTLINE.rank > Authority.MODEL_EXTRACTED.rank
    assert Authority.MODEL_EXTRACTED.rank > Authority.INFERRED.rank


def test_character_normalizes_aliases_and_rejects_empty_name() -> None:
    character = Character("character-1", "林岚", (" 林岚 ", "阿岚", "阿岚"), "主角")

    assert character.aliases == ("林岚", "阿岚")

    with pytest.raises(ValueError, match="人物名称"):
        Character("character-2", "  ", (), "")


def test_character_state_rejects_confidence_outside_zero_to_one() -> None:
    with pytest.raises(ValueError, match="confidence"):
        CharacterStateEvent(
            id="state-1",
            character_id="character-1",
            chapter_id="chapter-1",
            motivation="追查真相",
            psychology="警惕",
            current_goal="进入档案室",
            relationships="与同伴互不信任",
            recent_activity="发现来信",
            confidence=1.1,
            source_type=SourceType.MODEL,
            review_status=ReviewStatus.REVIEW,
            created_at=datetime.now(UTC),
        )

