# AI Novel Studio Frontend C1.5：WebEngine 黑色边条修复

> 适用仓库：`13422100338/AI-Novel-Studio-Frontend`
> 分支：`codex/frontend-agent-c1`（独立提交，未合并 `main`）
> 性质：只修 WebEngine 背景、滚动条与 resize 重绘问题；未改后端、未做视觉重构。

## 1. 现象

- 启动程序时正文 WebEngine 右侧/底部出现黑色 L 形边条，切换章节后消失；
- 多次开关 AI 助手时，编辑器靠 AI 助手一侧偶尔短暂出现黑条，随后自行消失。

## 2. 排查结论（两个问题分别定位）

### 问题 A：启动 L 形黑条 = 页面视口与滚动条

只读审计 `editor_web/src/style.css` 与 `index.html`：

- `html/body` 没有 width/height/margin/padding/background —— QtWebEngine 在页面
  首次合成前露出默认黑色画布；
- `.novel-editor` 使用 `min-height:100%` + `padding:24px 32px`，且未开
  `box-sizing:border-box`（content-box）→ 内容高度 = 100% + padding，产生
  纵向溢出，触发 body 滚动条；32px 左右 padding 同样可能诱发横向溢出；
- 没有 `::-webkit-scrollbar` 样式 → 默认黑色轨道，构成 L 形黑条的下/右段。

### 问题 B：AI Dock 开关黑条 = WebEngine 动态 resize 重绘

复现并逐层验证：

1. **宽度动画**（C1.2 加入的 `Behavior on Layout.preferredWidth`，220ms）：
   WebEngineView 逐帧 resize，合成器跟不上一整条 400px 宽的新区域；
2. **即使改为瞬间 resize**：Chromium 渲染器不一定收到 resize 通知，新暴露区
   保持上一帧纹理（纯黑）。实验证明：把 `backgroundColor` 设为品红，黑条仍是
   `(0,0,0)` —— 黑条不是 QSG 清屏色，而是渲染器未重新合成的旧纹理区；
3. **带回调的 JS 布局读取**
   `runJavaScript("void(document.body.offsetHeight)", callback)` 能确定性触发
   渲染器往返并重绘新区域（无回调的 fire-and-forget 无效）；
4. **残留持久化**：本机 Windows D3D 下 Chromium 频繁 `context lost`，即使有
   nudge，2/10 周期黑条仍持续 300ms+；`--disable-gpu`（软件合成）后
   10/10 周期 0 持久化，GPU 错误消失。

## 3. 修复内容

### 问题 A（页面与滚动条）

`editor_web/src/style.css`：

- `html, body { width:100%; height:100%; margin:0; padding:0;
  background: var(--editor-bg, #fffdf7); overflow: hidden; }`
- 全局 `* { box-sizing: border-box; }`（含 `::before/::after`）；
- `#editor-mount { width:100%; height:100%; min-height:100%;
  overflow-x: hidden; overflow-y: auto; }` —— 编辑器在挂载点内部滚动，
  body 永不出现滚动条，`min-height:100%` + padding 不再溢出；
- `::-webkit-scrollbar / track / thumb` 使用 `--editor-bg` / `--editor-muted`
  主题色，radius 5px，禁止黑色轨道。

`editor_web/src/editor.ts`：`applyTheme` 把 CSS 变量同步到
`document.documentElement` 与 `#editor-mount`（原来只写到 view.dom），
确保 html/body 背景与滚动条轨道跟随主题重绘。

### 问题 B（动态 resize）

- `NovelEditorView.qml`：`backgroundColor: Theme.tokens.color.bgEditor`
  （视图清屏色与页面背景一致，resize/重绘时不会闪黑）；
- `AgentDock.qml`：新增 `property bool animateWidth`，`Behavior` 用
  `enabled: root.animateWidth` 关闭；`App.qml` 传 `animateWidth: !window.useWebEngine`
  —— WebEngine 模式下 Dock 宽度瞬间切换，不再逐帧 resize；
- `NovelEditorView.qml`：宽度变化后立即执行一次**带回调**的
  `runJavaScript("void(document.body.offsetHeight)", callback)` + `update()`，
  25ms 后再补一次（覆盖延迟到达的 resize 通知）。这是重绘触发，不是重载章节；
- `bootstrap.py`（WebEngine 入口）：`QTWEBENGINE_CHROMIUM_FLAGS`
  `setdefault("--disable-gpu")` —— 软件合成消除 D3D context-lost 导致的
  残留黑条。页面为纯文本编辑器，性能影响可忽略；用户可用自己的
  `QTWEBENGINE_CHROMIUM_FLAGS` 覆盖。

