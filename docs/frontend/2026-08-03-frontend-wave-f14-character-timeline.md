# Frontend Wave F14 交付记录（人物状态详情与时间线）

> 分支：`codex/frontend-wave-f1`（F13 提交之上）
> 日期：2026-08-03
> 范围：人物页从只读列表升级为「列表 + 详情 + 状态时间线」；不改任何后端接口。

## 1. 交付内容

- `readonly_views.py`：新增 `CharacterJourneyViewDto`（state_id/chapter_id/
  motivation/psychology/goal/relationships/recent_activity），`CharacterViewDto`
  增加 `journey` 字段（来自 `CharacterStatusCard.journey`，后端已审核状态事件）；
- 新增 `CharacterJourneyListModel`（QAbstractListModel，7 个 roles）；
- Facade：
  - `selectCharacter(row)`：选中人物 → 填充详情属性（姓名/档案/动机/心理/目标/
    关系/近况/位置/伤势）与 `characterJourney` 时间线模型；
  - `characterDetailVisible` + `closeCharacterDetail()`；
  - 切章/关闭项目自动清空选中；
- QML CharactersPage：左侧人物列表（点击卡片选中、选中态高亮）+ 右侧详情面板
  （档案/位置/伤势/动机/心理/目标/关系/近况 + 状态时间线 ListView + 关闭按钮）。

## 2. 修改文件（全部位于前端允许清单）

```text
src/ai_novel_studio/ui_qml/
├── bridge/readonly_views.py                    CharacterJourneyViewDto + journey 字段
├── bridge/models/readonly_list_models.py       CharacterJourneyListModel（新增）
├── bridge/mock_novel_studio_facade.py          selectCharacter/详情属性/时间线模型
└── qml/pages/CharactersPage.qml                列表 + 详情 + 时间线
tests/ui_qml/test_readonly_views.py             真实人物夹具 + 时间线（+4）
tests/ui_qml/test_qml_shell.py                  QML 详情面板/关闭（+1）
docs/frontend/2026-08-03-frontend-wave-f14-character-timeline.md  本记录
```

## 3. 验证

| 门禁 | 结果 |
|---|---|
| `pytest tests/ui_qml` | 132 passed |
| 完整 `pytest` | 954 passed |
| Ruff / MyPy（200 文件）/ `git diff --check` | 全部通过 |

关键测试证据（真实项目夹具：1 人物 + 2 章 + 2 个已审核状态事件）：
- `readonly_views`：第一章 journey 1 条、第二章 2 条（时间线按章累积）；
- facade：选中人物 → 详情字段正确 + journey 行数随当前章变化（1 → 2）；
  关闭详情清空；切章自动清空；
- QML：导航到人物页 → 选中 → 详情面板可见、时间线列表出现、关闭按钮生效。

## 4. 接线细节、风险与下一步

- 时间线只含**已审核**状态事件（`state_histories_before_many` 的后端既有语义：
  REVIEW 事件不进入人物卡片历史）——前端未改、未绕过；
- 详情/时间线为只读展示；状态编辑、身份冲突合并留待 Phase 6 后续；
- 下一步建议：
  1. 审校证据定位（双击问题跳转编辑器并高亮，Phase 7 子集）；
  2. 或记忆记录详情面板（当前只读列表的下一层）。
