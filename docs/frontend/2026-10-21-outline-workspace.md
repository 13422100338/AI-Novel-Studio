# 正文与大纲工作区调整

前端分支：`codex/frontend-outline-workspace`。基线：`e7d7495d4915827cc4205d85567fefc665c7382f`。

## 界面行为

| 调整前 | 调整后 |
| --- | --- |
| 默认 Windows 标题栏 | 与底部状态栏同色的 36px 标题条，保留原生移动、缩放及窗口按钮 |
| 左侧轨道切换写作、大纲 | 工作区上方并列的“正文 / 大纲”切换 |
| 大纲页面仍显示章节侧栏 | 左侧切换为文档选择、标题层级和编号事件导航，支持搜索 |
| 章节关联藏在弹窗中 | AI 助手左侧显示当前节点及其子节点对应的章节，按正文顺序去重展示 |
| 大纲直接显示 Markdown 源码 | 默认排版阅读，支持标题、强调、列表、表格；“编辑源码”切换原始 Markdown 编辑 |

点击关联章节会通过原有章节打开接口进入正文。关联的待确认、已确认及失效状态沿用现有登记记录，保留原有管理弹窗及人工确认流程。编辑尚未保存时，关联栏明确提示以已登记记录为准。

阅读渲染不回写文件，不截断长大纲。为截图中的 `**文字。 **` 提供仅显示时的容错，源码、转义星号及代码内容保留。Markdown 不加载本地或远端图片，不执行 HTML。原有导入、导出、重导入预览、修订、自动保存和冲突保护继续使用。

导航位置使用 Qt 的 UTF-16 偏移；标题对应章节的分组、排序及阅读位置属于前端状态，不改变数据库结构、模型输入组装或 MCP 接口。

## 修改文件

- 外壳与导航：`qml/App.qml`、`components/NavigationRail.qml`、`components/ContextSidebar.qml`；新增 `WorkspaceTabs.qml`、`OutlineNavigator.qml`、`OutlineChapterRail.qml`、`WindowResizeHandles.qml`。
- 大纲页面：`qml/pages/OutlinePage.qml`。
- 前端桥接与排版：`bootstrap.py`、`bridge/outline_bridge.py`、`bridge/chat_markdown.py`；新增 `bridge/outline_markdown_view.py`。
- 前端测试：新增 `test_outline_markdown_view.py`、`test_outline_workspace_layout.py`；更新 `test_outline_bridge.py`、`test_outline_page.py`、`test_qml_shell.py`、`test_native_glass_shell.py`。

源文件均位于 `src/ai_novel_studio/ui_qml/`，测试位于 `tests/ui_qml/`。没有修改后端代码、数据库结构、小说项目、备份、导出或凭据。

## 验证

- 102 项相关前端测试通过，覆盖原有外壳、主题、默认创作流程、大纲保存与关联，以及新增阅读导航。
- 1100 / 1440 / 1920 宽度均通过布局检查；聊天栏拖至最大宽度后仍为文档保留至少 280px。
- Ruff、修改桥接模块的 MyPy 检查通过，`git diff --check` 通过。
- 本工作树编辑器资源 `npm ci` / `npm run build` 成功；`AI_NOVEL_STUDIO_LAUNCH_SMOKE=1` 的 `launch.ps1` 启动检查退出码为 0。
- Windows 实际窗口使用工作树内虚构测试项目验证：鼠标点击目录选择事件、关联章节打开正式正文、源码切换、窄窗口、最大化及还原；QML 警告为 0。
- 截图和窗口验证记录保存在本地 `.test-temp/visual-final/`，包含 `outline-reading.png`、`outline-source.png`、`outline-narrow.png`、`writing.png`、`verification.json`。截图中的项目与聊天均为界面验证样例，没有调用写作模型。

相关测试命令（在本前端工作树，设置 `PYTHONPATH=src`、`QT_QPA_PLATFORM=offscreen`、`QT_QUICK_BACKEND=software`）：

```powershell
python -m pytest tests/ui_qml/test_outline_workspace_layout.py tests/ui_qml/test_outline_page.py tests/ui_qml/test_outline_bridge.py tests/ui_qml/test_outline_link_bridge.py tests/ui_qml/test_outline_links_panel.py tests/ui_qml/test_chat_markdown.py tests/ui_qml/test_native_glass_shell.py tests/ui_qml/test_outline_markdown_view.py tests/ui_qml/test_qml_shell.py tests/ui_qml/test_ui_polish_layout.py tests/ui_qml/test_theme_provider.py tests/ui_qml/test_outline_workflow_default.py -q -p no:cacheprovider --basetemp .test-temp/verification
```

## 交付状态

改动尚未提交、合并或替换桌面旧入口。可从本工作树的 `启动程序.bat` 启动新版。后续整合由作者发起，继续遵守前端隔离规则。本机窗口按钮已经验证；Windows 手动拖拽吸附和其他显示缩放组合尚未逐一验收。
