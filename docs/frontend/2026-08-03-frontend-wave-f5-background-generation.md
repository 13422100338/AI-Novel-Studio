# Frontend Wave F5 交付记录（生成后台化与取消）

> 分支：`codex/frontend-wave-f1`（F4 提交之上）
> 日期：2026-08-03
> 范围：AI 草稿生成移出 UI 线程、可取消、任务状态可视化；演示模式行为不变；
> 不改任何后端接口。

## 1. 交付内容

- 新增前端自有后台协调器 `DraftCoordinator`
  （`src/ai_novel_studio/ui_qml/bridge/draft_coordinator.py`）：
  - 基于 `QThreadPool` 的后台任务，**不 import 旧 QWidget 适配层**
    （`ai_novel_studio.ui.qt`），遵守前端隔离；
  - `status_changed` 信号暴露状态机：`IDLE → QUEUED → GENERATING →
    COMPLETED / FAILED / CANCELLED`；终态自动清理 run 引用；
  - 重复启动被拒绝；无端口立即 FAILED；
- `DraftPort` 增加 `cancel(run_id)`，真实端口委托
  `ProjectGenerationSession.prose.cancel`（协作式取消 token）；
- `MockNovelStudioFacade` 异步接线：
  - `requestDraft` 仅 `prepare`（UI 线程）后交给协调器，不再同步阻塞；
  - `draftStatus` 属性驱动状态栏任务芯片与生成按钮；
  - `cancelDraft()` 槽（仅 QUEUED/GENERATING 生效）；
  - 草稿就绪后进入候选层并打开 AI 抽屉（不变）；
- QML：WritingPage 生成中显示「取消生成」按钮（生成按钮禁用）；
  App 状态栏任务芯片映射 QUEUED/GENERATING/COMPLETED/FAILED/CANCELLED；
- 取消不修改正式正文，候选层不产生草稿卡片。

## 2. 修改文件（全部位于前端允许清单）

```text
src/ai_novel_studio/ui_qml/
├── bridge/draft_coordinator.py             DraftCoordinator + 状态常量（新增）
├── bridge/draft_port.py                    cancel(run_id)（Protocol + 真实实现）
├── bridge/mock_novel_studio_facade.py      异步生成/取消/状态同步
├── qml/pages/WritingPage.qml               取消生成按钮 + 生成按钮禁用
└── qml/App.qml                             任务状态芯片
tests/ui_qml/test_draft_coordinator.py       后台完成/状态转移/取消/失败/双重启动（新增 6）
tests/ui_qml/test_mock_facade.py             FakeDraftPort 支持阻塞/取消；编排测试异步化（+1 取消测试）
tests/ui_qml/test_qml_shell.py               QML 层生成链路等待异步完成
docs/frontend/2026-08-03-frontend-wave-f5-background-generation.md  本记录
```

## 3. 验证

| 门禁 | 结果 |
|---|---|
| `pytest tests/ui_qml` | 83 passed |
| 完整 `pytest` | 905 passed |
| Ruff / MyPy（195 文件）/ `git diff --check` | 全部通过 |

关键测试证据：
- 后台完成：`waitSignal(draft_ready)` → 文本正确、状态 COMPLETED、run 清理；
- 状态转移顺序：QUEUED → GENERATING → COMPLETED；
- 协作取消：阻塞中的生成收到 cancel 后返回 CANCELLED，正文与候选层不变；
- 失败：错误文案 + FAILED；重复启动被拒绝；无端口立即 FAILED；
- facade/QML：异步生成 → 候选 → 采用全链路通过；取消后状态 CANCELLED、正文不变。

## 4. 接线细节、风险与下一步

- 取消是协作式的：`prose.cancel` 设置取消 token，流在下一个事件边界退出并保留
  已收内容（PARTIAL 语义由服务层保证），不会中断正在写入的检查点；
- `DraftCoordinator` 使用全局线程池，任务数量限制由 Qt 线程池策略控制；
  QThreadPool 单例在测试进程间共享，测试用例均为短任务，无泄漏迹象；
- 信号跨线程自动排队到 UI 线程（Qt 队列连接），facade 状态更新不会并发写；
- 生成配置仍固定（BASIC/MINIMAL/8192），目标字数/档位/审校策略弹层仍是延期项；
- 下一步建议：
  1. 生成配置弹层（目标字数、创作档位、审校策略透传端口）；
  2. 或草稿三视图（当前正文/AI 草稿/差异）与段落级采用；
  3. 或 Token/费用显示（复用 `UsageSnapshot` 语义，不改现有 `ui/qt`）。
