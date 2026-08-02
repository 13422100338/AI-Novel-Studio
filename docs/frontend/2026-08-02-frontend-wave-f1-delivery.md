# Frontend Wave F1 交付记录

> 分支：`codex/frontend-wave-f1`（基于 `main` @ `442ae15`）
> 日期：2026-08-02
> 原则：最小正确改动、前后端隔离、不改后端接口、不改现有 QWidget UI。

> 增量 F1.1（2026-08-02）：状态栏新增「收起/展开侧栏」切换按钮，侧栏宽度折叠
> 带动画并遵守 reduce-motion；对应 QML 交互测试 +1（45 个测试）。

## 1. 本轮交付内容

- 现代单窗口 QML Shell：`ApplicationWindow` + Navigation Rail + 可折叠上下文侧栏 + 中央工作区 + 右侧可折叠 AI Drawer + 状态栏；
- Design Tokens：`ThemeProvider`（paper / light / dark 三套 palette + spacing / radius / duration / font，单一 token 源）；
- 基础通用组件：`AppButton`、`IconButton`、`NavigationRail`、`ContextSidebar`、`StatusChip`、`SlidingDrawer`、`SearchField`、`EmptyState`；
- `MockNovelStudioFacade`：QML 唯一数据边界（项目、卷章、编辑器状态机、AI 建议候选层、导航、减少动效），全部确定性 Mock，零后端调用；
- `ChapterListModel` / `SuggestionListModel`：`QAbstractListModel` roles，UI 线程模型变更；
- 一个正文工作区垂直切片：`WritingPage`（卷/章标题、字数、修订、CLEAN/DIRTY/SAVING 状态、保存、章节信息/AI 参考/生成草稿、AI 建议采用/放弃）；
- 前端测试 `tests/ui_qml`（45 个）；截图脚本与 4 张截图。

## 2. 实际修改文件（全部为新增）

```text
src/ai_novel_studio/ui_qml/
├── __init__.py
├── __main__.py                       python -m ai_novel_studio.ui_qml 入口
├── bootstrap.py                      QGuiApplication + QQmlApplicationEngine + 单例注册 + 引用持有
├── bridge/
│   ├── __init__.py
│   ├── dtos.py                       ChapterDto / VolumeDto / SuggestionDto（word_count 确定性计算）
│   ├── text_utils.py                 count_words / format_word_count
│   ├── theme_provider.py             ThemeProvider（Design Tokens 单源）
│   ├── mock_novel_studio_facade.py   MockNovelStudioFacade
│   └── models/
│       ├── __init__.py
│       ├── chapter_list_model.py     卷/章扁平行 + 搜索过滤
│       └── suggestion_list_model.py  AI 建议候选列表
└── qml/
    ├── App.qml                       单窗口 Shell + 状态栏 + 路由
    ├── pages/
    │   ├── qmldir
    │   └── WritingPage.qml           正文工作区垂直切片
    └── components/
        ├── qmldir
        ├── AppButton.qml / IconButton.qml / NavigationRail.qml / ContextSidebar.qml
        ├── StatusChip.qml / SlidingDrawer.qml / SearchField.qml / EmptyState.qml
tests/ui_qml/                         7 个测试文件，44 个测试
scripts/capture_frontend_f1_screenshots.py
docs/frontend/
├── 2026-08-02-frontend-audit-wave-f1.md     只读审计报告
├── 2026-08-02-frontend-wave-f1-delivery.md  本记录
└── screenshots/                           4 张 PNG
```

与审计报告的预计范围相比的唯一偏差：**未改 `pyproject.toml`**（前端隔离约束下不触碰项目配置），运行方式为 `python -m ai_novel_studio.ui_qml`。

## 3. 验证结果

| 门禁 | 命令 | 结果 |
|---|---|---|
| QML 冒烟 | offscreen + software 加载 App.qml，交互链 | 加载成功，0 个 QML 错误 |
| 前端测试 | `pytest tests/ui_qml -q --basetemp .test-temp/pytest-base` | 45 passed |
| 完整测试 | `pytest -q --basetemp .test-temp/pytest-base` | 866 passed（含旧 UI 全部回归） |
| Ruff | `ruff check src tests scripts` | 通过 |
| MyPy | `mypy`（MYPYPATH=src） | 通过，193 个源文件 |
| 隐私扫描 | `privacy_scan --root`（我方目录逐项） | src/ui_qml、tests/ui_qml、docs/frontend、scripts 全部通过 |
| diff 检查 | `git diff --check` | 通过 |

