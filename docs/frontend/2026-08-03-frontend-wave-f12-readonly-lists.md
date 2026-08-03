# Frontend Wave F12 交付记录（人物/记忆/审校只读列表）

> 分支：`codex/frontend-wave-f1`（F11 提交之上）
> 日期：2026-08-03
> 范围：把 F9 数量概览骨架升级为只读列表视图；不改任何后端接口。

## 1. 交付内容

- 新增 `bridge/readonly_views.py`：
  - `CharacterViewDto`（id/name/aliases/profile/motivation/psychology/goal/
    relationships/recent/location/injury_status）；
  - `MemoryViewDto`（id/category/title/content/source_type/authority/
    review_status/status/revision）；
  - `AuditViewDto`（id/category/severity/evidence/explanation/confidence/status）；
  - `readonly_views()`：通过既有应用服务读取当前章节三类数据
    （人物 `list_cards_for_chapter`、记忆 `MemoryWorkspaceService.load`、
    审校 `latest_model_findings`），三类独立失败降级为空列表；
- 新增 `models/readonly_list_models.py`：`CharacterListModel / MemoryListModel /
  AuditListModel`（QAbstractListModel，各带 roles）；
- Facade：`characterViews / memoryViews / auditViews` 三个模型属性，与 F9 概览
  同刷新时机（打开项目/切章/关闭）；
- QML 三个页面升级为真实只读列表：
  - 人物：卡片（姓名/简介/目标/近况）；
  - 记忆：卡片（标题/分类·来源/内容预览/状态·复核·修订）；
  - 审校：卡片（严重度中文+颜色/证据/说明/置信度·状态）；
  - 各自保留空态说明与数量芯片。

## 2. 修改文件（全部位于前端允许清单）

```text
src/ai_novel_studio/ui_qml/
├── bridge/readonly_views.py              只读视图 DTO + 读取函数（新增）
├── bridge/models/readonly_list_models.py 三个列表模型（新增）
├── bridge/mock_novel_studio_facade.py    三个模型属性 + 刷新
└── qml/pages/CharactersPage.qml / MemoryPage.qml / AuditPage.qml  列表化
tests/ui_qml/test_readonly_views.py       视图/模型/facade（新增 7）
tests/ui_qml/test_qml_shell.py            列表存在 + 空态（+1）
docs/frontend/2026-08-03-frontend-wave-f12-readonly-lists.md  本记录
```

## 3. 验证

| 门禁 | 结果 |
|---|---|
| `pytest tests/ui_qml` | 127 passed |
| 完整 `pytest` | 949 passed |
| Ruff / MyPy（200 文件）/ `git diff --check` | 全部通过 |

关键测试证据：
- 空项目真实服务三列表为空；DTO 冻结字段读取正确；
- 三个模型 roles（id/name/goal、title/category/revision、category/severity 等）暴露正确；
- facade：项目模式三模型 0 行、无项目亦为空（不抛错）；
- QML：三个 ListView 存在，记忆页空态显示。

## 4. 接线细节、风险与下一步

- 只读列表与 F9 概览共用同一批服务调用（同一 `readonly_views`/`readonly_overview_counts`
  各跑一次，当前为空项目成本低；真实大项目若卡顿，合并为一次查询或后台化——记录为接线点）；
- 记忆/审校卡片仅展示轻量字段，正文/证据全文与按需加载留给后续 Wave；
- 下一步建议：
  1. 打包票实施（F11 文档的待办：package-data / gui-script / spec datas）；
  2. 或人物状态时间线/详情（Phase 6 子集）；
  3. 或审校问题定位（双击证据跳转编辑器，Phase 7 子集）。
