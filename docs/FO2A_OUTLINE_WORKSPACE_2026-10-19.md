# FO-2a：可编辑 Markdown 大纲工作区

日期：2026-10-19。状态：实现及临时项目、离屏界面验证完成，未提交或推送。
工作分支：`codex/full-outline-architecture`，沿用 FO-1 的独立工作树与未提交实现。
依据：[完整大纲方案](FULL_OUTLINE_WORKFLOW_2026-10-18.md)、[FO-1 存储基础](FO1_OUTLINE_STORAGE_2026-10-19.md)。

FO-2 涉及工作区接线和章节关联的新迁移，按项目小票规则拆分：本票完成 FO-2a 编辑工作区，FO-2b 单独实现关联与确认。
本票没有新增迁移，仍使用 FO-1 的 v26；没有更改 Codex、正文输入或旧记忆主链。

## 使用方式

在此工作树版本打开小说项目，选择左侧“大纲”：

- 新建文档，或导入 UTF-8 Markdown／文本。可创建全书总览和多份分卷大纲。
- 直接编辑 Markdown 源码；停止输入约 900ms 后自动保存，也可点击保存或使用标准保存快捷键。
- 文档下拉框切换大纲；“···”菜单可调整文档顺序。
- “目录”显示 Markdown 标题、编号事件与中文卷标题；点击跳转，搜索框筛选标题，回车查找正文。
- “···”菜单可查看历史、预览后回退、重新导入、导出当前编辑、重载和恢复。
- 重新导入先展示差异并等待确认；预览不是写入。采用历史版本会新建修订，保留原有历史。
- 编辑区、目录和确认窗沿用现有米色主题；目录与历史面板可关闭，不常驻占用正文宽度。

本票的大纲尚未自动注入 Codex 或独立正文模型。章节关联与确认属于 FO-2b；模型输入属于 FO-3／FO-4。

## 内容与状态保护

- 加载不触发保存，不改写 BOM、CRLF、空白、注释与 Markdown 链接。
- Qt 编辑区所需的换行显示归一化仅影响展示；真正编辑时只替换变化范围，未触及的原文格式保留。
- 导出包含当前完整编辑，未保存或发生保存冲突时也能导出副本；已有目标文件拒绝覆盖。
- 保存失败保留缓冲区，并阻止文档切换、离开大纲页面、项目切换或正常窗口关闭。
- 项目结构刷新不会清空同一项目的大纲编辑；无效导入不丢弃当前文档。
- 重导入和历史采用校验作者看到的修订、当前文档与预览时的缓冲区，不能采用未审阅的服务器新修订。
- 接纳磁盘副本另校验预览哈希；确认文案明确会替换当前编辑，作者可取消后先导出。
- 缺失文件只通过显式恢复入口重建。损坏快照继续失败关闭，不编造或覆盖历史。
- 全局状态栏在大纲页面显示大纲字符数和大纲保存状态，不借用正文的“已保存”状态。
- 导航、目录、预览和导出不调用真实模型或读取章正文；大纲编辑与正文缓冲区分别持有状态。

## 改动文件

后端／文本处理：

- `src/ai_novel_studio/core/outline_markdown.py`：显示与原文的最小编辑映射、轻量标题定位、UTF-16 光标位置。
- `src/ai_novel_studio/application/outline_service.py`：只读文件预览、显式导出。
- `src/ai_novel_studio/infrastructure/storage/outline_repository.py`：事务内文档排序，保留全部文档与内容修订。

界面：

- `src/ai_novel_studio/ui_qml/bridge/outline_bridge.py`：独立编辑状态、自动保存、预览与恢复。
- `src/ai_novel_studio/ui_qml/bridge/mock_novel_studio_facade.py`：项目生命周期、保存保护和导航接线。
- `src/ai_novel_studio/ui_qml/qml/pages/OutlinePage.qml`：源码编辑、目录、文档操作及预览确认窗。
- `src/ai_novel_studio/ui_qml/qml/App.qml`：页面、窗口关闭保护及准确的全局状态。
- `src/ai_novel_studio/ui_qml/qml/components/NavigationRail.qml`、`NavIcon.qml`：大纲入口与图标。

新增测试：

- `tests/unit/test_outline_markdown.py`
- `tests/integration/application/test_outline_workspace.py`
- `tests/ui_qml/test_outline_bridge.py`
- `tests/ui_qml/test_outline_page.py`

中英文 README 与路线文档同步更新当前能力，未将后续关联、完整上下文注入宣称为已完成。

## 验证与边界

- 本票新增 **23 项**测试通过；相关界面、原有项目操作、文本处理与应用服务合计 **132 项**通过。
- 原有存储、FO-1 服务与草稿采用／恢复回归 **360 项**通过；两组共 **492 项**，无跳过。
- Ruff、5 份相关 Python 源码的 MyPy、差异与文档检查通过。
- 独立只读复核通过；主编辑页、聊天并排、目录和确认窗完成离屏截图检查。
- 实际 QML 确认按钮验证一次点击只新建一份文档，避免自定义确认窗重复发出接受事件。
- 验证只操作临时项目，未打开或升级作者项目，未启动可见桌面窗口，未调用真实模型。

延续 FO-1 的 UTF-8、20MB 存储限制与硬链接文件系统要求。
当前目录解析和最小编辑映射会扫描全文，历史列表在保存后刷新；接近上限或积累大量修订的性能尚未专门压测，后续按真实规模测量后再优化。

复核时设置 `PYTHONPATH` 为本工作树 `src`、`PYTHONDONTWRITEBYTECODE=1`、`QT_QPA_PLATFORM=offscreen`、`QT_QUICK_BACKEND=software`，
使用已安装开发依赖的 Python 和新的临时目录运行：

```powershell
python -m pytest tests/ui_qml/test_outline_page.py tests/ui_qml/test_outline_bridge.py tests/ui_qml/test_project_wiring.py tests/ui_qml/test_mock_facade.py tests/ui_qml/test_qml_shell.py tests/unit/test_outline_markdown.py tests/integration/application/test_outline_workspace.py -q -p no:cacheprovider
python -m pytest tests/integration/storage tests/integration/application/test_outline_service.py tests/integration/generation/test_generation_acceptance_and_recovery.py -q -p no:cacheprovider
```

下一票：FO-2b，轻量章节关联、普通 Markdown 章节链接，以及任一大纲版本变更后的作者重新确认。保留旧关联与确认历史，不建立事件图谱。
