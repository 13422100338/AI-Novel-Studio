from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from ai_novel_studio.harness.conversation_summary import (
    ConversationSummary,
    SummaryRevision,
)


def test_summary_normalizes_and_deduplicates_lists() -> None:
    summary = ConversationSummary(
        confirmed_decisions=("  decision a  ", "decision a", " "),
        rejected_options=(),
    )
    assert summary.confirmed_decisions == ("decision a",)
    assert summary.rejected_options == ()
    assert summary.unresolved_questions == ()


def test_summary_round_trips_through_json() -> None:
    summary = ConversationSummary(
        confirmed_decisions=("decide the POV",),
        important_rationale=("作者想保持第一人称",),
    )
    payload = json.loads(summary.to_json())
    assert payload["confirmed_decisions"] == ["decide the POV"]
    assert payload["important_rationale"] == ["作者想保持第一人称"]


def test_summary_revision_requires_positive_revision_and_utc() -> None:
    naive = datetime(2026, 8, 14, 12, 0, 0)
    revision = SummaryRevision(1, ConversationSummary(), naive)
    assert revision.created_at.tzinfo is UTC
    with pytest.raises(ValueError):
        SummaryRevision(0, ConversationSummary(), naive)


def test_summary_is_never_a_domain_truth_source() -> None:
    # 摘要只存会话事实,不含权威/修订/来源结构字段
    summary = ConversationSummary(confirmed_decisions=("x",))
    assert not hasattr(summary, "authority")
    assert not hasattr(summary, "review_status")
