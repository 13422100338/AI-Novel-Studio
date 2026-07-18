import pytest

from ai_novel_studio.domain.view import (
    EpistemicStatus,
    ViewAssertionDraft,
    ViewType,
)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("subject_id", None),
        ("content", 42),
        ("viewer_subject_id", 42),
        ("story_time_label", False),
    ),
)
def test_view_assertion_draft_rejects_invalid_text_types(
    field: str, value: object
) -> None:
    values: dict[str, object] = {
        "subject_id": "subject-1",
        "view_type": ViewType.WORLD_TRUTH,
        "content": "fact",
    }
    values[field] = value

    with pytest.raises(ValueError, match=field):
        ViewAssertionDraft(**values)  # type: ignore[arg-type]


def test_view_assertion_draft_rejects_unparsed_view_enum() -> None:
    with pytest.raises(ValueError, match="view_type"):
        ViewAssertionDraft(
            subject_id="subject-1",
            view_type="WORLD_TRUTH",  # type: ignore[arg-type]
            content="fact",
        )


def test_character_view_rejects_unparsed_epistemic_enum() -> None:
    with pytest.raises(ValueError, match="epistemic_status"):
        ViewAssertionDraft(
            subject_id="subject-1",
            view_type=ViewType.CHARACTER_VIEW,
            viewer_subject_id="viewer-1",
            epistemic_status="KNOWS",  # type: ignore[arg-type]
            content="fact",
        )


def test_view_assertion_draft_normalizes_valid_model_fields() -> None:
    draft = ViewAssertionDraft(
        subject_id="  subject-1  ",
        view_type=ViewType.CHARACTER_VIEW,
        viewer_subject_id="  viewer-1  ",
        epistemic_status=EpistemicStatus.BELIEVES,
        content="  belief  ",
        story_time_label="  the next morning  ",
    )

    assert draft.subject_id == "subject-1"
    assert draft.viewer_subject_id == "viewer-1"
    assert draft.content == "belief"
    assert draft.story_time_label == "the next morning"
