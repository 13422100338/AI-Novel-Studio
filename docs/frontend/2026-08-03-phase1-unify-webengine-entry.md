# Phase 1 交付记录（统一迁移到 NovelEditorView，P2-3）

> 分支：`codex/frontend-wave-f1`；日期：2026-08-03
> 范围：默认入口统一为 WebEngine 编辑器；TextArea 保留为回退/测试基线。

## 1. 变更

- **入口统一**：`python -m ai_novel_studio.ui_qml`（及 gui-script
  `ai-novel-studio-qml`）现在默认 WebEngine（`QtWebEngineQuick.initialize()` +
  `WritingPageUseWebEngine=true`）；`--textarea` 参数回退 TextArea；
  `bootstrap_webengine.py` 收敛为兼容别名；
- **字数实时**：编辑器每次事务后回传字数（JS `countWords` 与 Python
  `count_words` 同语义），桥新增 `wordCountChanged` → Facade
  `webEngineWordCountText`，写作页与状态栏在 WebEngine 模式显示实时字数；
- **审校定位接线**：NovelEditorView 新增 `revealRange(from,to)`（ProseMirror
  TextSelection + scrollIntoView），F15 证据定位在 WebEngine 模式可用；
- **草稿生成**：WebEngine 模式仍隐藏（AI 候选回流编辑器属迁移后接线点，见风险）。

## 2. 验证

| 门禁 | 结果 |
|---|---|
| pytest | 989 passed（含字数回传/桥/facade 新测试） |
| Ruff / MyPy（210 文件） | 通过 |
| npm test / typecheck / build | 124 passed |

## 3. 真机复核

```powershell
cd C:\Users\钟子诚\.codex\worktrees\c9a2\AI-Novel-Studio
.\.venv\Scripts\python.exe -m ai_novel_studio.ui_qml
```

打开演示项目 → 编辑器渲染 → 打字时字数实时变化 → 800ms 自动保存 →
审校证据定位（若有问题）→ 切章。需要 `--textarea` 时：
`python -m ai_novel_studio.ui_qml --textarea`。

## 4. 风险与迁移后接线点

- **AI 草稿生成**：WebEngine 模式隐藏「生成草稿」（TextArea 模式可用）；
  迁移后需把候选层回流编辑器（loadDocument 或 insertTextAt 桥命令）并统一
  采用路径；
- 截图脚本 `capture_frontend_f1_screenshots.py` 固定 TextArea 基线；
- 状态栏「修订/保存状态」沿用 Facade（保存后更新），编辑期间为上一修订号，
  与 WebEngine 协议一致（保存时带 baseRevision）。
