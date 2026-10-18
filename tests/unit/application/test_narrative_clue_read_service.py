"""QP-3A: bounded read-only projection over the approved clue ledger.

Contract under test: only CURRENT clues with APPROVED/LOCKED reviews, events
strictly before the target chapter in canonical order, truncated summaries,
deterministic ordering, sanitized fixed errors, and zero writes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("ai_novel_studio.application")

from ai_novel_studio.application.narrative_clue_read_service import (
    NarrativeClueReadService,
)
from ai_novel_studio.domain.memory import (
    Authority,
    ClueAction,
    ClueType,
    SourceType,
)
from ai_novel_studio.domain.memory import (
    ReviewStatus as ReviewStatusDomain,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import (
    ChapterRepository,
)
from ai_novel_studio.infrastructure.storage.narrative_memory_repository import (
    NarrativeMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import (
    ProjectRepository,
)


def _project(tmp_path: Path) -> tuple[ProjectRepository, list[str]]:
    project = ProjectRepository.create(tmp_path / "novel", "线索投影")
    chapters = ChapterRepository(project)
    ids = [
        chapters.create_chapter(project.list_volumes()[0].id, f"第{i}章", str(i)).id
        for i in range(1, 4)
    ]
    return project, ids


def _seed(
    repository: NarrativeMemoryRepository,
    chapter_id: str,
    *,
    tag: str,
    review_status=ReviewStatusDomain.APPROVED,
) -> str:
    clue = repository.add_clue(
        ClueType.FORESHADOW,
        f"铜钥匙的来历{tag}",
        f"细节摘要 {tag}。",
        Authority.MODEL_EXTRACTED if review_status is not ReviewStatusDomain.APPROVED
        else Authority.USER_CONFIRMED,
        review_status,
    )
    repository.append_clue_action(
        clue.id,
        chapter_id,
        ClueAction.PLANT,
        f"在第一章埋下 {tag}",
        source_type=SourceType.SYSTEM,
        review_status=review_status,
    )
    return clue.id


def test_returns_only_approved_current_before_target_ordered(tmp_path: Path) -> None:
    project, ids = _project(tmp_path)
    memory = NarrativeMemoryRepository(project)
    kept = _seed(memory, ids[0], tag="kept")
    rejected = _seed(
        memory, ids[0], tag="rejected", review_status=ReviewStatusDomain.REJECTED
    )
    later = _seed(memory, ids[2], tag="later")
    service = NarrativeClueReadService(project)

    rows = service.list_clues_before(ids[1])

    assert [row.clue_id for row in rows] == [kept]
    row = rows[0]
    assert row.title == "铜钥匙的来历kept"
    assert row.event_count == 1
    assert row.last_action == "PLANT"
    assert len(row.summary) <= 200
    assert rejected not in [r.clue_id for r in rows]
    assert later not in [r.clue_id for r in rows]


def test_unknown_chapter_maps_to_fixed_error(tmp_path: Path) -> None:
    from ai_novel_studio.domain.identifiers import new_id

    project, _ids = _project(tmp_path)
    service = NarrativeClueReadService(project)

    with pytest.raises(ValueError, match="unknown chapter"):
        service.list_clues_before(new_id())


def test_results_are_bounded_and_deterministic(tmp_path: Path) -> None:
    project, ids = _project(tmp_path)
    memory = NarrativeMemoryRepository(project)
    for index in range(5):
        _seed(memory, ids[0], tag=f"n{index}")
    service = NarrativeClueReadService(project)

    first = service.list_clues_before(ids[1])
    second = service.list_clues_before(ids[1])

    assert len(first) == 5
    assert [row.clue_id for row in first] == [row.clue_id for row in second]


def test_first_200_clues_without_events_do_not_block_valid_later_clues(
    tmp_path: Path,
) -> None:
    """RC-4 follow-up: the bounded query must first select clue IDs that
    have eligible events, not just the oldest N clue rows."""
    project, ids = _project(tmp_path)
    memory = NarrativeMemoryRepository(project)
    # Seed 200 clues with NO events (they should all be excluded).
    for index in range(200):
        memory.add_clue(
            ClueType.FORESHADOW,
            f"无事件线索 {index}",
            f"摘要 {index}",
            Authority.USER_CONFIRMED,
            ReviewStatusDomain.APPROVED,
        )
    # Now seed one valid clue WITH an event — must not be blocked.
    valid = _seed(memory, ids[0], tag="valid")
    service = NarrativeClueReadService(project)

    rows = service.list_clues_before(ids[1])

    assert len(rows) == 1
    assert rows[0].clue_id == valid


def test_multi_action_ordering_last_action_is_truly_latest(
    tmp_path: Path,
) -> None:
    """RC-4 follow-up: with multiple actions on a single clue across
    chapters, last_action and chapter_ids must reflect the true latest
    before-target event in narrative order."""
    project, ids = _project(tmp_path)
    memory = NarrativeMemoryRepository(project)
    from ai_novel_studio.domain.memory import SourceType

    clue = memory.add_clue(
        ClueType.FORESHADOW,
        "跨章伏笔",
        "跨章摘要",
        Authority.USER_CONFIRMED,
        ReviewStatusDomain.APPROVED,
    )
    actions_and_chapters = [
        (ClueAction.PLANT, ids[0], "埋下"),
        (ClueAction.REINFORCE, ids[0], "强化"),
        (ClueAction.REDIRECT, ids[1], "转向"),
        (ClueAction.REVEAL, ids[1], "揭示"),
    ]
    for action, ch_id, detail in actions_and_chapters:
        memory.append_clue_action(
            clue.id, ch_id, action, detail,
            source_type=SourceType.SYSTEM,
            review_status=ReviewStatusDomain.APPROVED,
        )
    service = NarrativeClueReadService(project)

    # Viewing at ch3 (after both chapters): latest is REVEAL at ch2.
    rows = service.list_clues_before(ids[2])
    assert len(rows) == 1
    row = rows[0]
    assert row.last_action == "REVEAL"
    assert row.event_count == 4
    assert row.chapter_ids[-1] == ids[1]

    # Viewing at ch2 (only ch1 events are strictly before): PLANT + REINFORCE.
    rows_early = service.list_clues_before(ids[1])
    assert len(rows_early) == 1
    assert rows_early[0].last_action == "REINFORCE"
    assert rows_early[0].event_count == 2

    # Hydrated events never exceed the per-clue cap.
    assert len(rows[0].chapter_ids) <= 50


def test_hydrated_event_total_does_not_exceed_hard_cap(tmp_path: Path) -> None:
    """RC-4 follow-up: total hydrated events must never exceed
    max_clues × max_events_per_clue (= 200 × 50 = 10000)."""
    project, ids = _project(tmp_path)
    memory = NarrativeMemoryRepository(project)
    from ai_novel_studio.domain.memory import SourceType

    # Create 10 clues each with 60 events before target.
    for clue_index in range(10):
        clue = memory.add_clue(
            ClueType.FORESHADOW,
            f"线索 {clue_index}",
            f"摘要 {clue_index}",
            Authority.USER_CONFIRMED,
            ReviewStatusDomain.APPROVED,
        )
        for event_index in range(60):
            memory.append_clue_action(
                clue.id, ids[0],
                ClueAction.PLANT if event_index < 30 else ClueAction.REINFORCE,
                f"事件 {event_index}",
                source_type=SourceType.SYSTEM,
                review_status=ReviewStatusDomain.APPROVED,
            )
    service = NarrativeClueReadService(project)

    rows = service.list_clues_before(ids[1])

    assert len(rows) == 10
    total_hydrated = sum(len(row.chapter_ids) for row in rows)
    assert total_hydrated <= 10 * 50


def test_later_chapter_events_do_not_crowd_out_earlier_evidence(
    tmp_path: Path,
) -> None:
    """RC-4 follow-up: the per-clue cap must rank the already-eligible set.
    If a clue has 60 events before target and 60 after, all 60 earlier ones
    must survive (total=120, returned<=50 newest-before-target)."""
    project, ids = _project(tmp_path)
    memory = NarrativeMemoryRepository(project)
    from ai_novel_studio.domain.memory import SourceType

    clue = memory.add_clue(
        ClueType.FORESHADOW,
        "跨章伏笔",
        "跨章摘要",
        Authority.USER_CONFIRMED,
        ReviewStatusDomain.APPROVED,
    )
    # 60 approved events at chapter 1 (before target ch2)
    for index in range(60):
        memory.append_clue_action(
            clue.id, ids[0], ClueAction.PLANT,
            f"前文 {index}", source_type=SourceType.SYSTEM,
            review_status=ReviewStatusDomain.APPROVED,
        )
    # 60 more approved events at chapter 3 (after target ch2) — these must
    # NOT consume the per-clue budget of before-target rows.
    for index in range(60):
        memory.append_clue_action(
            clue.id, ids[2], ClueAction.REINFORCE,
            f"后文 {index}", source_type=SourceType.SYSTEM,
            review_status=ReviewStatusDomain.APPROVED,
        )
    service = NarrativeClueReadService(project)

    rows = service.list_clues_before(ids[1])

    assert len(rows) == 1
    row = rows[0]
    assert row.clue_id == clue.id
    assert row.event_count == 60
    assert len(row.chapter_ids) == 50
    assert all(cid == ids[0] for cid in row.chapter_ids)


def test_backfill_ordering_uses_narrative_position_not_created_at(
    tmp_path: Path,
) -> None:
    """Final fix (P1): events must be ordered by narrative position, not by
    insertion time. If a later-chapter event is inserted FIRST and an
    earlier-chapter event is backfilled SECOND, the earlier-chapter event
    must still come first in the timeline."""
    project, ids = _project(tmp_path)
    memory = NarrativeMemoryRepository(project)
    from ai_novel_studio.domain.memory import SourceType

    clue = memory.add_clue(
        ClueType.FORESHADOW,
        "回填顺序",
        "回填顺序摘要",
        Authority.USER_CONFIRMED,
        ReviewStatusDomain.APPROVED,
    )
    # Deliberately insert ch2 (later) event FIRST.
    memory.append_clue_action(
        clue.id, ids[1], ClueAction.REVEAL,
        "第二章揭示", source_type=SourceType.SYSTEM,
        review_status=ReviewStatusDomain.APPROVED,
    )
    # Then backfill ch1 (earlier) event — has LATER created_at but EARLIER
    # narrative position.
    memory.append_clue_action(
        clue.id, ids[0], ClueAction.PLANT,
        "第一章埋下", source_type=SourceType.SYSTEM,
        review_status=ReviewStatusDomain.APPROVED,
    )
    service = NarrativeClueReadService(project)

    rows = service.list_clues_before(ids[2])

    assert len(rows) == 1
    row = rows[0]
    assert row.last_action == "REVEAL"
    assert row.event_count == 2
    # chapter_ids are in narrative order: ch1 then ch2.
    assert list(row.chapter_ids) == [ids[0], ids[1]]
