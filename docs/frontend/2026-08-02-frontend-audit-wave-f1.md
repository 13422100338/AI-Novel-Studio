# AI Novel Studio 前端只读审计（Frontend Wave F1 前置）

> 日期：2026-08-02
> 分支：`codex/frontend-wave-f1`（基于 `main` @ `7fb53d5`）
> 范围：只读审计。本报告不修改任何代码；实施范围见文末“本轮预计修改文件”与后续 F1 提交。

## 1. 审计输入

- 前端重构方案：`AI_Novel_Studio_前端升级实施方案.md`（2026-07-17 输出）；
- 仓库基线：`main` @ `7fb53d5`（`docs: record P0 logging integration`）；
- 阅读对象：`src/ai_novel_studio/app.py`、`src/ai_novel_studio/ui/**`（约 29 个源文件，约 10,600 行）、`tests/ui/**`（27 个文件，约 8,400 行）、`docs/architecture/0003-phase-2-ui-boundaries.md`、`application/project_runtime.py`、`application/project_workspace_service.py` 的公开契约、`pyproject.toml` 门禁与 CI 配置。
- 环境：PySide6 6.11.1（含 QtQuick / QtWebEngineQuick，F1 不使用后者）。

## 2. 当前前端模块地图

```text
src/ai_novel_studio/
├── app.py                    入口：QApplication → 首启语言 → appearance → MainWindow
├── ui/
│   ├── main_window.py        1580 行：组合根 + 全部命令编排 + 服务/仓储装配
│   ├── theme.py              单一 application_stylesheet()（QSS 字符串，light/dark × density）
│   ├── appearance.py         AppearanceManager（theme/density，QSettings 持久化）
│   ├── i18n.py               LocalizationManager（zh/en，QWidget eventFilter 翻译）
│   ├── demo_data.py          WorkspaceDemoData + Demo* dataclass（生产面板直接消费）
│   ├── feature_flags.py      AGENT_TOOLS_ENABLED 等开关
│   ├── panels/               TopBar / ChapterSidebar / ManuscriptPanel / PlotChatPanel
│   ├── pages/                welcome / brief / memory / audit / settings / style_rules /
│   │                         character_identity / reference / agent_trace / generation / language
│   ├── qt/                   9 个 coordinator + ModelRuntime + QtProjectGenerationRuntime
│   └── widgets/              ChatBubble / CollapsibleSection / MetricChip
tests/ui/                     27 个测试文件，pytest-qt + offscreen（行为合同）
```

### 各层职责与规模

| 单元 | 行数 | 职责 | 备注 |
|---|---:|---|---|
| `main_window.py` | 1580 | 窗口组合、服务装配、命令路由 | 直接构造 20+ application 服务与 4 个 infrastructure 仓储 |
| `pages/memory_window.py` | 1641 | 记忆工作区 + 指引 + 设定 + View Assertion + Reader View | 多职责巨型窗口 |
| `pages/settings_dialog.py` | 731 | 模型连接/配置/外观/创作 | 直连 `infrastructure.llm` 类型 |
| `panels/*` | 1213 | 三栏工作区面板 | 以 `WorkspaceDemoData` 为构造参数 |
| `ui/qt/*` | 1085 | 后台任务适配（QThreadPool + Signal） | 模式正确：只翻译框架无关服务结果 |
| `theme.py` + `appearance.py` | 320 | 主题/密度 QSS | 颜色硬编码在 QSS 字符串内 |
| `i18n.py` | 635 | zh/en 翻译 | widget 专用 |

## 3. 现有耦合问题（按严重度排序）

