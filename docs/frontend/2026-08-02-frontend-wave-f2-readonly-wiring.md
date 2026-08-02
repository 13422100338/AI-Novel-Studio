# Frontend Wave F2 交付记录（只读项目接线）

> 分支：`codex/frontend-wave-f1`（F1 提交之上）
> 日期：2026-08-02
> 范围：真实项目只读接入——卷章树、章节正文与修订号经 Facade 加载到 QML；
> 不写任何项目文件、不改后端接口。

## 1. 交付内容

- `MockNovelStudioFacade` 新增真实项目模式：
  - `openProject(path)` / `openProjectFromUrl(QUrl)`：通过只读应用服务
    `ProjectWorkspaceService` 打开项目，映射 `volume_tree()` → `VolumeDto`，
    自动载入第一章节；
  - `closeProject()`：释放项目锁并恢复演示数据；
  - `projectSource` 属性（`mock` / `project`）供状态栏展示；
  - 真实项目模式下保存为会话内状态，明确标注「F3 接线点 · 未写入磁盘」，不伪造持久化；
- `ChapterDto` 增加 `declared_number` 与可选 `word_count`（正文为空时由树节点字数传入）；
- QML：侧栏新增「打开项目 / 重置演示」按钮与 `FolderDialog`，打开失败时显示错误；
  状态栏新增「数据源」状态芯片；
- 测试：`tests/ui_qml/test_project_wiring.py`（8 个）+ QML 接线测试 2 个。

## 2. 修改文件（全部位于前端允许清单）

```text
src/ai_novel_studio/ui_qml/
├── __init__.py                       边界说明更新（消费只读应用服务）
├── bridge/dtos.py                    ChapterDto：declared_number + word_count
├── bridge/mock_novel_studio_facade.py  openProject / closeProject / projectSource
└── qml/components/ContextSidebar.qml   打开项目/重置演示 + FolderDialog + 错误显示
└── qml/App.qml                       数据源状态芯片
tests/ui_qml/test_project_wiring.py    新增（8 个）
tests/ui_qml/test_qml_shell.py         +2（项目加载进编辑器、重置回演示）
docs/frontend/2026-08-02-frontend-wave-f2-readonly-wiring.md  本记录
```

## 3. 验证

| 门禁 | 结果 |
|---|---|
| `pytest tests/ui_qml` | 60 passed |
| 完整 `pytest` | 882 passed |
| Ruff / MyPy / `git diff --check` | 全部通过 |

## 4. 接线细节与风险

- 本轮只接线 `ProjectWorkspaceService`（应用层只读）；`ProjectRuntime` 需要
  LLM gateway，留给 F4/F5 的 AI 主链，不提前引入。
- `volume_tree()` 对每章调用 `read_content()` 计算字数（既有后端行为，与旧 UI
  一致）；真实大项目侧栏刷新性能与旧 UI 基线持平即可，暂不做增量过滤。
- 真实项目打开会获取 `ProjectLock`；`closeProject()` 与再次 `openProject()` 都会
  释放旧锁（`open_project` 内部先 `close_project`），测试与退出路径均已覆盖。
- 保存仍是会话内 Mock（`currentRevision` 不推进、不写盘），UI 文案明确
  「F3 接线点」，避免误导。
- QML `FolderDialog` 通过 `QUrl` 传入；`openProjectFromUrl` 兼容字符串直调
  （Python 测试），QML 路径走 QUrl 规范化。

## 5. 下一步（F3）

真实保存接线：`ProjectWorkspaceService.save_chapter(id, content, expected_revision=...)`
接 `requestSave`，处理 `StaleChapterRevisionError` → CONFLICT 状态机与对比/恢复界面；
仍不改后端接口。
