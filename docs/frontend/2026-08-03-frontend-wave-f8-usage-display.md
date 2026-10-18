# Frontend Wave F8 交付记录（Token / 费用显示）

> 分支：`codex/frontend-wave-f1`（F7 提交之上）
> 日期：2026-08-03
> 范围：状态栏展示 Token / 费用 / 缓存用量，复用 `UsageSnapshot` 语义；
> 不改 `ui/qt`、不改任何后端接口。

## 1. 交付内容

- 新增前端 `UsageDto`（`bridge/dtos.py`）：input/output/cached tokens、cost、
  call_count、failed_call_count、cache_known——语义对齐后端 `UsageSnapshot`；
- `DraftPort` 增加 `usage_snapshot()`，真实实现
  `ProjectSessionDraftPort.usage_snapshot()` 委托
  `session.gateway.usage_tracker.snapshot()`（只读），FakeDraftPort 返回确定性值；
- Facade 用量状态与格式化：
  - `usageInputOutputText`（如 `1.2K / 800`）、`usageCostText`（`¥0.018` /
    「未估算」）、`usageCacheText`（`缓存 600` / `缓存 未知`）、
    `usageCallsText`（`N 次调用[ · M 失败]`）；
  - 生成 COMPLETED / FAILED / CANCELLED 终态后刷新（失败也保留已统计用量）；
  - 无端口时保持 0/未估算；
- QML 状态栏新增三个芯片：Token（入/出）、费用、缓存；
- 未改旧 QWidget `TopBar`（其 `update_usage(UsageSnapshot)` 语义作为对照基线）。

## 2. 修改文件（全部位于前端允许清单）

```text
src/ai_novel_studio/ui_qml/
├── bridge/dtos.py                          UsageDto（新增）
├── bridge/draft_port.py                    usage_snapshot()（Protocol + 真实实现）
├── bridge/mock_novel_studio_facade.py      用量状态/格式化/终态刷新
└── qml/App.qml                             状态栏 Token/费用/缓存芯片
tests/ui_qml/test_mock_facade.py            生成后/失败后/无端口用量断言（+3）
tests/ui_qml/test_draft_port.py             空 tracker 镜像（+1）
tests/ui_qml/test_qml_shell.py              芯片可见性与更新（+1）
docs/frontend/2026-08-03-frontend-wave-f8-usage-display.md  本记录
```

## 3. 验证

| 门禁 | 结果 |
|---|---|
| `pytest tests/ui_qml` | 113 passed |
| 完整 `pytest` | 935 passed |
| Ruff / MyPy（197 文件）/ `git diff --check` | 全部通过 |

关键测试证据：
- facade：生成前 0 / 0 + 未估算 + 缓存未知；生成完成后 `1.2K / 800`、
  `¥0.018`、`缓存 600`、`1 次调用`；生成失败后仍刷新用量；无端口保持零值；
- 端口：空 `UsageTracker` 快照镜像为全零 DTO（cost=0，facade 层对无调用显示
  「未估算」）；
- QML：三个用量芯片存在，生成完成后值同步更新。

## 4. 接线细节、风险与下一步

- 用量为「当前会话累计」语义（`UsageTracker.snapshot()` 与旧 UI 相同）；
  未做跨会话持久化（与旧 UI 行为一致，不扩范围）；
- 生成失败/取消也会刷新用量（`usage_tracker` 对失败调用有记录，partial 用量保留）；
- `usageCallsText` 当前未直接展示在状态栏（供未来任务详情/工具提示使用）；
- 下一步建议：
  1. 人物 / 记忆 / 审校只读数量概览与页面骨架；
  2. 或打包前 QML 资源清单与入口评估（F6 打包票）；
  3. 或状态栏 Token 芯片加鼠标悬浮显示调用/失败明细。
