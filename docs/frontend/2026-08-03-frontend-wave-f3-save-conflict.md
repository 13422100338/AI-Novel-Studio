# Frontend Wave F3 交付记录（真实保存与修订冲突）

> 分支：`codex/frontend-wave-f1`（F2 提交之上）
> 日期：2026-08-03
> 范围：项目模式下「保存」接真实持久化；修订冲突进入 CONFLICT 状态并可显式恢复；
> 不改任何后端接口。

## 1. 交付内容

- `MockNovelStudioFacade.requestSave()` 项目模式改为调用
  `ProjectWorkspaceService.save_chapter(chapter_id, content, expected_revision=...)`；
  成功返回 `SaveChapterResult` 后更新修订号并进入 CLEAN；
- 修订过期（后端 `StaleChapterRevisionError` 包装为
  `RuntimeError("chapter revision is stale")`）→ 编辑器进入 `CONFLICT`：
  - 不覆盖磁盘内容；
  - 状态栏显示「正文已在其他位置修改（修订冲突）· 未覆盖任何内容，请重新载入」；
  - 冲突期间继续输入不退出 CONFLICT（避免误以为可以保存）；
- 新增 `reloadChapter()`：仅 CONFLICT 可用，显式放弃本地未保存修改并从磁盘重载
  （用户主动点击，不自动执行）；
- QML：WritingPage 新增「放弃本地修改并重新载入」按钮（仅 CONFLICT 可见）；
  status chip 增加「修订冲突 / danger」；App 状态栏自动保存芯片增加冲突态；
- 演示（mock）模式保存行为不变。

## 2. 修改文件（全部位于前端允许清单）

```text
src/ai_novel_studio/ui_qml/
├── bridge/mock_novel_studio_facade.py  requestSave 真实持久化 + CONFLICT + reloadChapter
├── qml/pages/WritingPage.qml           冲突状态展示 + 重新载入按钮
└── qml/App.qml                         自动保存状态芯片冲突态
tests/ui_qml/test_project_wiring.py     保存持久化/冲突/恢复/冲突期编辑（5 个新增）
tests/ui_qml/test_qml_shell.py          QML 层保存按钮→冲突→重新载入按钮恢复（1 个新增）
docs/frontend/2026-08-03-frontend-wave-f3-save-conflict.md  本记录
```

## 3. 验证

| 门禁 | 结果 |
|---|---|
| `pytest tests/ui_qml` | 65 passed |
| 完整 `pytest` | 887 passed |
| Ruff / MyPy / `git diff --check` | 全部通过 |

关键测试证据：
- `test_save_persists_to_disk_and_bumps_revision`：Facade 保存后关闭项目，再以独立
  `ProjectWorkspaceService` 打开同一项目，正文与修订号（1→2）与磁盘一致；
- `test_save_detects_stale_revision_conflict`：仓储层外部写入（修订 1→2）后，
  Facade 以旧修订保存 → CONFLICT，磁盘未被覆盖；
- `test_reload_chapter_recovers_after_conflict`：重新载入后正文为外部版本、修订 2；
- QML 层：点「保存」→ CONFLICT（重新载入按钮可见）→ 点按钮 → CLEAN + 外部正文。

## 4. 接线细节与风险

- 冲突检测依赖服务层的稳定错误包装（`RuntimeError("chapter revision is stale")`）；
  若未来后端改成独立异常类型，facade 需要同步适配（记录为接线点）。
- 冲突恢复会**放弃本地未保存修改**：仅通过显式按钮触发，文案已明示，符合
  「不静默删除用户内容」。
- 章节要求（requirement）在 F3 中不随保存写入（`requirement_content=None`），
  与旧 UI 每次全量保存的语义不同，属于刻意的最小改动；后续需要时再接线。
- 无防抖自动保存（800 ms）与窗口关闭拦截：这是 F3 明确范围之外，留待后续。

## 5. 下一步建议

- F4：AI 抽屉接线（`ProjectGenerationSession` + `GenerationAcceptanceService`）；
- 或先做保存协议的补充：窗口关闭/切章前强制保存、防抖自动保存、冲突对比界面。
