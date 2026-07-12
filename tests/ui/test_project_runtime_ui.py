from pathlib import Path

from pytestqt.qtbot import QtBot

from ai_novel_studio.application.model_tasks import StyleAuditFinding, StyleAuditResult
from ai_novel_studio.application.project_runtime import ProjectRuntime
from ai_novel_studio.domain.audit import AuditFindingStatus, AuditTargetKind
from ai_novel_studio.domain.generation import BriefStatus, CreationMode, GenerationStatus
from ai_novel_studio.domain.memory import Authority, ReviewStatus, SummaryLevel
from ai_novel_studio.infrastructure.storage.audit_repository import AuditRepository
from ai_novel_studio.infrastructure.storage.chapter_brief_repository import (
    ChapterBriefRepository,
)
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.chapter_requirement_repository import (
    ChapterRequirementRepository,
)
from ai_novel_studio.infrastructure.storage.character_memory_repository import (
    CharacterMemoryRepository,
)
from ai_novel_studio.infrastructure.storage.generation_repository import GenerationRepository
from ai_novel_studio.infrastructure.storage.summary_repository import SummaryRepository
from ai_novel_studio.ui.main_window import MainWindow
from ai_novel_studio.ui.pages.project_welcome import ProjectWelcome
from tests.integration.application.test_project_runtime import FakeModelRuntime as GatewayRuntime


class _Signal:
    def connect(self, _callback):  # type: ignore[no-untyped-def]
        return None


class _Coordinator:
    def __init__(self) -> None:
        self.chat_chunk = _Signal()
        self.chat_finished = _Signal()
        self.requirement_ready = _Signal()
        self.brief_ready = _Signal()
        self.audit_ready = _Signal()
        self.task_failed = _Signal()
        self.usage_changed = _Signal()

    def start_audit(self, manuscript, rules, output_token_limit):  # type: ignore[no-untyped-def]
        self.last_audit = (manuscript, rules, output_token_limit)


class UiModelRuntime(GatewayRuntime):
    def __init__(self, tmp_path: Path) -> None:
        super().__init__(tmp_path)
        self.coordinator = _Coordinator()
        self.settings_controller = None


def _project_with_chapter(root: Path, model_root: Path) -> tuple[ProjectRuntime, str]:
    runtime = ProjectRuntime.create(root, "UI Runtime Novel", UiModelRuntime(model_root))
    chapter = ChapterRepository(runtime.project).create_chapter(
        runtime.project.list_volumes()[0].id,
        "Opening",
        "第1章",
        "原始正文",
    )
    requirements = ChapterRequirementRepository(runtime.project)
    requirements.get_or_create(chapter.id)
    requirements.update(
        chapter.id,
        "当前章要求",
        is_locked=False,
        expected_revision=0,
    )
    runtime.close()
    return ProjectRuntime.open(root, UiModelRuntime(model_root)), chapter.id


def test_project_welcome_emits_create_and_open_requests(qtbot: QtBot, tmp_path: Path) -> None:
    widget = ProjectWelcome()
    qtbot.addWidget(widget)
    seen: list[tuple[str, object, object]] = []
    widget.create_project_requested.connect(
        lambda root, title: seen.append(("create", root, title))
    )
    widget.open_project_requested.connect(lambda root: seen.append(("open", root, None)))

    widget.request_create_project(tmp_path / "novel", "Novel")
    widget.request_open_project(tmp_path / "novel")

    assert seen == [
        ("create", tmp_path / "novel", "Novel"),
        ("open", tmp_path / "novel", None),
    ]