> 注：全仓 `privacy_scan --root .` 在本分支返回非零，唯一命中为
> `docs/handoffs/*.md` 中的既有用户 home 路径（origin/main 已存在，见
> `git show origin/main:docs/handoffs/BACKEND_WORKTREE_BOARD.md`）。该目录属于后端
> 治理文件，前端隔离规则禁止修改，故保留为基线问题上报，不在本轮处理。

## 4. 截图

- `docs/frontend/screenshots/01-shell-paper.png` — 暖灰纸面主题写作工作区；
- `docs/frontend/screenshots/01-shell-light.png` — 编辑浅色主题；
- `docs/frontend/screenshots/01-shell-dark.png` — 深色主题；
- `docs/frontend/screenshots/02-shell-paper-ai-drawer.png` — paper 主题 + AI 建议抽屉（含候选卡片）。

截图由 `scripts/capture_frontend_f1_screenshots.py` 在 offscreen + software 渲染下生成
（1440×900），已验证各主题像素亮度差异显著，非空白图。

> 提交历史：`7f42052`（F1 主体）→ F1.1（侧栏折叠交互，本记录同步更新）。

## 5. 本轮延期事项（不变更）

- 全页面迁移（人物 / 记忆 / 线索 / 审校 / 设置仅占位 EmptyState）；
- 正文编辑器内核（Tiptap / ProseMirror、Qt WebEngine、QWebChannel 协议）；
- 后端接线（真实项目打开、切章、保存冲突、自动保存 800 ms 防抖、AI 主链）；
- 数据库 / Migration、打包安装、默认入口切换、大规模文件搬迁。

## 6. 未来接线点（后端需求备注，仅在本文档记录）

| 前端需求 | 现状（F1） | 未来接线（不做后端接口改动） |
|---|---|---|
| 项目标题/路径 | Mock 常量 | `ProjectRuntime.workspace.summary()` |
| 卷章树 | `ChapterListModel`（mock） | `ProjectRuntime.workspace.volume_tree()` → `VolumeTreeItem`/`ChapterTreeItem` DTO 映射 |
| 正文/修订 | `ChapterDto.body/revision` | `ProjectRuntime.workspace.load_chapter(id)` → `ChapterWorkspace` |
| 保存 | 本地状态机（revision+1） | `ProjectWorkspaceService.save_chapter(id, body, expected_revision=..., requirement_content=..., expected_requirement_revision=..., requirement_locked=...)`；注意现有签名携带 QWidget 专属字段，需要 facade 显式映射 |
| 字数 | facade 确定性 `count_words()` | 保持前端 DTO 计算，不引入每键保存 |
| AI 建议/草稿 | `SuggestionListModel` mock + 本地采用 | `ProjectGenerationSession` + `GenerationAcceptanceService` 安全边界 |
| 任务状态/Token | 状态栏静态“空闲 / Mock” | 复用 `ui/qt` coordinator 的信号语义，收敛为 QML 中立 Facade（不改现有 `ui/qt`） |
| 主题 | 独立 `ThemeProvider`（QSettings 独立） | 方案 6.5：未来与 QWidget appearance 收敛为同一 Theme DTO |
| 入口 | `python -m ai_novel_studio.ui_qml` | F6 打包时再评估 `pyproject`/启动器改动 |

## 7. 风险与已知限制

- QML 单例目前通过 `rootContext().setContextProperty` 注册（仅 Facade、Theme 两个），F6 打包时
  需改为 qmldir 类型注册或至少加入打包资源清单；
- `ThemeProvider` 主题切换未与旧 QWidget appearance/QSettings 同步（刻意隔离，属接线点）；
- 编辑器为 `TextArea` 占位实现，无撤销跨章隔离、无 20 万字符压力证明（方案 Phase 1 未到）；
- `ChapterListModel` 搜索过滤为全量重建（beginResetModel），F2 接入真实项目时若章节量大再评估
  增量过滤；
- Windows pytest 需要预建 `--basetemp`（本机 `C:\CodexTemp` 权限遗留问题），记录在交付说明。

## 8. 下一步建议

1. 合并/评审本分支（不合并 main，由用户决定）；
2. F2：只读项目接线——用 `ProjectRuntime.workspace` 替换 Mock 卷章树与正文载入；
3. F3：保存协议（expected_revision 冲突、DIRTY/SAVING/CONFLICT 状态机接真实服务）。
