# Frontend Wave F17 交付记录（审校忽略 / 误报）

> 分支：`codex/frontend-wave-f1`（F16 提交之上）
> 日期：2026-08-03
> 范围：审校卡片支持「忽略 / 误报」写操作，经既有应用服务持久化；不改任何后端接口。

## 1. 交付内容

- Facade 新增 `updateAuditFindingStatus(row, status)`：
  - 通过 `ProjectAuditService(project).update_finding_status(finding_id,
    AuditFindingStatus(status))` 持久化（与旧 UI 相同的既有服务入口）；
  - 成功 → 重拉只读视图/概览并提示「审校状态已更新」；
  - 失败（未打开项目、非法状态等）→ 状态栏提示，不改变 UI 状态；
- QML AuditPage：OPEN 状态的卡片显示「忽略 / 误报」按钮；
  更新后状态徽标变化且按钮隐藏（非 OPEN 不再重复操作）。

## 2. 修改文件（全部位于前端允许清单）

```text
src/ai_novel_studio/ui_qml/
├── bridge/mock_novel_studio_facade.py   updateAuditFindingStatus 槽
└── qml/pages/AuditPage.qml              忽略/误报按钮（仅 OPEN）
tests/ui_qml/test_readonly_views.py      忽略/误报/非法状态（+3）
tests/ui_qml/test_qml_shell.py           忽略按钮点击链路（+1）
docs/frontend/2026-08-03-frontend-wave-f17-audit-actions.md  本记录
```

## 3. 验证

| 门禁 | 结果 |
|---|---|
| `pytest tests/ui_qml` | 144 passed |
| 完整 `pytest` | 966 passed |
| Ruff / MyPy（200 文件）/ `git diff --check` | 全部通过 |

关键测试证据（真实模型审校 run + MODEL finding 夹具）：
- 忽略：`status` OPEN → REJECTED，计数仍 1 项（`latest_model_findings` 不过滤状态，
  与后端语义一致），提示「已更新」；
- 误报：OPEN → FALSE_POSITIVE；
- 非法状态：保持 OPEN 并提示失败；
- QML：点击「忽略」→ 模型行状态变 REJECTED + 提示更新。

## 4. 接线细节、风险与下一步

- 这是 F 系列第一个审校写操作：数据直接落入既有审计持久化，无前端旁路；
- 计数/列表仍显示已处理问题（后端 `latest_model_findings` 语义），如需隐藏
  已处理项是产品决策，不在本轮；
- 下一步建议：草稿三视图「编辑后接受」（基于现有 diff 块，纯前端编辑）。