def test_project_welcome_buttons_open_dialogs_and_emit_requests(
    qtbot: QtBot, tmp_path: Path, monkeypatch
) -> None:
    widget = ProjectWelcome()
    qtbot.addWidget(widget)
    seen: list[tuple[str, object, object]] = []
    widget.create_project_requested.connect(
        lambda root, title: seen.append(("create", root, title))
    )
    widget.open_project_requested.connect(lambda root: seen.append(("open", root, None)))
    widget.import_file_requested.connect(lambda source: seen.append(("import", source, None)))

    monkeypatch.setattr(
        "ai_novel_studio.ui.pages.project_welcome.QFileDialog.getExistingDirectory",
        lambda *args, **kwargs: str(tmp_path / "created"),
    )
    monkeypatch.setattr(
        "ai_novel_studio.ui.pages.project_welcome.QInputDialog.getText",
        lambda *args, **kwargs: ("Created Novel", True),
    )
    widget.create_button.click()

    monkeypatch.setattr(
        "ai_novel_studio.ui.pages.project_welcome.QFileDialog.getExistingDirectory",
        lambda *args, **kwargs: str(tmp_path / "opened"),
    )
    widget.open_button.click()

    monkeypatch.setattr(
        "ai_novel_studio.ui.pages.project_welcome.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(tmp_path / "draft.md"), "Markdown"),
    )
    widget.import_button.click()

    assert seen == [
        ("create", tmp_path / "created", "Created Novel"),
        ("open", tmp_path / "opened", None),
        ("import", tmp_path / "draft.md", None),
    ]


def test_main_window_starts_blank_until_project_is_opened(qtbot: QtBot) -> None:
    window = MainWindow(model_runtime=UiModelRuntime(Path.cwd()))
    qtbot.addWidget(window)

    assert window.project_runtime is None
    assert window.project_welcome.isVisibleTo(window)
    assert "雾港来信" not in window.top_bar.project_label.text()
    assert window.chapter_sidebar.chapter_tree.topLevelItemCount() == 0
    assert window.manuscript_panel.editor.toPlainText() == ""
    assert window.manuscript_panel.chapter_requirement.toPlainText() == ""


def test_main_window_opens_real_project_and_loads_chapter(qtbot: QtBot, tmp_path: Path) -> None:
    runtime, chapter_id = _project_with_chapter(tmp_path / "novel", tmp_path)
    window = MainWindow(model_runtime=UiModelRuntime(tmp_path), project_runtime=runtime)
    qtbot.addWidget(window)

    window.load_project_chapter(chapter_id)

    assert window.current_chapter_id == chapter_id
    assert window.manuscript_panel.editor.toPlainText() == "原始正文"
    assert window.manuscript_panel.chapter_requirement.toPlainText() == "当前章要求"
    assert window.chapter_sidebar.chapter_tree.topLevelItemCount() == 1


def test_project_chat_history_is_restored_and_budgeted_after_reopen(
    qtbot: QtBot, tmp_path: Path
) -> None:
    root = tmp_path / "novel"
    runtime, _chapter_id = _project_with_chapter(root, tmp_path)
    window = MainWindow(model_runtime=UiModelRuntime(tmp_path), project_runtime=runtime)
    qtbot.addWidget(window)
    assert window.chat_session_id is not None
    window.plot_chat_panel.append_external_message("user", "保留旧港伏笔")
    window.persist_chat_message("user", "保留旧港伏笔")
    window.plot_chat_panel.append_external_message("assistant", "已记录，不提前揭晓")
    window.persist_chat_message("assistant", "已记录，不提前揭晓")
    runtime.close()

    reopened = ProjectRuntime.open(root, UiModelRuntime(tmp_path))
    restored_window = MainWindow(model_runtime=UiModelRuntime(tmp_path), project_runtime=reopened)
    qtbot.addWidget(restored_window)

    assert [item.text for item in restored_window.plot_chat_panel.message_snapshot()] == [
        "保留旧港伏笔",
        "已记录，不提前揭晓",
    ]
    assert [item.content for item in restored_window._conversation_messages()] == [
        "保留旧港伏笔",
        "已记录，不提前揭晓",
    ]


def test_plot_conversation_receives_pre_chapter_memory(qtbot: QtBot, tmp_path: Path) -> None:
    runtime, first_id = _project_with_chapter(tmp_path / "novel", tmp_path)
    chapters = ChapterRepository(runtime.project)
    second = chapters.create_chapter(
        runtime.project.list_volumes()[0].id,
        "Second",
        "第2章",
        "第二章正文",
    )
    SummaryRepository(runtime.project).add_human_summary(
        SummaryLevel.CHAPTER,
        first_id,
        "第一章已经确认的剧情",
        (first_id,),
        authority=Authority.USER_CONFIRMED,
        review_status=ReviewStatus.APPROVED,
    )
    window = MainWindow(model_runtime=UiModelRuntime(tmp_path), project_runtime=runtime)
    qtbot.addWidget(window)
    window.load_project_chapter(second.id)

    messages = window._conversation_messages()

    assert messages[0].role == "system"
    assert "第一章已经确认的剧情" in messages[0].content
    assert "【已审查" in messages[0].content