未使用：黑色遮罩、`clip` 掩盖、延时截图、强制刷新/重载章节。

## 4. 真机验证（Windows 真实显示）

验证脚本 `scripts/verify_webengine_edges.py`（三个模式）：

- `cold`：冷启动 → 等 `editorLoaded` → **立即**抓窗 → 断言 WebEngineView
  四边 4px 带内黑色像素占比 ≤ 0.4，且中部无近实心黑列/黑行；
- `interact`：20 次 AI 开关、20 次切章、Dock 宽度 360/420/520，每步
  settle 60ms（渲染器往返落地）后断言；
- `audit`：10 次开关，逐帧采样测量黑条持久化时长，要求 ≤ 150ms。

结果：

```text
冷启动 20 次（立即抓帧）：20/20 通过，0 黑条
AI 开关 20 次 × 缩放 1.0 / 1.25 / 1.5：全部通过（每轮 40 帧断言）
切换章节 20 次 × 3 缩放：全部通过
Dock 宽度 360 / 420 / 520px × 3 缩放：全部通过
瞬态审计（黑条最长持久化）：
  缩放 1.0 / 1.25 / 1.5 → max_persistence = 0.000s（10/10 周期无黑条）
```

说明：本机系统 DPI = 200%（截图 2880×1800）；100%/125%/150% 通过
`QT_SCALE_FACTOR=1 / 1.25 / 1.5` 叠加验证，几何断言按
`image.devicePixelRatio()` 换算，不依赖固定分辨率。

### 离线/集成测试

```text
独立前端测试：128 passed, 35 skipped（skip 均为后端依赖，同前）
主仓库集成测试：204 passed, 0 skipped
npm：129 passed，typecheck/build 通过
ruff / mypy：通过
```

新增测试：

- `tests/ui_qml/test_editor_web_page.py`（6 项静态契约）：html/body 尺寸与
  背景、border-box、mount 尺寸、`overflow-x:hidden`、滚动条主题色、
  `applyTheme` 写页面根、`backgroundColor`、`animateWidth` 布线；
- `tests/ui_qml/test_qml_shell.py::test_agent_dock_webengine_mode_skips_width_animation`：
  `animateWidth:false` 时开关宽度瞬间到位（无动画帧）。

## 5. 截图（docs/frontend/screenshots/，真实程序窗口抓取）

- `c1.5-startup.png` —— 启动后（AI 关闭）
- `c1.5-ai-open.png` —— AI 助手展开
- `c1.5-ai-closed.png` —— AI 助手关闭
- `c1.5-dock-360px.png` / `c1.5-dock-420px.png` / `c1.5-dock-520px.png`
- `c1.5-cold-01.png … c1.5-cold-20.png` —— 20 次冷启动（每次独立进程）

## 6. 修改文件

```text
src/ai_novel_studio/ui_qml/editor_web/src/style.css
src/ai_novel_studio/ui_qml/editor_web/src/editor.ts
src/ai_novel_studio/ui_qml/editor_web/dist/style.css      （重建产物）
src/ai_novel_studio/ui_qml/editor_web/dist/editor.js      （重建产物）
src/ai_novel_studio/ui_qml/qml/components/NovelEditorView.qml
src/ai_novel_studio/ui_qml/qml/components/AgentDock.qml
src/ai_novel_studio/ui_qml/qml/App.qml
src/ai_novel_studio/ui_qml/bootstrap.py
tests/ui_qml/test_editor_web_page.py                      （新增）
tests/ui_qml/test_qml_shell.py
scripts/verify_webengine_edges.py                         （新增）
docs/frontend/2026-08-04-frontend-c1-5-webengine-black-edges.md
docs/frontend/screenshots/c1.5-*.png                      （新增）
```

## 7. 风险与说明

- `--disable-gpu` 使 WebEngine 走软件合成：本页面为纯文本编辑器，影响可忽略；
  若未来引入视频/WebGL 内容需重新评估；
- 验证脚本在真机窗口下运行，会短暂弹出程序窗口（已随本轮需求执行）；
- AI 开关后 60ms settle 属于“渲染器往返落地”的验证时机，不是掩盖手段：
  `audit` 模式独立证明黑条不持久（0.000s）；
- 侧栏（左侧）折叠仍有 220ms 宽度动画，WebEngineView 同样会被 resize；
  本轮按范围仅处理 AI Dock，侧栏如出现同类问题可作为后续项。
