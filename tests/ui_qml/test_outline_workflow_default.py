import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QMetaObject, QUrl
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow

from ai_novel_studio.infrastructure.storage.audit_repository import AuditRepository
from ai_novel_studio.ui_qml import bootstrap
from ai_novel_studio.ui_qml.bridge.codex_session_bridge import CodexSessionController
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import MockNovelStudioFacade

from .test_qml_shell import _create_temp_project
from .test_writer_input_review import find


@pytest.fixture
def default_ui(tmp_path, qtbot):
    root = _create_temp_project(tmp_path / "novel")

    class Port:
        has_saved_thread = False

        def close(self):
            pass

    controller = CodexSessionController(session_factory=lambda _: Port())
    facade = MockNovelStudioFacade(codex_controller=controller)
    assert facade.openProject(str(root)) == ""
    facade.setReduceMotion(True)
    facade.toggleAiDrawer(True)
    engine = QQmlApplicationEngine()
    _, theme = bootstrap.register_frontend_types(engine, facade)
    engine.load(QUrl.fromLocalFile(str(bootstrap.app_qml_path())))
    window = engine.rootObjects()[0]
    assert isinstance(window, QQuickWindow)
    qtbot.waitUntil(lambda: find(window.contentItem(), "creativeAgentPanel") is not None)
    yield window, facade, controller
    facade.closeProject()
    engine.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_production_bootstrap_does_not_create_legacy_harness(qtbot, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("legacy Harness must not be created at default startup")

    monkeypatch.setattr(bootstrap, "HarnessAgentPort", forbidden)
    engine = QQmlApplicationEngine()
    try:
        facade, theme = bootstrap.register_frontend_types(engine)
        assert facade._real_agent is None
        assert facade.codexEnabled
        facade._codex.close()
    finally:
        engine.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_missing_outline_hint_opens_editor_and_hides_after_registration(default_ui, qtbot):
    window, facade, _ = default_ui
    hint = find(window.contentItem(), "outlineWorkflowHint")
    assert hint is not None and hint.property("visible")
    QMetaObject.invokeMethod(find(window.contentItem(), "openWorkflowOutlineButton"), "clicked")
    assert facade.activeNav == "outline"
    assert facade._outline.newDocument("全书")
    facade._outline.edit("# 全书\n事件 1 的详细原文。")
    assert facade._outline.flush()
    qtbot.waitUntil(lambda: not hint.property("visible"))


def test_legacy_views_are_grouped_but_remain_reachable(default_ui):
    window, facade, _ = default_ui
    nav = find(window.contentItem(), "nav-library")
    assert nav.property("text") == "旧资料"
    assert find(window.contentItem(), "nav-advanced") is None
    facade.setActiveNav("library")
    button = find(window.contentItem(), "openLegacyAdvancedButton")
    assert button is not None and button.property("visible")
    QMetaObject.invokeMethod(button, "clicked")
    assert facade.activeNav == "advanced"
    QMetaObject.invokeMethod(find(window.contentItem(), "backToLegacyLibraryButton"), "clicked")
    assert facade.activeNav == "library"


def test_old_generation_entry_points_route_to_codex_not_harness(default_ui, monkeypatch):
    _, facade, controller = default_ui
    sent = []
    monkeypatch.setattr(controller, "start", lambda text, **kw: sent.append((text, kw)))
    facade.requestDraft()
    facade.startAgentTurn("展开下一场景")
    assert len(sent) == 2
    assert "$novel-edit" in sent[0][1]["request_text"]
    assert sent[1][0] == "展开下一场景"
    assert not facade._agent_busy


def test_legacy_audit_record_cannot_be_written_through_codex_facade(default_ui, tmp_path, qtbot):
    from .test_readonly_views import create_project_with_audit

    window, facade, _ = default_ui
    root = create_project_with_audit(tmp_path / "legacy-audit")
    assert facade.openProject(str(root)) == ""
    finding = facade._audits_model.audit_at_row(0)
    assert finding is not None
    repository = AuditRepository(facade._workspace.project)
    before = repository.get_finding(finding.id)
    facade.setActiveNav("advanced")
    find(window.contentItem(), "legacyAdvancedTabs").setProperty("currentIndex", 4)
    qtbot.waitUntil(lambda: find(window.contentItem(), "ignoreAuditButton") is not None)
    assert not find(window.contentItem(), "ignoreAuditButton").property("visible")
    assert not find(window.contentItem(), "falsePositiveAuditButton").property("visible")
    facade.updateAuditFindingStatus(0, "REJECTED")
    assert repository.get_finding(finding.id) == before