def test_main_window_saves_current_real_chapter(qtbot: QtBot, tmp_path: Path) -> None:
    runtime, chapter_id = _project_with_chapter(tmp_path / "novel", tmp_path)
    window = MainWindow(model_runtime=UiModelRuntime(tmp_path), project_runtime=runtime)
    qtbot.addWidget(window)
    window.load_project_chapter(chapter_id)

    window.manuscript_panel.editor.setPlainText("人工修改正文")
    window.manuscript_panel.chapter_requirement.setPlainText("人工修改要求")
    window.save_current_chapter()

    repository = ChapterRepository(runtime.project)
    assert repository.read_content(chapter_id) == "人工修改正文"
    assert repository.list_versions(chapter_id)
    reloaded = runtime.workspace.load_chapter(chapter_id)
    assert reloaded.requirement_content == "人工修改要求"


def test_agent_mode_uses_current_project_chapter_id(qtbot: QtBot, tmp_path: Path) -> None:
    runtime, chapter_id = _project_with_chapter(tmp_path / "novel", tmp_path)
    window = MainWindow(model_runtime=UiModelRuntime(tmp_path), project_runtime=runtime)
    qtbot.addWidget(window)
    window.load_project_chapter(chapter_id)
    window.plot_chat_panel.agent_mode_toggle.setChecked(True)

    window.plot_chat_panel.composer.setPlainText("请检索前文")
    window.plot_chat_panel.send_button.click()

    assert window.last_agent_result is not None
    assert runtime.agent_repository.list_turns(window.last_agent_result.run_id)


def test_main_window_builds_memory_for_open_project(qtbot: QtBot, tmp_path: Path) -> None:
    runtime, chapter_id = _project_with_chapter(tmp_path / "novel", tmp_path)
    window = MainWindow(model_runtime=UiModelRuntime(tmp_path), project_runtime=runtime)
    qtbot.addWidget(window)

    window.build_project_memory()
    qtbot.waitUntil(
        lambda: not window.memory_build_coordinator.is_running,
        timeout=3_000,
    )
    window.open_memory_window()

    assert SummaryRepository(runtime.project).list_all()
    with runtime.project.database.connect() as connection:
        indexed = connection.execute(
            "SELECT 1 FROM memory_documents WHERE source_id = ?",
            (chapter_id,),
        ).fetchone()
    assert indexed is not None
    assert window.memory_window is not None
    assert window.memory_window.tabs.tabText(0) == "压缩前文"


def test_main_window_saves_sidebar_character_state_to_project_memory(
    qtbot: QtBot, tmp_path: Path
) -> None:
    runtime, chapter_id = _project_with_chapter(tmp_path / "novel", tmp_path)
    window = MainWindow(model_runtime=UiModelRuntime(tmp_path), project_runtime=runtime)
    qtbot.addWidget(window)
    window.load_project_chapter(chapter_id)

    window.chapter_sidebar.begin_new_character("林默")
    window.chapter_sidebar.psychology_edit.setPlainText("警惕但克制")
    window.chapter_sidebar.motivation_edit.setPlainText("确认旧信真伪")
    window.chapter_sidebar.goal_edit.setPlainText("进入档案室")
    window.chapter_sidebar.relationships_edit.setPlainText("暂不信任来信者")
    window.chapter_sidebar.recent_edit.setPlainText("刚收到匿名来信")
    window.chapter_sidebar.apply_character_edit()

    repository = CharacterMemoryRepository(runtime.project)
    character = repository.list_characters()[0]
    state = repository.state_before(character.id, chapter_id, inclusive=True)

    assert character.canonical_name == "林默"
    assert state is not None
    assert state.psychology == "警惕但克制"
    assert state.motivation == "确认旧信真伪"
    assert state.current_goal == "进入档案室"
    assert state.relationships == "暂不信任来信者"
    assert state.recent_activity == "刚收到匿名来信"
    assert window.chapter_sidebar.character_feedback_label.text() == (
        "人物状态已保存到当前章节节点。"
    )


