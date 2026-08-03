"""Phase 1: editor bridge payload validation."""

from pathlib import Path

from ai_novel_studio.ui_qml.bridge.editor_bridge import (
    EditorBridge,
    fnv1a_hash,
    sha256,
    validate_content_hash,
)
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import MockNovelStudioFacade

from .test_project_wiring import create_temp_project


def test_editor_ready_accepts_valid_protocol() -> None:
    bridge = EditorBridge()
    received: list[tuple[int, str]] = []
    bridge.editor_ready.connect(lambda version, caps: received.append((version, caps)))

    bridge.editorReady(1, '["markdown-v1","selection-v1","decorations-v1"]')

    assert len(received) == 1
    assert received[0][0] == 1
    assert bridge.capabilities == {"markdown-v1", "selection-v1", "decorations-v1"}


def test_editor_ready_rejects_version_mismatch() -> None:
    bridge = EditorBridge()
    errors: list[tuple[str, str]] = []
    bridge.error.connect(lambda code, message: errors.append((code, message)))

    bridge.editorReady(2, "[]")

    assert errors[0][0] == "PROTOCOL_MISMATCH"


def test_editor_ready_rejects_unknown_capabilities() -> None:
    bridge = EditorBridge()
    errors: list[tuple[str, str]] = []
    bridge.error.connect(lambda code, message: errors.append((code, message)))

    bridge.editorReady(1, '["markdown-v1","remote-shell"]')

    assert errors[0][0] == "UNKNOWN_CAPABILITY"


def test_save_requested_validates_payload_and_emits() -> None:
    bridge = EditorBridge()
    saves: list[tuple[str, int, str, str]] = []
    bridge.save_requested.connect(lambda *args: saves.append(args))
    markdown = "# 第一章\n\n正文"

    bridge.saveRequested("chapter-1", 3, markdown, sha256(markdown))

    assert len(saves) == 1
    assert saves[0][0] == "chapter-1"
    assert saves[0][1] == 3
    assert bridge.last_save_revision == 3


def test_save_requested_rejects_hash_mismatch() -> None:
    bridge = EditorBridge()
    errors: list[tuple[str, str]] = []
    bridge.error.connect(lambda code, message: errors.append((code, message)))

    bridge.saveRequested("chapter-1", 1, "正文", "wrong-hash")

    assert errors[0][0] == "HASH_MISMATCH"
    assert bridge.last_save_revision is None


def test_save_requested_rejects_invalid_chapter_and_revision() -> None:
    bridge = EditorBridge()
    errors: list[tuple[str, str]] = []
    bridge.error.connect(lambda code, message: errors.append((code, message)))

    bridge.saveRequested("", 1, "正文", sha256("正文"))
    bridge.saveRequested("c1", -1, "正文", sha256("正文"))

    assert [code for code, _ in errors] == ["INVALID_CHAPTER_ID", "INVALID_REVISION"]


def test_save_requested_rejects_oversized_payload() -> None:
    bridge = EditorBridge()
    errors: list[tuple[str, str]] = []
    bridge.error.connect(lambda code, message: errors.append((code, message)))

    bridge.saveRequested("c1", 1, "大" * 2_000_000, sha256("大" * 2_000_000))

    assert errors[0][0] == "PAYLOAD_TOO_LARGE"


def test_selection_changed_ignores_negative_positions() -> None:
    bridge = EditorBridge()
    emitted: list[tuple[int, int]] = []
    bridge.selection_changed.connect(lambda f, t: emitted.append((f, t)))

    bridge.selectionChanged(-1, 5)
    assert emitted == []

    bridge.selectionChanged(2, 8)
    assert emitted == [(2, 8)]


def test_word_count_changed_forwards_positive_counts() -> None:
    bridge = EditorBridge()
    emitted: list[int] = []
    bridge.word_count_changed.connect(emitted.append)

    bridge.wordCountChanged(13570)
    bridge.wordCountChanged(-1)

    assert emitted == [13570]


def test_bridge_save_flows_into_facade_persistence(tmp_path: Path) -> None:
    root = create_temp_project(tmp_path / "novel")
    facade = MockNovelStudioFacade()
    facade.openProject(str(root))
    chapter_id = facade.property("currentChapterId")
    bridge = EditorBridge()
    bridge.save_requested.connect(facade.saveFromEditor)
    markdown = "来自 WebEngine 的正文"

    bridge.saveRequested(chapter_id, 1, markdown, sha256(markdown))

    assert facade.property("editorState") == "CLEAN"
    assert facade.property("currentRevision") == 2
    assert facade.property("currentChapterBody") == markdown


def test_fnv1a_hash_matches_javascript_fingerprint_format() -> None:
    assert fnv1a_hash("正文").startswith("fnv1a:")
    assert len(fnv1a_hash("正文")) == len("fnv1a:") + 8


def test_validate_content_hash_accepts_fnv_and_sha256() -> None:
    markdown = "正文"
    assert validate_content_hash(markdown, fnv1a_hash(markdown)) is True
    assert validate_content_hash(markdown, sha256(markdown)) is True
    assert validate_content_hash(markdown, fnv1a_hash("别的")) is False
    assert validate_content_hash(markdown, "wrong") is False


def test_bridge_accepts_fnv_fingerprint_save(tmp_path: Path) -> None:
    root = create_temp_project(tmp_path / "novel")
    facade = MockNovelStudioFacade()
    facade.openProject(str(root))
    chapter_id = facade.property("currentChapterId")
    bridge = EditorBridge()
    bridge.save_requested.connect(facade.saveFromEditor)
    markdown = "带 FNV 指纹的正文"

    bridge.saveRequested(chapter_id, 1, markdown, fnv1a_hash(markdown))

    assert facade.property("editorState") == "CLEAN"
    assert facade.property("currentRevision") == 2
