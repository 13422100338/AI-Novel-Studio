# Phase 1 人工验收清单（需真实 Windows 桌面会话）

> offscreen 无法初始化 Qt WebEngine，IME / 滚动 / 手感只能在本机验证。
> 先决条件：`src/ai_novel_studio/ui_qml/editor_web` 下执行 `npm install` 与
> `npm run build`（dist 已就绪时跳过）。

## 1. 准备 20 万字符样本

```powershell
cd src\ai_novel_studio\ui_qml\editor_web
node scripts\generate-large-sample.mjs
# 产物：dist\samples\large-sample.md（约 20 万字符）
```

## 2. 浏览器内闸门（无需 Qt）

用任意现代浏览器打开 `dist/index.html`，在 DevTools 执行：

```js
window.__novelEditor.loadDocument({
  chapterId: "chapter-1",
  baseRevision: 1,
  markdown: "第一章\n\n" + "雾港的清晨。" .repeat(40000)
});
```

人工确认：
- 中文输入法候选与组合输入不丢字、光标不跳动；
- 20 万字符打开、滚动、Ctrl+Z 撤销无明显卡顿；
- 选中文本出现选区工具条；`Mod-f` 查找替换可用；
- 审校 Decoration 通过 `showDecorations([{from,to,label}])` 可见。

## 3. QML/WebEngine 内闸门（Qt 真实会话）

接入步骤（当前为可选项，主写作页仍用 TextArea）：
1. `bootstrap.main()` 中在 `QGuiApplication` 创建前调用
   `QtWebEngineQuick.initialize()`；
2. `NovelEditorView` 挂到 WritingPage（替换 TextArea 的垂直切片）；
3. `editorLoaded` 后 `runJavaScript` 注入 `loadDocument`，并接
   `EditorBridge.save_requested` → Facade 保存（复用 F3 路径）；
4. 启动 `python -m ai_novel_studio.ui_qml.webengine`，打开真实项目切章验证
   （WebEngine 写作切片入口，P1-5）。

人工确认：
- 打开/切章加载 20 万字符稿，滚动与撤销流畅；
- 中文 IME 在 WebEngine 内无丢字；
- 停止输入 800ms 触发一次保存（状态栏可见），重载后可恢复（Python 快照）；
- 审校证据定位（F15）在编辑器内高亮。

## 4. 退出标准（方案 12.1）

任一失败即停用 WebEngine 路线并回退 QML TextEdit：IME 不可规避丢字、
20 万字符明显劣于现有编辑器、Markdown 子集不能稳定往返（当前 100 组样本全过）、
打包版频繁失败、WebChannel 恢复无法零丢稿。