def test_open_project_generates_and_accepts_prose_for_selected_chapter(
    qtbot: QtBot, tmp_path: Path
) -> None:
    runtime, chapter_id = _project_with_chapter(tmp_path / "novel", tmp_path)
    window = MainWindow(model_runtime=UiModelRuntime(tmp_path), project_runtime=runtime)
    qtbot.addWidget(window)
    window.load_project_chapter(chapter_id)
    window.manuscript_panel.set_creation_mode(CreationMode.BASIC)

    assert window.manuscript_panel.generate_button.isEnabled()
    window.manuscript_panel.generate_button.click()
    qtbot.waitUntil(
        lambda: window.manuscript_panel.generated_draft_editor.toPlainText() == "模型生成正文",
        timeout=3000,
    )
    qtbot.waitUntil(
        lambda: (
            len(
                GenerationRepository(runtime.project).list_by_statuses(
                    (GenerationStatus.COMPLETED,)
                )
            )
            == 1
        ),
        timeout=3000,
    )

    runs = GenerationRepository(runtime.project).list_by_statuses((GenerationStatus.COMPLETED,))
    assert len(runs) == 1
    assert runs[0].chapter_id == chapter_id

    qtbot.waitUntil(
        lambda: window.manuscript_panel.adopt_draft_button.isEnabled(),
        timeout=3000,
    )
    window.manuscript_panel.adopt_draft_button.click()

    chapter = ChapterRepository(runtime.project).get_chapter(chapter_id)
    assert ChapterRepository(runtime.project).read_content(chapter_id) == "模型生成正文"
    assert window.manuscript_panel.current_chapter_revision == chapter.revision


def test_strict_generation_runs_draft_audit_before_adoption(qtbot: QtBot, tmp_path: Path) -> None:
    runtime, chapter_id = _project_with_chapter(tmp_path / "novel", tmp_path)
    window = MainWindow(model_runtime=UiModelRuntime(tmp_path), project_runtime=runtime)
    qtbot.addWidget(window)
    window.load_project_chapter(chapter_id)
    window.open_brief_dialog()
    assert window.brief_dialog is not None
    window.brief_dialog.freeze_button.click()
    window.manuscript_panel.set_creation_mode(CreationMode.STRICT)

    window.manuscript_panel.generate_button.click()

    qtbot.waitUntil(
        lambda: window.manuscript_panel.generated_draft_editor.toPlainText() == "模型生成正文",
        timeout=3000,
    )
    qtbot.waitUntil(
        lambda: window.manuscript_panel.adopt_draft_button.isEnabled(),
        timeout=3000,
    )
    run = GenerationRepository(runtime.project).list_by_statuses((GenerationStatus.COMPLETED,))[0]
    audits = AuditRepository(runtime.project).list_runs_for_target(
        target_kind=AuditTargetKind.GENERATED_DRAFT,
        target_id=run.id,
    )
    assert len(audits) == 2
    assert all(audit.mode == CreationMode.STRICT for audit in audits)
    assert {audit.prompt_version for audit in audits} == {
        "deterministic-audit-v1",
        "model-audit-ui-v1",
    }
    assert "均通过" in window.manuscript_panel.pipeline_status_label.text()

    window.manuscript_panel.adopt_draft_button.click()

    assert ChapterRepository(runtime.project).read_content(chapter_id) == "模型生成正文"


