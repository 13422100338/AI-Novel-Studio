# Frontend 修复：正文 Enter/Shift+Enter 换行 与 AI 引用文本溢出

> 分支：`codex/frontend-agent-c1`（独立提交，未合并 `main`）

## 1. 问题 1：正文 WebEngine 编辑器 Enter/Shift+Enter 无法换行

### 根因

`editor.ts` 的 keymap 只绑定了撤销/重做（`Mod-z`/`Mod-y`），没有引入
ProseMirror 的 `baseKeymap`——它是 PM 的标准按键绑定，其中包含
`Enter → splitBlock`、`Shift+Enter → insertHardBreak`。缺失时编辑器能输入
文字，但回车没有任何反应（既不分段也不换行）。

### 修复

- `editor_web/src/editor.ts`：keymap 改为 `{ ...baseKeymap, "Mod-z": ..., ... }`；
- `dist/` 已重新构建（`npm run build`）；
- 新增 Node 测试：`splitBlock`（Enter 命令）在光标处拆分段落；
  `hard_break`（Shift+Enter 目标节点）在 schema 中存在且 markdown 往返不丢。

## 2. 问题 2：AI 助手引用文本过长时超出屏幕

### 根因

`ContextReferenceChip` 的预览 Text 虽设了 `elide: ElideRight`，但 QML `Text`
的省略只在**单行**时生效；跨段选区文本包含换行符时预览变成多行，配合
`maximumWidth` 上限仍可能把文本挤出 chip 之外。

### 修复

- `ContextReferenceChip.qml`：label 与 preview 都加 `maximumLineCount: 1`，
  保证 elide 始终生效；
- `mock_novel_studio_facade.py`：`selectionReferencePreview` 把换行/空白折叠为
  单个空格再截断 80 字符并补省略号，预览永远单行。

## 3. 验证

```text
pytest（独立前端）   140 passed, 35 skipped
pytest（c9a2 集成）  216 passed, 0 skipped
ruff / mypy          通过
npm test             131 passed（新增 splitBlock / hard_break 两项）
npm typecheck / build 通过
```

真机 WebEngine 截图 `docs/frontend/screenshots/fix-long-reference.png` 确认长
引用文本被截断在 chip 内（文本左右均有留白，无越界）。

说明：自动化脚本无法可靠模拟真实键盘焦点链（合成按键与 QTest 均不触发编辑，
用户手动输入正常），Enter 行为由 Node 层命令测试 + dist 产物确认，建议真机
启动后按 Enter / Shift+Enter 复核手感。
