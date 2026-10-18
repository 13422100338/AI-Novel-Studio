"""Live acceptance using a newly created test novel and the signed-in Codex account.

Uses an isolated preferences/index directory, never an author's existing novel.
Run with --image PATH to also validate image input. Calls consume account usage.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from uuid import uuid4

from ai_novel_studio.application.codex_controls_service import CodexControlsService
from ai_novel_studio.application.codex_session_service import CodexSessionService
from ai_novel_studio.application.novel_read_service import NovelEditorSnapshot, NovelReadService
from ai_novel_studio.infrastructure.codex.app_server import CodexConnectionError
from ai_novel_studio.infrastructure.codex.preferences import CodexPreferencesStore
from ai_novel_studio.infrastructure.codex.session_index import CodexSessionIndex
from ai_novel_studio.infrastructure.storage.chapter_repository import ChapterRepository
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path)
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--sessions-only", action="store_true")
    parser.add_argument("--material-only", action="store_true")
    args = parser.parse_args()
    root = Path(os.environ["LOCALAPPDATA"]) / "Temp" / ("novel-live-" + uuid4().hex[:8])
    root.mkdir()
    store = CodexPreferencesStore(root / "preferences.json")
    controls = CodexControlsService(store, root / "catalog")
    catalog = controls.refresh()
    print("CATALOG", len(catalog.models), catalog.preferences.model, flush=True)
    model = catalog.preferences.model
    choice = next(item for item in catalog.models if item.model == model)
    effort = "low" if "low" in choice.efforts else choice.default_effort
    controls.choose(choice.model, effort, True)
    book = ProjectRepository.create(root / "novel", "工作台能力验收")
    chapter = ChapterRepository(book).create_chapter(
        book.list_volumes()[0].id,
        "海港钟楼",
        content="叶舟在海港钟楼发现了银色钥匙。",
    )
    reader = NovelReadService(book)
    reader.update_editor(
        NovelEditorSnapshot(
            chapter.id,
            chapter.title,
            chapter.revision,
            "待审阅的作者结尾：钥匙打不开门。",
            True,
            "钥匙",
        )
    )
    port = CodexSessionService(
        book.project.id,
        CodexSessionIndex(root / "sessions.json"),
        root / "workspace",
        preferences=store.load,
    )
    port.bind_novel(reader)
    events: list[tuple[str, dict]] = []
    answers: dict[str, str] = {}

    def event(method, params):
        events.append((method, params))
        if method in {"item/started", "item/completed"}:
            item = params.get("item", {})
            if item.get("type") in {"mcpToolCall", "webSearch"}:
                print(
                    "TOOL",
                    item.get("type"),
                    item.get("tool", "web"),
                    item.get("status"),
                    flush=True,
                )

    try:
        port.restore()
        print("MCP_CONNECTED", bool(port._mcp), flush=True)
        if args.metadata_only:
            return
        if args.sessions_only:
            port.send("请仅回复：会话验收", lambda *_: None)
            first = port.thread_id
            port.restore(fork=True)
            port.restore(thread_id=first)
            port.restore(new=True)
            port.send("请仅回复：新会话验收", lambda *_: None)
            print("SESSION_OPERATIONS_PASSED", len(port.sessions), flush=True)
            return
        text = root / "资料.md"
        text.write_text("作者附加设定：银色钥匙的暗号是潮汐。", encoding="utf-8")
        attachments = (text,) + ((args.image,) if args.image else ())
        if args.material_only:
            status = port.send(
                "请阅读本轮文字附件，回答银色钥匙的暗号。"
                + ("再直接读取图片，回答模型设置页面的 Base URL。" if args.image else "")
                + "不调用工具，只给两行答案。",
                lambda item, body: answers.__setitem__(item, body),
                attachments=attachments,
            )
            answer = "\n".join(answers.values())
            assert status == "completed" and "潮汐" in answer, answer
            if args.image:
                assert "https://api.deepseek.com/v1" in answer, answer
            assert not any(word in answer for word in ("无法", "未读取", "未收到", "未取得")), (
                answer
            )
            print("MATERIAL_INPUT_PASSED", answer, flush=True)
            return
        prompt = (
            "这是测试小说的只读能力验收。请先调用小说 MCP 的当前上下文、章节列表和正式正文工具，"
            "再联网搜索 OpenAI Codex app-server 官方文档。简要回答：正式正文标题及钥匙颜色、"
            "未保存的结尾、文本附件中的暗号、官方文档链接。"
            + ("同时描述图片中模型设置页面上 Base URL 的内容。" if args.image else "")
            + "不修改任何资料，中文回答不超过300字。"
        )
        status = port.send(
            prompt,
            lambda item, body: answers.__setitem__(item, body),
            attachments=attachments,
            on_event=event,
        )
        answer = "\n".join(answers.values())
        (root / "answer.txt").write_text(answer, encoding="utf-8")
        assert status == "completed", status
        assert "海港钟楼" in answer and "银" in answer and "潮汐" in answer, answer
        if args.image:
            assert "https://api.deepseek.com/v1" in answer, answer
        material_answer: dict[str, str] = {}
        status = port.send(
            "请阅读本轮输入携带的附件材料（文字已直接传入，无需打开文件），"
            "只回答银色钥匙的暗号，不调用任何工具。",
            lambda item, body: material_answer.__setitem__(item, body),
            attachments=(text,),
        )
        material_text = "\n".join(material_answer.values())
        assert status == "completed" and "潮汐" in material_text, material_text
        assert not any(word in material_text for word in ("无法", "未读取", "未收到", "未取得")), (
            material_text
        )
        assert any(params.get("item", {}).get("type") == "webSearch" for _, params in events)
        assert any(params.get("item", {}).get("type") == "mcpToolCall" for _, params in events)
        first = port.thread_id
        port.restore(fork=True)
        branch = port.thread_id
        assert branch != first
        history = port.restore(thread_id=first)
        assert any("海港钟楼" in content for _, content in history)
        port.restore(new=True)
        port.send("请仅回复：新会话验收", lambda *_: None)
        assert len(port.sessions) == 3
        port.restore(thread_id=branch)
        result = port.compact()
        assert result == "compacted", result
        assert (
            ChapterRepository(book).read_content_exact(chapter.id)
            == "叶舟在海港钟楼发现了银色钥匙。"
        )
        report = {
            "model": choice.model,
            "effort": effort,
            "status": status,
            "sessions": len(port.sessions),
            "compaction": result,
            "answer": answer,
        }
        (root / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("LIVE_ACCEPTANCE_PASSED", root, flush=True)
        print(answer, flush=True)
    except CodexConnectionError as exc:
        print("RPC_DIAGNOSTIC", exc.rpc_error, flush=True)
        raise
    finally:
        port.close()


if __name__ == "__main__":
    main()
