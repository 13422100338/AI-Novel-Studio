"""Open the production window with an owned test novel for native UI acceptance."""

import os
import sys
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QTimer

from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository
from ai_novel_studio.ui_qml import bootstrap

root = Path(os.environ["LOCALAPPDATA"]) / "Temp" / ("novel-ui-" + uuid4().hex[:8])
project = ProjectRepository.create(root / "novel", "Codex 工作台验收")
ChapterRepository(project).create_chapter(
    project.list_volumes()[0].id,
    "海港钟楼",
    content="叶舟在海港钟楼发现了银色钥匙。",
)
original_register = bootstrap.register_frontend_types


def register(engine, *args, **kwargs):
    facade, theme = original_register(engine, *args, **kwargs)
    error = facade.openProject(str(root / "novel"))
    if error:
        raise RuntimeError(error)

    def prepare():
        engine.rootObjects()[0].setTitle("AI Novel Studio · Codex 工作台验收")
        facade.toggleAiDrawer(True)
        if "--settings" in sys.argv:
            facade.setActiveNav("settings")
        if "--chat" in sys.argv:
            facade.startAssistantChat(
                "请调用小说 MCP 读取当前章节，回答章节标题和钥匙颜色，不超过两句话。"
            )
        print("NATIVE_WORKBENCH_READY", root, flush=True)

    QTimer.singleShot(1000, prepare)
    return facade, theme


bootstrap.register_frontend_types = register
raise SystemExit(bootstrap.main(["codex-workbench-preview"]))
