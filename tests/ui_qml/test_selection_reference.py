"""H-SEL1 selection-patch-v1 bridge and Facade boundary tests."""

from __future__ import annotations

import json

from ai_novel_studio.application.selection_patch import (
    ANCHOR_CODEPOINTS,
    MAX_SELECTION_CODEPOINTS,
    SCHEMA_VERSION,
)
from ai_novel_studio.ui_qml.bridge.editor_bridge import EditorBridge
from ai_novel_studio.ui_qml.bridge.hash_utils import sha256
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import (
    MockNovelStudioFacade,
)
from ai_novel_studio.ui_qml.bridge.models.selection_reference import (
    parse_selection_reference,
)

_SOURCE = (
    "清晨的雾港还浸在灰蓝色的光线里。渡轮靠岸时，甲板上的水汽"
    "把远处灯塔的光晕揉成一团模糊的暖色。\n\n"
    "林默把最后一封信塞进外套内袋，沿着湿漉漉的栈桥走进镇子。"
    "他没想到，二十年后回到这里的第一个清晨，会先听见钟声。"
)
_SELECTED_TEXT = "清晨的雾港"


def _span(source: str, start: int, end: int) -> dict[str, object]:
    text = source[start:end]
    return {
        "start": start,
        "end": end,
        "text": text,
        "text_hash": sha256(text),
    }


def _valid_payload(
    *,
    source: str = _SOURCE,
    selected_text: str = _SELECTED_TEXT,
    occurrence: int = 0,
    chapter_id: str = "chapter-1",
    base_revision: int = 3,
) -> str:
    start = -1
    for _ in range(occurrence + 1):
        start = source.index(selected_text, start + 1)
    end = start + len(selected_text)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "chapter_id": chapter_id,
        "base_revision": base_revision,
        "base_source_hash": sha256(source),
        "selection": _span(source, start, end),
        "before_anchor": _span(source, max(0, start - ANCHOR_CODEPOINTS), start),
        "after_anchor": _span(
            source,
            end,
            min(len(source), end + ANCHOR_CODEPOINTS),
        ),
    }
    return json.dumps(payload, ensure_ascii=False)


def test_parse_selection_reference_accepts_complete_patch_capture() -> None:
    ref = parse_selection_reference(_valid_payload())
    assert ref is not None
    assert ref.schema_version == SCHEMA_VERSION
    assert ref.chapter_id == "chapter-1"
    assert ref.base_revision == 3
    assert ref.base_source_hash == sha256(_SOURCE)
    assert ref.selection.text == _SELECTED_TEXT
    assert ref.before_anchor.end == ref.selection.start
    assert ref.after_anchor.start == ref.selection.end


def test_parse_selection_reference_rejects_unknown_fields_versions_and_fnv() -> None:
    payload = json.loads(_valid_payload())
    payload["unexpected"] = "no"
    assert parse_selection_reference(json.dumps(payload)) is None

    payload = json.loads(_valid_payload())
    payload["schema_version"] = "selection-patch-v2"
    assert parse_selection_reference(json.dumps(payload)) is None

    payload = json.loads(_valid_payload())
    payload["base_source_hash"] = "fnv1a:00000000"
    assert parse_selection_reference(json.dumps(payload)) is None


def test_parse_selection_reference_rejects_invalid_and_oversized_payloads() -> None:
    assert parse_selection_reference("not json") is None
    assert parse_selection_reference("[]") is None
    assert parse_selection_reference("") is None

    oversized = "字" * (MAX_SELECTION_CODEPOINTS + 1)
    assert (
        parse_selection_reference(_valid_payload(source=oversized, selected_text=oversized)) is None
    )


def test_bridge_forwards_valid_capture_and_errors_on_invalid() -> None:
    bridge = EditorBridge()
    emitted: list[str] = []
    errors: list[tuple[str, str]] = []
    bridge.selection_reference_changed.connect(emitted.append)
    bridge.error.connect(lambda code, message: errors.append((code, message)))

    bridge.selectionReferenceChanged(_valid_payload())
    assert len(emitted) == 1

    bridge.selectionReferenceChanged('{"schema_version":"selection-patch-v1"}')
    assert emitted == [_valid_payload(), ""]
    assert errors == [("INVALID_SELECTION_REFERENCE", "选区引用数据无效，已忽略")]

    bridge.selectionReferenceChanged("")
    assert emitted[-1] == ""


def test_facade_selection_patch_lifecycle_and_preview() -> None:
    facade = MockNovelStudioFacade(demo_mode=True)
    assert facade.property("hasSelectionReference") is False

    facade.setSelectionReferenceJson(_valid_payload())
    assert facade.property("hasSelectionReference") is True
    assert _SELECTED_TEXT in facade.property("selectionReferencePreview")
    assert "字" in facade.property("selectionReferenceLabel")

    facade.clearSelectionReference()
    assert facade.property("hasSelectionReference") is False

    facade.setSelectionReferenceJson(_valid_payload())
    facade.selectChapter(1)
    assert facade.property("hasSelectionReference") is False


def test_facade_preview_is_single_line_with_ellipsis_for_cross_paragraph_span() -> None:
    facade = MockNovelStudioFacade(demo_mode=True)
    facade.setSelectionReferenceJson(_valid_payload(source=_SOURCE, selected_text=_SOURCE))

    preview = facade.property("selectionReferencePreview")
    assert isinstance(preview, str)
    assert "\n" not in preview
    assert " " in preview
    assert preview.endswith("…")
    assert len(preview) <= 81


def test_facade_rejects_stale_chapter_revision_and_source_hash() -> None:
    facade = MockNovelStudioFacade(demo_mode=True)

    facade.setSelectionReferenceJson(_valid_payload(chapter_id="chapter-2"))
    assert facade.property("hasSelectionReference") is False
    assert "过期" in facade.property("saveStatusText")

    facade.setSelectionReferenceJson(_valid_payload(base_revision=2))
    assert facade.property("hasSelectionReference") is False
    assert "过期" in facade.property("saveStatusText")

    facade.setSelectionReferenceJson(
        _valid_payload(source=_SOURCE + " drift", selected_text=_SELECTED_TEXT)
    )
    assert facade.property("hasSelectionReference") is False
    assert "过期" in facade.property("saveStatusText")


def test_empty_payload_clears_reference() -> None:
    facade = MockNovelStudioFacade(demo_mode=True)
    facade.setSelectionReferenceJson(_valid_payload())
    facade.setSelectionReferenceJson("")
    assert facade.property("hasSelectionReference") is False


def test_invalid_payload_clears_previous_facade_reference() -> None:
    facade = MockNovelStudioFacade(demo_mode=True)
    facade.setSelectionReferenceJson(_valid_payload())
    assert facade.property("hasSelectionReference") is True

    facade.setSelectionReferenceJson('{"schema_version":"selection-patch-v1"}')

    assert facade.property("hasSelectionReference") is False
    assert facade.property("saveStatusText") == "选区引用数据无效，已清除"
