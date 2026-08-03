# Frontend Wave F11 交付记录（打包前 QML 资源清单与入口评估）

> 分支：`codex/frontend-wave-f1`（F10 提交之上）
> 日期：2026-08-03
> 范围：只读审计打包现状、列出 QML 资源清单、评估入口；
> 本轮不修改任何打包配置（spec / pyproject 属于打包票，需用户批准后再改）。

## 1. 现状基线（只读核实）

| 项 | 现状 | 影响 |
|---|---|---|
| `pyproject.toml` gui-script | 仅 `ai-novel-studio = ai_novel_studio.__main__:main`（旧 QWidget） | QML 入口无独立 script |
| `[tool.setuptools.package-data]` | 仅 `ai_novel_studio = ["py.typed"]` | **ui_qml 的 .qml / qmldir 不会进入 wheel** |
| `packaging/AI-Novel-Studio.spec` | `datas=[]`、`hiddenimports=[]`，EXE+COLLECT（onedir） | 即使 wheel 补上 QML，PyInstaller 也不会复制 |
| 开发入口 | `python -m ai_novel_studio.ui_qml` 可用（bootstrap 已加 import path） | 开发可运行 |
| PySide6 | 6.11.1（pyproject 约束 `>=6.8,<7`），site-packages 含 `qml/` 与 QtWebEngineQuick | Qt 自带 QML 模块齐全；WebEngine 本轮未用 |

## 2. QML 资源清单（打包时必须包含）

```text
src/ai_novel_studio/ui_qml/qml/
├── App.qml
├── components/  (qmldir + 11 个 .qml)
│   ├── AppButton / IconButton / NavigationRail / ContextSidebar / StatusChip /
│   ├── SlidingDrawer / SearchField / EmptyState / OverviewPlaceholderPage /
│   └── GenerationConfigDialog
└── pages/       (qmldir + WritingPage / CharactersPage / MemoryPage / AuditPage)
```

共 **17 个文件**（2 个 qmldir + 15 个 .qml）。运行入口 `ui_qml/__main__.py`
经 `bootstrap.app_qml_path()` 从包内定位 `App.qml`，因此只要这些文件被复制到
包目录即可解析（无需 qrc 预编译；打包票可评估 qrc 作为备选）。

## 3. 入口评估结论

- 开发：`python -m ai_novel_studio.ui_qml` 已可用（本分支测试覆盖）；
- 正式发布需新增 GUI script（如 `ai-novel-studio-qml =
  ai_novel_studio.ui_qml.__main__:main`）或改 spec 的 Analysis 入口——属打包票；
- 旧 QWidget 入口在迁移期保持（方案 9 的 Phase 9 才切换默认入口）。

## 4. 打包票待办（仅记录，需用户批准后实施）

1. `pyproject.toml`：
   - `package-data` 增加 `"ui_qml/qml/**/*.qml"` 与 `"ui_qml/qml/**/qmldir"`；
   - 新增 `ai-novel-studio-qml` gui-script 入口；
2. `packaging/AI-Novel-Studio.spec`：
   - `datas` 加入 `ui_qml/qml` 目录（相对包路径）；
   - `hiddenimports` 按实际使用加入 PySide6 模块（QtQml、QtQuick、
     QtQuickControls2、QtQuickLayouts、QtQuickDialogs、QtQmlModels 等）；
   - QtWebEngine 相关资源仅在编辑器接线（F1 的 Phase 1 闸门）后追加；
3. `QQuickStyle` 在创建引擎前固定为 `Basic` / `Fusion`（方案 7.1 已注明
   FluentWinUI3 控件不完整）；
4. 构建验证：
   - `python -m build --wheel` 后检查 wheel 内含 `ui_qml/qml/**`；
   - PyInstaller 构建后冒烟：QML 窗口加载、主题切换、三视图正常；
   - offscreen 冒烟已有脚本 `scripts/capture_frontend_f1_screenshots.py` 可复用。

## 5. 本轮修改文件

```text
docs/frontend/2026-08-03-frontend-wave-f11-packaging-assessment.md  本记录
docs/frontend/2026-08-02-frontend-audit-wave-f1.md                  审计表更新
```

未修改 `pyproject.toml`、`packaging/*.spec`、`launch.*`、`scripts/*`。

## 6. 风险

- 若跳过打包票直接发布：wheel 缺 QML → 安装后 `ui_qml` 无法加载（开发环境因
  源码目录在而正常，容易漏测）；
- `datas` 若用通配符复制整个 `qml/`，需排除截图/临时文件（当前目录无此类文件）；
- 后续编辑器接线（Tiptap/WebEngine）会再增加一批资源，建议打包票只处理
  当前 F1 范围，编辑器资源留到对应 Phase。
