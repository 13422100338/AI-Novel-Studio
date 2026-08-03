# Phase 1 交付记录（WebEngine 接入主写作页切片，P1-5）

> 分支：`codex/frontend-wave-f1`；日期：2026-08-03
> 范围：把 Tiptap/ProseMirror 编辑器接入 QML 主壳的写作页，保存复用 F3 路径。

## 1. 交付内容

- `bootstrap_webengine.py`：`QtWebEngineQuick.initialize()`（必须在 QGuiApplication
  创建前）→ `QWebChannel` 注册 `pythonBridge` → 加载 `AppWebEngine.qml`；
  `EditorBridge.save_requested` 直接接 `Facade.saveFromEditor`（Python 侧连接，
  不依赖 QML 信号命名映射）；
- `AppWebEngine.qml`：独立 WebEngine 写作入口（导航轨 + 章节侧栏 + NovelEditorView
  + 顶部章节标题/保存按钮）；页面加载完成后自动注入当前章节；
- `NovelEditorView.qml` 简化：`webChannel` 直接绑定 Python 端 `EditorChannel`
  context property（QML 不再自建 channel）；
- `Facade.saveFromEditor(chapterId, expectedRevision, markdown)`：校验章节匹配 +
  expected_revision（F3 语义），写入真实项目并推进修订；过期 → CONFLICT；
- 新 GUI 入口 `ai-novel-studio-editor`（`python -m ai_novel_studio.ui_qml.webengine`）。

## 2. 验证

| 门禁 | 结果 |
|---|---|
| pytest | 983 passed（含 saveFromEditor 3 例 + 桥→facade 集成 1 例） |
| Ruff / MyPy（210 文件） | 通过 |
| npm test | 124 passed（编辑器源码未改动） |

## 3. 真机验收（需你本机）

```powershell
cd C:\Users\钟子诚\.codex\worktrees\c9a2\AI-Novel-Studio
.\.venv\Scripts\python.exe -m ai_novel_studio.ui_qml.webengine
```

确认：窗口出现 WebEngine 编辑器 → 打开项目 → 章节正文在编辑器内渲染 →
中文输入不丢字 → 停止输入 800ms 状态栏“已保存 · 修订 N” → 切章重新加载。

## 4. 风险

- `QtWebEngineQuick.initialize()` 必须在应用创建前调用，普通 QML 入口（
  `python -m ai_novel_studio.ui_qml`）不加载 WebEngine，两者互不干扰；
- QML `WebEngineView` 的 webChannel 在 PySide6 6.11 的绑定方式以真机为准，
  若 channel 不通，回退方案是 `NovelEditorView` 改用 `runJavaScript` 注入
  pythonBridge 握手（方案 6.1 的 editor.ready 已就绪）；
- WebEngine 进程需要真实桌面会话，offscreen 测试未覆盖其渲染。