1. **组合根过大（P0）**：`MainWindow` 同时是布局、命令编排、服务工厂和仓储装配点。它直接 `new` 了 `CharacterMemoryRepository`、`ChapterContextPinRepository`、`ProjectGuidanceRepository` 等基础设施对象，并直接构造 `DeterministicAuditService`、`ManuscriptImportService`、`MemoryAnalysisService(LLMContractRunner(gateway))` 等。方案文档 1.1 已指出该问题。
2. **生产面板与演示数据混合（P1）**：`ChapterSidebar`、`ManuscriptPanel`、`PlotChatPanel`、`TopBar` 都以 `WorkspaceDemoData` 为构造输入，`MainWindow` 在无 `project_runtime` 时回退到 demo 数据。数据边界不清晰，QML 侧必须建立独立 Mock Facade 而不是复用这些 widget。
3. **无 DTO / Facade 层（P1）**：页面直接导入 domain 类型（`BriefStatus`、`ChapterBrief`、`StyleRule`、`AuditFindingStatus`、`GenerationStatus`）与仓储 DTO（`BriefDraftData`）。QML 无法安全直接消费这些对象，需要前端 DTO 边界。
4. **主题无令牌层（P2）**：颜色、间距、圆角、时长散落在 QSS 字符串中；`application_stylesheet()` 按整串重设。QML 与未来 Web 编辑器都需要单一 token 来源。
5. **任务状态无统一模型（P2）**：保存/生成/错误状态写进 `pipeline_status_label`、`save_status_label` 等 widget 文案，窗口方法里同步改 label；没有可测试的任务状态机。
6. **i18n 绑定 QWidget（P2）**：`LocalizationManager` 用 eventFilter 翻译控件文本，QML 无法复用。
7. **导航/路由隐式化（P3）**：三栏 `QSplitter` 硬编码，页面切换靠窗口方法 + 信号，无路由概念。

## 4. KEEP / ADAPT / REPLACE / DEFER / REJECT

### KEEP（冻结为基线，本轮不动）

- `application/` 全部服务与 `ProjectRuntime` 组合（workspace / brief_service / generation_session / agent_runtime）——后端边界资产；
- `ui/qt` coordinator 模式（后台线程 + Qt Signal，服务保持框架无关）——迁移期冻结；
- `tests/ui` 产品行为合同（旧 UI 回归门禁）；
- 旧 QWidget 入口与外观/语言偏好语义；
- 现有性能基线（18.6 万字符 / 35 章）与“正文为唯一权威”约束。

### ADAPT（在新前端中以新形态复用语义）

- `theme.py` QSS 颜色 → `ThemeProvider` Design Tokens（color/spacing/radius/duration/font 单源）；
- `demo_data.py` → `MockNovelStudioFacade` + 前端 DTO（`ChapterDto` / `VolumeDto`）；
- 卷章树语义（`ChapterSidebar.apply_volume_tree`）→ `ChapterListModel`（`QAbstractListModel` roles）；
- 保存状态语义（`mark_saved(revision)`）→ 编辑器状态机 `CLEAN / DIRTY / SAVING` 雏形；
- 字数统计（`ManuscriptPanel._update_word_count`）→ facade 确定性字数计算；
- TopBar 指标芯片 → 状态栏 StatusChip。

### REPLACE（仅发生在新建的 QML Shell 内）

- 三栏 `QSplitter` 布局 → `ApplicationWindow` + Navigation Rail + Context Sidebar + AI Drawer + 状态栏；
- QSS 整串重设 → token 驱动 QML 组件；
- 隐式信号导航 → 显式导航状态（`activeNav`）。

### DEFER（本轮明确不做）

- Tiptap / ProseMirror / Qt WebEngine / QWebChannel 编辑器内核与协议（方案 Phase 1）；
- 全页面迁移（人物 / 记忆 / 线索 / 审校 / 设置）；
- 后端接线（Phase 3 只读项目、Phase 4 保存冲突、Phase 5 AI 主链）；
- 自动保存协议（800 ms 防抖、`base_revision` 冲突、恢复快照）；
- QML i18n、打包（PyInstaller / QML 资源 / WebEngine）、默认入口切换；
- 大规模文件搬迁与旧 UI 删除。

### REJECT（永不采用）

- 把 `MainWindow` 1:1 翻译成 QML Controller；
- QML / JS 直接访问 repository、SQLite、项目文件或模型网关；
- 在前端再造保存 / 生成 / 审校 / 身份合并逻辑；
- 建立第二份“正式稿”权威；
- F1 阶段引入 WebEngine / Tiptap。