def test_strict_generation_stays_locked_when_model_audit_reports_error(
    qtbot: QtBot, tmp_path: Path
) -> None:
    runtime, chapter_id = _project_with_chapter(tmp_path / "novel", tmp_path)
    window = MainWindow(model_runtime=UiModelRuntime(tmp_path), project_runtime=runtime)
    qtbot.addWidget(window)
    window.load_project_chapter(chapter_id)
    window.open_brief_dialog()
    assert window.brief_dialog is not None
    window.brief_dialog.freeze_button.click()
    window.manuscript_panel.set_creation_mode(CreationMode.STRICT)

    class BlockingAuditService:
        def audit_style(self, manuscript, rules, output_token_limit):  # type: ignore[no-untyped-def]
            return StyleAuditResult(
                "发现阻断问题",
                (
                    StyleAuditFinding(
                        "CHARACTER",
                        "人物行为与既有动机冲突",
                        "模型生成正文",
                        "ERROR",
                    ),
                ),
            )

    runtime.generation_runtime.audit_coordinator.service = BlockingAuditService()
    window.manuscript_panel.generate_button.click()

    qtbot.waitUntil(
        lambda: "阻断问题" in window.manuscript_panel.pipeline_status_label.text(),
        timeout=3000,
    )

    assert not window.manuscript_panel.adopt_draft_button.isEnabled()
    assert ChapterRepository(runtime.project).read_content(chapter_id) == "原始正文"


def test_real_project_brief_can_be_saved_and_frozen_from_dialog(
    qtbot: QtBot, tmp_path: Path
) -> None:
    runtime, chapter_id = _project_with_chapter(tmp_path / "novel", tmp_path)
    window = MainWindow(model_runtime=UiModelRuntime(tmp_path), project_runtime=runtime)
    qtbot.addWidget(window)
    window.load_project_chapter(chapter_id)

    window.open_brief_dialog()

    dialog = window.brief_dialog
    assert dialog is not None
    assert dialog.brief_status() == "草稿"
    assert dialog.section_editors["戏剧功能"].toPlainText() == "当前章要求"

    dialog.section_editors["戏剧功能"].setPlainText("本章推动主角接受委托")
    dialog.freeze_button.click()

    frozen = ChapterBriefRepository(runtime.project).list_for_chapter(
        chapter_id, BriefStatus.FROZEN
    )
    assert len(frozen) == 1
    assert frozen[0].dramatic_purpose == "本章推动主角接受委托"
    assert dialog.brief_status() == "已冻结"

    window.manuscript_panel.set_creation_mode(CreationMode.STANDARD)
    assert window.manuscript_panel.generate_button.isEnabled()


def test_changed_requirement_reports_brief_error_and_can_recompile(
    qtbot: QtBot, tmp_path: Path
) -> None:
    runtime, chapter_id = _project_with_chapter(tmp_path / "novel", tmp_path)
    window = MainWindow(model_runtime=UiModelRuntime(tmp_path), project_runtime=runtime)
    qtbot.addWidget(window)
    window.load_project_chapter(chapter_id)
    window.open_brief_dialog()
    dialog = window.brief_dialog
    assert dialog is not None

    requirements = ChapterRequirementRepository(runtime.project)
    current = requirements.get(chapter_id)
    requirements.update(
        chapter_id,
        "变更后的当前章要求",
        is_locked=False,
        expected_revision=current.revision,
    )

    dialog.freeze_button.click()

    assert "来源" in dialog.warning_label.text()
    assert not ChapterBriefRepository(runtime.project).list_for_chapter(
        chapter_id, BriefStatus.FROZEN
    )

    dialog.recompile_button.click()

    assert dialog.section_editors["戏剧功能"].toPlainText() == "变更后的当前章要求"
    assert dialog.brief_status() == "草稿"


def test_deterministic_audit_uses_and_persists_current_project_chapter(
    qtbot: QtBot, tmp_path: Path
) -> None:
    runtime, chapter_id = _project_with_chapter(tmp_path / "novel", tmp_path)
    window = MainWindow(model_runtime=UiModelRuntime(tmp_path), project_runtime=runtime)
    qtbot.addWidget(window)
    window.load_project_chapter(chapter_id)
    repeated = (
        "这是一段用于检查重复问题的正文，它足够长并且会在本章中完整重复出现，"
        "同时保留完全相同的文字证据。"
    )
    window.manuscript_panel.editor.setPlainText(f"{repeated}\n\n{repeated}")
    window.save_current_chapter()
    window.open_audit_window()

    window.request_deterministic_audit()

    runs = AuditRepository(runtime.project).list_runs_for_target(
        target_kind=AuditTargetKind.FORMAL_CHAPTER,
        target_id=chapter_id,
    )
    assert len(runs) == 1
    findings = AuditRepository(runtime.project).list_findings(runs[0].id)
    assert findings
    assert any(item.evidence == repeated for item in findings)
    assert window.audit_window is not None
    assert any(
        window.audit_window.deterministic_table.item(row, 2).text() == repeated
        for row in range(window.audit_window.deterministic_table.rowCount())
    )

    window.audit_window.evidence_activated.emit(repeated)

    assert window.manuscript_panel.editor.textCursor().selectedText() == repeated

    window.audit_window.deterministic_table.selectRow(0)
    window.audit_window.false_positive_button.click()

    assert AuditRepository(runtime.project).get_finding(findings[0].id).status == (
        AuditFindingStatus.FALSE_POSITIVE
    )
    assert window.audit_window.deterministic_table.item(0, 3).text() == "FALSE_POSITIVE"


