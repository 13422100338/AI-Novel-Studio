# Frontend Wave F13 交付记录（打包票实施）

> 分支：`codex/frontend-wave-f1`（F12 提交之上）
> 日期：2026-08-03
> 范围：落实 F11 评估的打包待办——QML 资源进 wheel、QML 入口、PyInstaller datas/
> hiddenimports；用户已明确批准修改 `pyproject.toml` 与打包 spec。

## 1. 交付内容

- `pyproject.toml`：
  - `[project.gui-scripts]` 新增 `ai-novel-studio-qml = "ai_novel_studio.ui_qml.__main__:main"`；
  - `[tool.setuptools.package-data]` 新增 `ui_qml/qml/**/*.qml` 与
    `ui_qml/qml/**/qmldir`（旧 QWidget 入口保留）；
- `packaging/AI-Novel-Studio.spec`：
  - `datas` 加入 `src/ai_novel_studio/ui_qml/qml` → `ai_novel_studio/ui_qml/qml`；
  - `hiddenimports` 加入 PySide6 QtQml / QtQuick / QtQuickControls2 /
    QtQuickLayouts / QtQuickDialogs / QtQmlModels（WebEngine 相关留到编辑器接线）。

## 2. 验证

| 门禁 | 结果 |
|---|---|
| wheel 构建 | `python -m build --wheel` 成功 |
| wheel 内容 | **17 个 QML/qmldir 文件**全部进入 `ai_novel_studio/ui_qml/qml/**` |
| entry_points | `ai-novel-studio` 与 `ai-novel-studio-qml` 双 GUI script |
| 完整 `pytest` | 949 passed |
| Ruff / MyPy（200 文件）/ `git diff --check` | 全部通过 |

## 3. 修改文件

```text
pyproject.toml                       gui-script + package-data（唯一项目配置改动）
packaging/AI-Novel-Studio.spec       datas + hiddenimports
docs/frontend/2026-08-03-frontend-wave-f13-packaging-implementation.md  本记录
docs/frontend/2026-08-02-frontend-audit-wave-f1.md                      审计表更新
```

## 4. 风险与后续

- 未执行完整 PyInstaller 构建（需要 Windows 打包机/CI 与更长耗时；`windows-package.yml`
  工作流存在但需手动触发）；spec 修改经 wheel 级资源验证，PyInstaller 冒烟记录为
  F6 打包验收项；
- `QQuickStyle` 固定为 Basic/Fusion 仍需在打包入口评估（bootstrap 尚未设置，
  记录为接线点）；
- 编辑器（Tiptap/WebEngine）资源与 spec 追加留到对应 Phase。