## 5. 建议的渐进迁移路线

| 票 | 内容 | 对应方案阶段 |
|---|---|---|
| F1（本轮） | 新增 `ui_qml` 包：Mock Facade + Design Tokens + Shell + 基础组件 + 写作垂直切片；旧 UI 零改动 | Phase 2 子集 |
| F2 | 只读项目接线：`ProjectViewModel` + `ChapterListModel` ← `ProjectRuntime.workspace`（volume_tree / load_chapter） | Phase 3 |
| F3 | 编辑保存：facade 状态机 → `ProjectWorkspaceService.save_chapter`（expected_revision 冲突） | Phase 4 |
| F4 | AI 抽屉：`ProjectGenerationSession` / `GenerationAcceptanceService` 接线与草稿对照 | Phase 5 |
| F5 | 人物 / 记忆 / 审校页面（复用现有服务，不复制逻辑） | Phase 6 / 7 |
| F6 | 打包（QML 资源、WebEngine、安装器） | Phase 8 |
| F7 | 行为对照 + 默认入口切换 + 旧 UI 退役 | Phase 9 |

## 6. 本轮（F1）预计修改文件

全部为新增文件；**不修改任何现有 `domain / application / infrastructure / ui` 文件**：

```text
src/ai_novel_studio/ui_qml/
├── __init__.py
├── __main__.py                 python -m ai_novel_studio.ui_qml 入口
├── bootstrap.py                QGuiApplication + QQmlApplicationEngine + 类型注册
├── bridge/
│   ├── __init__.py
│   ├── mock_novel_studio_facade.py   MockNovelStudioFacade + ChapterDto/VolumeDto
│   ├── theme_provider.py             ThemeProvider（三套 palette + spacing/radius/duration/font）
│   └── models/
│       ├── __init__.py
│       ├── chapter_list_model.py     QAbstractListModel（卷/章扁平行）
│       └── suggestion_list_model.py  AI 抽屉 mock 建议列表
└── qml/
    ├── App.qml
    ├── components/  (NavigationRail / ContextSidebar / AppButton / IconButton / StatusChip /
    │                 SlidingDrawer / SearchField / EmptyState + qmldir)
    └── pages/WritingPage.qml   （正文工作区垂直切片）
tests/ui_qml/                   （theme / facade / models / QML shell 测试）
scripts/capture_frontend_f1_screenshots.py
docs/frontend/                  （本审计报告 + F1 交付记录）
pyproject.toml                  （仅新增 ai-novel-studio-qml gui-script 入口，纯增量）
```

与方案的目录差异（有意为之，理由见 F1 交付记录）：
- 暂不建 `bridge/app_controller.py`：F1 的 shell 命令直接由 Mock Facade 承担，避免空壳控制器；
- 暂不建 `qml/theme/`：token 由 Python `ThemeProvider` 单例提供，QML 通过 `import AI.NovelStudio 1.0` 消费；
- 暂不建 `editor_web/`：方案 Phase 1 的编辑器技术闸门明确不在本轮。

## 7. 后端依赖风险

- **F1 零后端调用**：Mock Facade 不导入 `application` / `infrastructure`，不触碰数据库、稿件、密钥。风险主要存在于未来接线。
- **接线必须走 `ProjectRuntime`**：`ProjectRuntime.workspace`（`ProjectWorkspaceService`）已提供 `summary() / volume_tree() / load_chapter(id) / save_chapter(id, body, expected_revision=...)`；`save_chapter` 还要求 `requirement_content`、`expected_requirement_revision`、`requirement_locked`，这些是 QWidget 专属形态，facade DTO 未来需要显式映射，不能透传 QWidget 状态。
- **`ui/qt` 是 QWidget 形态适配层**：`ModelRuntime` / coordinator 依赖 QWidget 生命周期与主窗口接线，QML 不能假设可直接复用；F2 起应评估把“任务状态”收敛到 QML 中立 Facade，但不修改现有 `ui/qt`。
- **共享持久化**：`appearance` / `i18n` 使用 QSettings，与旧 UI 共享。QML ThemeProvider 本轮独立实现，未来再收敛到同一 DTO（方案 6.5 的 Theme DTO 单一来源）。
- **接口冻结**：不为前端方便修改 domain / application / infrastructure 公共接口；如未来需要新数据（例如章节列表含“人物状态 N+1 概览”），先定义前端 DTO + Mock，再报告接线需求。
- **主线合并风险**：本分支与并行后端 worktree（4df4 / 8802 / 93d7）文件零重叠，冲突面仅限 `docs/` 与新增 `ui_qml` 包。

