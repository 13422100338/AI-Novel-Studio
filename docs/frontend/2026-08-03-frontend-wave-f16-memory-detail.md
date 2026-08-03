# Frontend Wave F16 交付记录（记忆记录详情面板）

> 分支：`codex/frontend-wave-f1`（F15 提交之上）
> 日期：2026-08-03
> 范围：记忆页从只读列表升级为「列表 + 详情面板」；不改任何后端接口。

## 1. 交付内容

- `MemoryListModel` 增加 `memory_at_row(row)`；
- Facade 新增记忆详情状态：
  - `selectMemory(row)` / `closeMemoryDetail()` / `memoryDetailVisible`；
  - 详情属性：标题、分类、内容、来源类型、权威、状态、复核、修订；
  - 切章/关闭项目自动清空选中（与人物详情一致）；
- QML MemoryPage：左侧记忆列表（点击卡片选中、选中态高亮）+ 右侧详情面板
  （标题/分类·来源/正文/权威/状态/复核/修订 + 关闭按钮）。

## 2. 修改文件（全部位于前端允许清单）

```text
src/ai_novel_studio/ui_qml/
├── bridge/models/readonly_list_models.py   MemoryListModel.memory_at_row
├── bridge/mock_novel_studio_facade.py      记忆详情状态/属性/槽
└── qml/pages/MemoryPage.qml                列表 + 详情面板
tests/ui_qml/test_readonly_views.py         真实摘要夹具 + 详情（+3）
tests/ui_qml/test_qml_shell.py              面板可见/关闭（+1）
tests/ui_qml/test_draft_coordinator.py      cancel 终态断言健壮化（跨线程信号顺序）
docs/frontend/2026-08-03-frontend-wave-f16-memory-detail.md  本记录
```

## 3. 验证

| 门禁 | 结果 |
|---|---|
| `pytest tests/ui_qml` | 140 passed |
| 完整 `pytest` | 962 passed |
| Ruff / MyPy（200 文件）/ `git diff --check` | 全部通过 |

关键测试证据（真实项目夹具：第一章摘要 + 第二章边界）：
- `readonly_views` 经记忆工作区加载摘要记录（严格 before 边界，与旧 UI 一致）；
- facade：选中 → 详情字段正确；关闭 → 隐藏；
- QML：导航到记忆页 → 选中 → 详情面板可见 → 关闭生效。

## 4. 接线细节、风险与下一步

- 记忆查询沿用后端 `is_before` 严格边界语义（当前章之前的内容，与旧 UI 记忆窗口一致）；
- 详情为只读展示；编辑/整理/晋升等写操作接线留待 Phase 6 后续；
- 下一步建议：
  1. 审校「忽略 / 误报」写操作（`ProjectAuditService.update_finding_status`）；
  2. 或草稿三视图「编辑后接受」（基于现有 diff 块）。
