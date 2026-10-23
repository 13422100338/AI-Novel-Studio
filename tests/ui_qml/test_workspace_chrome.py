from pathlib import Path

import pytest
from PySide6.QtCore import QMetaObject, QObject, QUrl

from .test_outline_page import _find
from .test_outline_workspace_layout import workspace as workspace


def test_old_library_entry_is_removed_and_status_details_are_at_the_left(workspace, qtbot):
    _, _, _, window, _, _, warnings = workspace
    assert _find(window.contentItem(), "nav-library") is None
    status = _find(window.contentItem(), "statusMoreButton")
    qtbot.wait(50)
    assert status.mapToScene(status.boundingRect().center()).x() < window.width() / 2
    assert not warnings


def test_theme_controls_are_available_from_settings(workspace, qtbot):
    _, facade, _, window, _, _, warnings = workspace
    settings = _find(window.contentItem(), "nav-settings")
    assert settings is not None
    assert _find(window.contentItem(), "navRailGlass") is None
    center = settings.mapToScene(settings.boundingRect().center())
    assert center.x() > window.width() - 60
    assert center.y() > window.height() - 45
    QMetaObject.invokeMethod(settings, "clicked")
    assert facade.activeNav == "settings"
    button = _find(window.contentItem(), "appearanceSettingsButton")
    assert button is not None
    QMetaObject.invokeMethod(button, "clicked")
    qtbot.waitUntil(lambda: _find(window.contentItem(), "appearance-theme-light") is not None)
    QMetaObject.invokeMethod(_find(window.contentItem(), "appearance-theme-light"), "clicked")
    assert _find(window.contentItem(), "appearance-theme-light").property("selected")
    assert not warnings


def test_new_project_dialog_has_one_cancel_and_creates_a_temporary_project(
    workspace, tmp_path, qtbot
):
    _, facade, _, window, _, _, warnings = workspace
    QMetaObject.invokeMethod(_find(window.contentItem(), "newProjectButton"), "clicked")
    dialog = window.findChild(QObject, "newProjectDialog")
    confirm = window.findChild(QObject, "createProjectConfirmButton")
    qtbot.waitUntil(lambda: dialog.property("visible"))
    assert not confirm.property("enabled")
    cancels = [
        item
        for item in dialog.findChildren(QObject)
        if item.inherits("QQuickAbstractButton")
        and item.property("text") == "取消"
        and item.property("visible")
    ]
    assert len(cancels) == 1
    name = window.findChild(QObject, "newProjectNameInput")
    name.setProperty("text", "临时小说")
    parent = tmp_path.parent / "new-book-location"
    parent.mkdir()
    selected = QUrl.fromLocalFile(str(parent))
    assert dialog.setProperty("selectedParentUrl", selected)
    assert Path(dialog.property("selectedParentUrl").toLocalFile()) == parent
    assert confirm.property("enabled")
    QMetaObject.invokeMethod(confirm, "clicked")
    assert window.findChild(QObject, "newProjectError").property("text") == ""
    qtbot.waitUntil(lambda: facade.projectTitle == "临时小说")
    assert (parent / "临时小说").is_dir()
    assert not dialog.property("visible")
    assert not warnings


@pytest.mark.parametrize("kind", ["Volume", "Chapter"])
def test_volume_and_chapter_creation_dialogs_have_one_cancel_and_submit(workspace, qtbot, kind):
    project, facade, _, window, _, _, warnings = workspace
    facade.setActiveNav("writing")
    QMetaObject.invokeMethod(_find(window.contentItem(), f"new{kind}Button"), "clicked")
    dialog = window.findChild(QObject, f"new{kind}Dialog")
    qtbot.waitUntil(lambda: dialog.property("visible"))
    cancels = [
        item
        for item in dialog.findChildren(QObject)
        if item.inherits("QQuickAbstractButton")
        and item.property("text") == "取消"
        and item.property("visible")
    ]
    assert len(cancels) == 1
    confirm = window.findChild(QObject, f"create{kind}ConfirmButton")
    assert confirm is not None and not confirm.property("enabled")
    if kind == "Volume":
        name = "第二卷 · 远行"
        _find(window.contentItem(), "newVolumeNameInput").setProperty("text", name)
    else:
        name = "雾中的来客"
        _find(window.contentItem(), "newChapterTitleInput").setProperty("text", name)
        _find(window.contentItem(), "newChapterNumberInput").setProperty("text", "第3章")
    assert confirm.property("enabled")
    QMetaObject.invokeMethod(confirm, "clicked")
    qtbot.waitUntil(lambda: not dialog.property("visible"))
    if kind == "Volume":
        assert name in [volume.title for volume in project.list_volumes()]
    else:
        assert facade.property("currentChapterTitle") == name
    assert not warnings
