# Phase 1 交付记录（编辑器内核 + 桥接，P1-0 至 P1-3）

> 分支：`codex/frontend-wave-f1`
> 日期：2026-08-03
> 范围：方案 Phase 1 的自动化闸门全部落地（往返、压力、编辑可靠性、桥接协议）；
> 真机 IME / 手感验收仍需要你本机执行。

## 1. 交付内容

- P1-0：`editor_web` 脚手架（Node 24 / npm 11，vitest 4），受限小说 Schema
  （H1/H2、段落、粗体、斜体、引用、分隔线、软换行），**100 组黄金样本**
  Markdown 往返测试全部通过（prosemirror-markdown 为正式实现，@tiptap/markdown
  未启用为第二序列化器）；不支持语法（代码块/HTML/表格/缩进代码/数学/反引号）在
  parse 前拒绝；
- P1-1：DOM-free 编辑器核心——中文文本插入、history 撤销重做、查找替换、
  快照（FNV 指纹 + Python 侧权威 SHA-256）、800ms 防抖保存控制器；
  **20 万字符**打开/往返/撤销 + **1000 次连续编辑**压力测试全部通过；
- P1-2：浏览器入口——EditorView 挂载、IME composition 钩子、撤销/重做快捷键、
  `Mod-f` 查找替换、选区工具条样式、审校 Decoration 原型、主题 CSS 变量、
  `window.__novelEditor` 桥表面；`npm run build` 产出 dist（editor.js + html +
  css + qwebchannel.js）；
- P1-3：Python/QML 桥——`EditorBridge`（协议 v1 握手、能力白名单、payload 校验：
  章节 ID / 修订 / 5MB / 哈希）、`editor_runtime`（runJavaScript 脚本生成、
  qwebchannel.js 幂等复制、WebEngine 安全设置函数）、`NovelEditorView.qml`
  （WebEngineView + QWebChannel + off-the-record profile）。

## 2. 桥接设计

- 下行（Python → JS）：`runJavaScript("window.__novelEditor.loadDocument(...)")`；
- 上行（JS → Python）：QWebChannel 单对象 `pythonBridge`（editorReady /
  saveRequested / selectionChanged）；
- 协议不匹配、能力未知、哈希不一致、超大 payload 一律拒绝并返回稳定错误码；
- CSP `default-src 'none'` + 本地 `self`；关闭远程/文件/存储/弹窗/粘贴/DNS 预取/
  插件/全屏/录屏（方案 6.5）。

## 3. 验证结果

| 门禁 | 结果 |
|---|---|
| npm test | 124 passed（100 黄金样本 + 编辑核心 + 压力） |
| npm typecheck / build | 通过，dist 4 文件 |
| pytest（含 bridge/runtime 测试） | 980 passed |
| Ruff / MyPy（207 文件） | 通过 |

压力证据：20 万字符 parse < 3s、往返 < 5s、1000 次编辑无丢字、撤销 < 5s
（宽松 CI 阈值；真实手感需本机）。

## 4. 遗留与人工验收

- 20 万字符**滚动/输入/IME 手感**与中文候选窗口只能在真实 Windows 桌面会话
  验证（offscreen 不初始化 WebEngine）；
- WebEngineView 尚未接入 QML 主 Shell 的写作页（需真实启动；QML 组件已就绪）；
- `qwebchannel.js` 来自 Qt（LGPL-3.0，`src/editor_web/src/qwebchannel.js`），
  前端文档记录许可证；**项目根 `THIRD_PARTY_NOTICES.md` 需在打包票补充该项**
  （该文件不在前端允许清单，需用户/主控确认）。

## 5. 下一步建议

- 真机冒烟：`python -m ai_novel_studio.ui_qml` 接 EditorView 并加载 20 万字符稿；
- 或接入主写作页（WritingPage 的 TextArea 替换为 NovelEditorView 垂直切片）。