def test_validated_repair_is_applied_only_after_user_confirmation(
    qtbot: QtBot, tmp_path: Path
) -> None:
    runtime, chapter_id = _project_with_chapter(tmp_path / "novel", tmp_path)
    window = MainWindow(model_runtime=UiModelRuntime(tmp_path), project_runtime=runtime)
    qtbot.addWidget(window)
    window.load_project_chapter(chapter_id)
    repeated = (
        "这是一段用于检查重复问题的正文，它足够长并且会在本章中完整重复出现，"
        "同时保留完全相同的文字证据。"
    )
    original = f"{repeated}\n\n{repeated}"
    replacement = "这是经过人工审查的局部替换文本。"
    window.manuscript_panel.editor.setPlainText(original)
    window.save_current_chapter()
    window.open_audit_window()
    window.request_deterministic_audit()
    assert window.audit_window is not None
    window.audit_window.deterministic_table.selectRow(0)
    window.audit_window.repair_replacement.setPlainText(replacement)

    window.audit_window.repair_button.click()

    proposal = AuditRepository(runtime.project).get_repair_proposal(
        window.audit_window.current_proposal_id
    )
    assert proposal.status.value == "VALIDATED"
    assert ChapterRepository(runtime.project).read_content(chapter_id) == original
    assert "--- 原文" in window.audit_window.repair_diff.toPlainText()

    window.manuscript_panel.editor.appendPlainText("未保存的人工作者修改")
    window.audit_window.apply_repair_button.click()

    assert ChapterRepository(runtime.project).read_content(chapter_id) == original
    assert "未保存修改" in window.audit_window.repair_status_label.text()

    window.manuscript_panel.editor.setPlainText(original)
    window.audit_window.apply_repair_button.click()

    assert ChapterRepository(runtime.project).read_content(chapter_id) == (
        f"{replacement}\n\n{repeated}"
    )
    assert ChapterRepository(runtime.project).list_versions(chapter_id)
    assert AuditRepository(runtime.project).list_provenance(chapter_id)
    assert window.manuscript_panel.editor.toPlainText().startswith(replacement)


def test_model_audit_result_is_persisted_and_reloaded_for_project_chapter(
    qtbot: QtBot, tmp_path: Path
) -> None:
    model_runtime = UiModelRuntime(tmp_path)
    runtime, chapter_id = _project_with_chapter(tmp_path / "novel", tmp_path)
    window = MainWindow(model_runtime=model_runtime, project_runtime=runtime)
    qtbot.addWidget(window)
    window.load_project_chapter(chapter_id)
    window.open_audit_window()

    window.request_model_audit()
    window.apply_model_audit(
        StyleAuditResult(
            "存在人物声音问题",
            (StyleAuditFinding("声音", "人物声音区分不足", "原文证据句", "中"),),
        )
    )

    runs = AuditRepository(runtime.project).list_runs_for_target(
        target_kind=AuditTargetKind.FORMAL_CHAPTER,
        target_id=chapter_id,
    )
    model_findings = tuple(
        finding
        for run in runs
        for finding in AuditRepository(runtime.project).list_findings(run.id)
        if finding.source.value == "MODEL"
    )
    assert len(model_findings) == 1
    assert model_findings[0].evidence == "原文证据句"

    assert window.audit_window is not None
    window.audit_window.close()
    window.audit_window = None
    window.open_audit_window()

    assert window.audit_window.model_table.item(0, 2).text() == "原文证据句"
