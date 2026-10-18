# Frontend Wave F9 交付记录（人物/记忆/审校只读数量概览与页面骨架）

> 分支：`codex/frontend-wave-f1`（F8 提交之上）
> 日期：2026-08-03
> 范围：三个工作区页面骨架 + 当前章节只读数量概览；不改任何后端接口。

## 1. 交付内容

- 新增只读计数模块 `bridge/overview_counts.py`：
  - 人物：`CharacterStatusService(CharacterMemoryRepository(project)).list_cards_for_chapter(...)`
    计数（与旧 UI 同一应用服务语义）；
  - 记忆：`MemoryWorkspaceService(ProjectMemoryWorkspaceGateway(project)).load(chapter_id)`
    记录数；
  - 审校：`ProjectAuditService(project).latest_model_findings(chapter_id)` 当前可见问题数；
  - 三个查询相互独立、各自失败降级为 `None`（UI 显示 `—`），不阻断项目加载；
- Facade：`characterCountText / memoryCountText / auditCountText`
  （`N 人 / N 条 / N 项`，无项目或失败为 `—`）；
  打开项目、切章、关闭项目时刷新；
- QML：新增 `OverviewPlaceholderPage` 组件与 `CharactersPage / MemoryPage / AuditPage`
  三个页面骨架（标题 + 数量 StatusChip + 迁移说明）；App StackLayout 扩为 6 态，
  线索/设置仍为占位说明。

## 2. 修改文件（全部位于前端允许清单）

```text
src/ai_novel_studio/ui_qml/
├── bridge/overview_counts.py              OverviewCounts + readonly_overview_counts（新增）
├── bridge/mock_novel_studio_facade.py     计数属性 + 刷新时机
├── qml/components/OverviewPlaceholderPage.qml  页面骨架组件（新增）
├── qml/components/qmldir                  注册组件
├── qml/pages/CharactersPage.qml / MemoryPage.qml / AuditPage.qml（新增）
├── qml/pages/qmldir                       注册页面
└── qml/App.qml                            6 态 StackLayout + navIndex
tests/ui_qml/test_overview_counts.py       计数服务 + facade 状态（新增 5）
tests/ui_qml/test_qml_shell.py             页面存在/可见/计数芯片（+1）
docs/frontend/2026-08-03-frontend-wave-f9-overview-pages.md  本记录
```

## 3. 验证

| 门禁 | 结果 |
|---|---|
| `pytest tests/ui_qml` | 119 passed |
| 完整 `pytest` | 941 passed |
| Ruff / MyPy（198 文件）/ `git diff --check` | 全部通过 |

关键测试证据：
- 空项目真实服务：人物 0 / 记忆 0 / 审校 0；
- facade：项目模式 `0 人 / 0 条 / 0 项`；无项目与关闭项目后 `—`；
- QML：三个页面 objectName 存在，导航到人物页可见且计数芯片显示 `0 人`。

## 4. 接线细节、风险与下一步

- 计数在打开/切章时同步读取（主线程）：真实大项目下 `load_before` 会加载记忆记录，
  概览成本与旧 UI 记忆工作区一致；若大项目出现卡顿，再评估后台计数（记录为接线点）；
- 审校计数只统计「当前可见」的模型审校问题（沿用 `latest_model_findings` 的
  hash 校验语义），旧 UI 行为一致；
- 下一步建议：
  1. Token 芯片悬浮显示调用/失败明细（F10）；
  2. 打包前 QML 资源清单与入口评估（F11，只读审计 + 前端文档）。