## 8. 未来接线点（本轮以 Mock 代替，均为确定性数据）

| 前端需求 | F1 Mock 来源 | 未来接线来源 |
|---|---|---|
| 项目标题 / 路径 | `MockNovelStudioFacade.projectTitle/projectPath` | `ProjectRuntime.workspace.summary()` |
| 卷章树 | `ChapterListModel`（flat rows, kind=volume/chapter） | `ProjectRuntime.workspace.volume_tree()` |
| 正文 / 修订号 | `ChapterDto.body/revision` | `ProjectRuntime.workspace.load_chapter(id)` → `ChapterWorkspace` |
| 保存 | `requestSave()`（同步 CLEAN，revision+1） | `save_chapter(..., expected_revision=...)` 已接线（F3）；冲突 → CONFLICT + 显式重载 |
| 字数 | facade 确定性 `count_words()` | 保持前端 DTO 计算（不引入每键保存） |
| AI 建议 / 草稿 | `SuggestionListModel` mock 建议 + 本地采用 | `ProjectGenerationSession` + `GenerationAcceptanceService`（F4） |
| 状态栏 Token / 费用 | 静态 Mock 占位 | `infrastructure.llm.UsageSnapshot`（复用 `TopBar.update_usage` 语义） |

> F2 进展（2026-08-02）：卷章树、正文/修订号已通过 `ProjectWorkspaceService` 只读接线
> （见 `2026-08-02-frontend-wave-f2-readonly-wiring.md`）；项目标题/路径使用
> `summary()`；保存、AI 建议、Token 仍未接线。

> F3 进展（2026-08-03）：项目模式下保存已接 `save_chapter(expected_revision=...)`，
> 修订冲突进入 CONFLICT 并支持显式重新载入（见
> `2026-08-03-frontend-wave-f3-save-conflict.md`）；AI 建议、Token/费用仍未接线。

> F4 进展（2026-08-03）：AI 抽屉候选层已接 `DraftPort` → `ProjectGenerationSession`，
> 采用/放弃走 `GenerationAcceptanceService`（见
> `2026-08-03-frontend-wave-f4-ai-drawer-wiring.md`）；生成流式后台化与 Token/费用显示
> 仍未接线。

> F5 进展（2026-08-03）：生成已后台化（前端自有 `DraftCoordinator` + QThreadPool，
> 不 import `ui/qt`）、支持协作式取消与任务状态可视化（见
> `2026-08-03-frontend-wave-f5-background-generation.md`）；Token/费用显示、
> 生成配置弹层、草稿三视图仍未接线。

> F6 进展（2026-08-03）：「生成草稿」弹层已落地——目标字数、输出 Token、创作档位、
> 采用前审校配置透传 `DraftPort`（见
> `2026-08-03-frontend-wave-f6-generation-config-dialog.md`）；Token/费用显示、
> 草稿三视图仍未接线。

## 9. 结论

当前前端最大的架构债务是 `MainWindow` 组合根与 demo 数据直灌面板；现有 `ui/qt` 适配模式和测试合同是可靠资产。F1 以纯新增方式建立 QML 壳、Design Tokens、Mock Facade 与写作垂直切片，不改旧 UI、不改后端，为 F2 起的渐进接线保留一条可验证的迁移通道。
