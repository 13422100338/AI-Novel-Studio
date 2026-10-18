"""Open an owned QA novel in the production shell; --live exercises the saved model routes.

No author project is opened. Codex session files and generated checkpoints belong
to this newly created temporary fixture. The report contains no credentials.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QTimer

from ai_novel_studio.application.codex_session_service import CodexSessionService
from ai_novel_studio.application.novel_read_service import NovelEditorSnapshot
from ai_novel_studio.infrastructure.codex.session_index import CodexSessionIndex
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.chapter_requirement_repository import (
    ChapterRequirementRepository,
)
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.ui_qml import bootstrap
from ai_novel_studio.ui_qml.bridge.codex_controls_bridge import default_preferences_store
from ai_novel_studio.ui_qml.bridge.codex_session_bridge import CodexSessionController
from ai_novel_studio.ui_qml.bridge.mock_novel_studio_facade import MockNovelStudioFacade


def headless(
    root, project, chapter, requirement, chapters, body, live, read_all=False, selected_polish=False
):
    app = QCoreApplication(["novel-chat-writer-headless-qa"])

    def session_factory(project_id):
        return CodexSessionService(
            project_id,
            CodexSessionIndex(root / "sessions" / f"{project_id}.json"),
            root / "codex-workspaces",
            preferences=default_preferences_store().load,
        )

    controller = CodexSessionController(session_factory=session_factory)
    controller.bind_project(project.project.id, project)
    selected = body.splitlines()[0] if selected_polish else ""
    skill_inputs = []
    skill_catalog = []
    generation_checks = {}
    if selected_polish:
        from ai_novel_studio.infrastructure.codex.app_server import CodexAppServer

        original_request = CodexAppServer.request

        def recorded_request(client, method, params):
            response = original_request(client, method, params)
            if method == "turn/start":
                skill_inputs.extend(
                    item["name"] for item in params["input"] if item["type"] == "skill"
                )
            if method == "skills/list":
                skill_catalog.extend(
                    skill["name"]
                    for entry in response.get("data", [])
                    for skill in entry.get("skills", [])
                    if skill.get("name") == "novel-edit"
                )
            return response

        CodexAppServer.request = recorded_request
        original_event = controller._on_event

        def recorded_event(epoch, method, params):
            item = params.get("item", {})
            if item.get("tool") == "generate_novel_draft":
                arguments = item.get("arguments", {})
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                instruction = str(arguments.get("instruction", ""))
                generation_checks[item.get("id", "writer")] = {
                    "contains_complete_selection": selected in instruction,
                    "contains_scope_limit": "选文" in instruction,
                }
            original_event(epoch, method, params)

        controller._on_event = recorded_event
    controller.update_editor(
        NovelEditorSnapshot(chapter.id, chapter.title, chapter.revision, body, False, selected)
    )
    sent = False

    def finish(timeout=False):
        if not timeout and (not sent or controller.is_busy):
            return
        rows = [row for row in controller._model.items() if row.kind == "writer_task"]
        result = {
            "project": str(root),
            "without_console": sys.stdout is None and sys.stderr is None,
            "chat_status": controller.status_text,
            "timeout": timeout,
            "formal_unchanged": chapters.read_content(chapter.id) == body,
            "requirement_unchanged": ChapterRequirementRepository(project).get(chapter.id)
            == requirement,
            "writer_cards": [
                {
                    "status": row.state,
                    "length": len(row.draft_text),
                    "metadata": json.loads(row.data),
                }
                for row in rows
            ],
            "read_summaries": [
                row.text for row in controller._model.items() if row.label == "小说资料汇总"
            ],
            "read_tools": list(controller._read_progress.calls.values()),
            "chapters_read": len(controller._read_progress.chapters),
            "selection": selected,
            "native_skill_inputs": skill_inputs,
            "native_skill_catalog": skill_catalog,
            "generation_scope": list(generation_checks.values()),
            "tools": [row.label for row in controller._model.items() if row.kind == "tool_call"],
            "messages": [
                row.text
                for row in controller._model.items()
                if row.kind in {"assistant_text", "warning", "error"}
            ],
        }
        (root / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        timer.stop()
        controller.close()
        success = bool(
            not timeout
            and result["formal_unchanged"]
            and result["requirement_unchanged"]
            and (
                not selected_polish
                or (
                    skill_inputs == ["novel-edit"]
                    and "novel-edit" in skill_catalog
                    and generation_checks
                    and all(all(check.values()) for check in generation_checks.values())
                )
            )
            and (
                not live
                or (
                    read_all
                    and len(controller._read_progress.chapters) == len(chapters.list_chapters())
                )
                or any(row.state == "COMPLETED" and row.draft_text for row in rows)
            )
        )
        app.exit(0 if success else 1)

    def start():
        nonlocal sent
        sent = True
        if live:
            if selected_polish:
                from ai_novel_studio.application.novel_writing_commands import writing_request

                controller.start(
                    "/润色 仅润色选文，候选不超过150字。",
                    request_text=writing_request("/润色 仅润色选文，候选不超过150字。")[1],
                )
            elif read_all:
                controller.start(
                    "请一次批量读取这部小说所有章节的正式正文，告诉我总章数和最后一章最后一句。"
                    "只读，不修改资料、不调用写作模型或联网。"
                )
            else:
                controller.start(
                    "请读取当前章要求，调用独立正文写作模型生成约100字候选草稿，"
                    "描写灯塔门打开时的场景。不改正式正文或章要求，完成后简短告知。"
                )

    timer = QTimer()
    timer.setInterval(250)
    timer.timeout.connect(finish)
    timer.start()
    QTimer.singleShot(0, start)
    QTimer.singleShot(240_000, lambda: finish(True))
    return app.exec()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--live", action="store_true", help="Send a short task to existing Codex and writing routes"
    )
    parser.add_argument(
        "--headless", action="store_true", help="Validate without opening or controlling a window"
    )
    parser.add_argument(
        "--read-all", action="store_true", help="Use a 34-chapter bulk reading task"
    )
    parser.add_argument(
        "--selected-polish",
        action="store_true",
        help="Exercise native writing skill on a quoted selection",
    )
    parser.add_argument(
        "--qa-root", type=Path, help="Use a new, nonexistent directory for owned test data"
    )
    args = parser.parse_args()
    if args.selected_polish and not args.headless:
        parser.error("--selected-polish requires --headless")
    root = args.qa_root or Path(tempfile.mkdtemp(prefix="novel-chat-writer-qa-"))
    if args.qa_root:
        root.mkdir(parents=True, exist_ok=False)
    project = ProjectRepository.create(root / "novel", "雾港来信 · 界面验收")
    chapters = ChapterRepository(project)
    body = (
        "清晨的雾港还在灰蓝色的光影里。海风带着盐与铁锈的味道，"
        "林默沿着堤岸走向灯塔。桥下的水拍着木桩，像在把一段无人辨认的话重新说一遍。\n\n"
    )
    titles = (
        tuple(f"港口第{i}章" for i in range(1, 35))
        if args.read_all
        else ("雾港的清晨", "潮汐声", "灯塔看守人", "旧信与火")
    )
    for number, title in enumerate(titles, 1):
        chapter = chapters.create_chapter(
            project.list_volumes()[0].id, title, str(number), body * 4
        )
    requirements = ChapterRequirementRepository(project)
    empty = requirements.get_or_create(chapter.id)
    requirement = requirements.update(
        chapter.id,
        "写约100字灯塔门打开时的场景，保持悬念，不揭晓来信者。",
        is_locked=True,
        expected_revision=empty.revision,
    )
    if args.headless:
        return headless(
            root,
            project,
            chapter,
            requirement,
            chapters,
            body * 4,
            args.live,
            args.read_all,
            args.selected_polish,
        )
    original_register = bootstrap.register_frontend_types
    runtime = {}

    def register(engine, *values, **kwargs):
        def session_factory(project_id):
            return CodexSessionService(
                project_id,
                CodexSessionIndex(root / "sessions" / f"{project_id}.json"),
                root / "codex-workspaces",
                preferences=default_preferences_store().load,
            )

        controller = CodexSessionController(engine, session_factory=session_factory)
        facade = MockNovelStudioFacade(codex_controller=controller)
        facade.openProject(str(project.layout.root))
        facade.selectChapter(
            4
        )  # Row zero is the volume header; the last fixture chapter is row four.
        facade.toggleAiDrawer(True)
        result = original_register(engine, facade, **kwargs)
        runtime.update(engine=engine, facade=facade, controller=controller)
        QTimer.singleShot(
            1000, lambda: engine.rootObjects()[0].setTitle("AI Novel Studio · 聊天写作验收")
        )
        if args.live:

            def send_task():
                runtime["sent"] = True
                facade.startAssistantChat(
                    "请读取当前章节要求，调用独立正文写作模型生成约100字候选草稿，描写灯塔门打开时的场景。"
                    "不改动正式正文或章要求；完成后简短告诉我查看任务卡片。"
                )

            QTimer.singleShot(2500, send_task)
        timer.start()
        return result

    def report():
        controller = runtime.get("controller")
        if controller is None:
            return
        rows = [row for row in controller._model.items() if row.kind == "writer_task"]
        if args.live and (controller.is_busy or not runtime.get("sent")):
            return
        result = {
            "project": str(root),
            "chat_status": controller.status_text,
            "formal_unchanged": chapters.read_content(chapter.id) == body * 4,
            "requirement_unchanged": requirements.get(chapter.id) == requirement,
            "writer_cards": [
                {
                    "status": row.state,
                    "length": len(row.draft_text),
                    "metadata": json.loads(row.data),
                }
                for row in rows
            ],
        }
        (root / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(result, ensure_ascii=False), flush=True)
        timer.stop()

    bootstrap.register_frontend_types = register
    timer = QTimer()
    timer.setInterval(1000)
    timer.timeout.connect(report)
    print("QA_ROOT=" + str(root), flush=True)
    return bootstrap.main(["AI Novel Studio QA"])


if __name__ == "__main__":
    raise SystemExit(main())
