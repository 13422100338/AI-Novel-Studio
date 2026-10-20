# FO-5：默认完整大纲流程与旧入口收拢

状态：已实现并验证；日期：2026-10-20。承接 [FO-4b 候选闭环](FO4B_WRITER_CANDIDATES_2026-10-20.md)，不删除历史代码、资料或数据库表。

## 默认行为

- 软件默认只启动 Codex 会话控制器，不再同时创建旧 Harness 助手；显式旧接口及演示模式保留。
- `NovelWriterService.generate()` 统一准备完整大纲输入，返回 `AWAITING_CONFIRMATION`。只有作者在软件中确认后才调用独立正文模型。
- 没有登记大纲时，正文任务在读取写作网关前明确停止，提示在大纲页导入／新建并保存完整大纲；不回退到旧记忆上下文编译。
- 缺少大纲的项目仍可打开、编辑、保存、只读讨论和查询正式章节。侧栏提供“打开大纲”入口，登记后提示收起；不自动把旧摘要改造成大纲。
- 旧的 `requestDraft()`、`startAgentTurn()` 在 Codex 模式下也转入同一会话与作者确认流程，不能绕过新默认入口。

## Codex 与小说资料

默认提供 6 个只读工具：当前上下文、章节列表、单章读取、批量读取、正文证据检索、作者约束；另有只准备输入的 `generate_novel_draft`。作者约束及正式正文搜索继续使用原有版本／证据校验。

旧 `query_novel_characters` 不再列入默认目录。直接只读调用仍兼容；`NovelMcpServer(include_legacy_tools=True)` 才显式提供该旧工具，默认启动不启用。工具实际注册目录与 endpoint 的允许列表一致。

会话规则与写作技能同步明确完整大纲、正文引用传递、作者确认和禁止自动记忆抽取。新版技能副本使用 `.agents/skills/studio-novel-edit-v2/SKILL.md`，保留旧 v1 文件；现有会话技能配置仅启用当前受管目录，不会同时启用旧副本。已有修改过的当前版本副本仍拒绝覆盖。

缺纲使用专门的 `OutlineRequiredError`；MCP 只透传该固定、可操作的提示，其他异常继续使用脱敏错误信息。

## 旧资料与保留边界

- 导航保留“写作、大纲、旧资料、设置”。历史人物与记忆记录集中只读展示，原高级视图通过“更多旧资料”进入，可返回。
- 移除旧世界／待处理页面的未实现占位入口，不删除对应存储。旧人物、记忆、伏笔、轨迹、认知和审查记录继续保留。
- Codex 模式下历史审查隐藏“忽略／误报”，facade 同时拦住直接写入调用。保留刷新和证据定位等只读行为。非 Codex 的显式旧接口保持原行为。
- 正文编辑、自动保存、修订历史、候选检查点、原输入恢复、正式正文索引及旧来源失效维护均保留。
- `GenerationMemoryContextProvider`、旧分析／抽取／摘要服务和旧 `_generate` 实现暂留，默认新流程不调度它们；后续清理需独立列出仍被显式旧接口使用的依赖。
- 本票没有数据库迁移，没有 DROP、清表、自动转换旧记忆或改写作者正文。历史视图的只读加载不等于把历史资料送入新模型上下文。

## 改动文件

路径相对于 `src/ai_novel_studio/`：

- `application/novel_writer_service.py`、`outline_writer_input.py`：新默认入口、缺纲错误及保留确认机制。
- `application/novel_read_service.py`、`infrastructure/mcp/novel_server.py`：默认与显式旧只读目录分开，固定错误透传。
- `application/codex_session_service.py`、`infrastructure/codex/writing_skill.py`、`skills/novel-edit/SKILL.md`：会话规则、新技能及副本版本升级。
- `ui_qml/bootstrap.py`、`bridge/mock_novel_studio_facade.py`：默认助手与旧入口重定向，历史审查写入保护。
- `ui_qml/qml/App.qml`、`components/NavigationRail.qml`、`CreativeAgentPanel.qml`、`pages/MemoryLibraryPage.qml`、`AdvancedCreationPage.qml`、`AuditPage.qml`：导航收拢、大纲提示和只读历史页面。

新增后端／QML 的 `test_outline_workflow_default.py`，扩展技能升级测试；原写作测试改为显式确认，历史记忆页测试使用新的两项分类。中英文 README 和总路线同步。

## 验证

- 新增 11 项测试，覆盖缺纲无网关／旧编译调用、登记后确认与生成、采用后正式正文可检索、旧记忆表未新增抽取、默认／显式 MCP 目录、明确缺纲错误、默认不建 Harness、导航、大纲提示、旧入口重定向、技能共存和历史审查拒写。
- 第一轮 10 项新行为测试失败，实施后通过；独立复核发现历史审查写入口后，新增用例先复现 OPEN 被改成 REJECTED，再验证完整记录保持不变。
- 相关存储、应用、旧任务恢复、UI、MCP／Codex 与大纲解析回归累计去重 **760 项通过**，无跳过。原“立即生成”断言更新为待作者确认的新语义。
- Ruff 与 8 份相关 Python 源码的 MyPy 通过。仍存在 MCP 依赖的 Pydantic `lifespan` 前向引用警告，不影响测试结果。
- 真实 Codex + 临时虚构项目串联通过：无大纲时只读取得正文末尾标记；登记 30 个事件、974 字完整大纲后，原生写作技能准备提案；确认前正文调用 0 次，确认后本地假写作模型调用 1 次，完整大纲原文进入最终消息，作者采用后修订递增。
- 实际会话中默认目录为 6 个只读工具加 1 个写作准备工具；旧技能文件保留且禁用，新技能正常启用。未接通付费正文供应商。
- 默认写作、大纲缺失提示、旧资料及历史审查三态离屏截图完成；历史审查无写按钮，直接调用也未修改记录，相关 QML 警告为 0。辅助截图脚本修正了测试审查类型与 `QQuickWindow` 导入后重拍，未据此修改业务逻辑。
- 只读复核提出的历史审查问题修正后复核通过。验证仅使用临时虚构项目，未打开或修改作者小说、数据库、备份、导出或密钥。

复跑关键用例，在当前工作树设置 `PYTHONPATH=src`、`PYTHONDONTWRITEBYTECODE=1`、`QT_QPA_PLATFORM=offscreen`、`QT_QUICK_BACKEND=software`：

```powershell
python -m pytest tests/integration/application/test_outline_workflow_default.py tests/ui_qml/test_outline_workflow_default.py tests/unit/application/test_novel_writing_commands.py -q -p no:cacheprovider --basetemp (Join-Path $env:TEMP ('ans-fo5-' + [guid]::NewGuid().ToString('N')))
```

下一步建议：在独立票中做整体验收与集成；专用 AI 章节关联提案和旧代码清理另行排期，不并入本票。
