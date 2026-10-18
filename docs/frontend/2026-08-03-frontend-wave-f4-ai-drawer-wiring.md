# Frontend Wave F4 交付记录（AI 抽屉接线）

> 分支：`codex/frontend-wave-f1`（F3 提交之上）
> 日期：2026-08-03
> 范围：AI 抽屉候选层接真实生成会话与采用服务；演示模式行为不变；
> 不改任何后端接口。

## 1. 交付内容

- 新增 `DraftPort` 端口抽象（`src/ai_novel_studio/ui_qml/bridge/draft_port.py`）：
  `prepare / generate / accept_current / discard_current`，让 facade 与具体模型运行时解耦；
- 真实实现 `ProjectSessionDraftPort`：包装框架中立的 `ProjectGenerationSession`
  （`prepare_generation` → `session.prose.stream` → `accept_current` /
  `discard_current`），其中**采用与放弃走 `GenerationAcceptanceService`** 的安全边界
  （写正文 source=ai_generation、run → ACCEPTED/DISCARDED、expected_revision 校验）；
- `MockNovelStudioFacade` 项目模式接线：
  - 「生成草稿」→ `port.prepare(...)` + `port.generate(run_id)` → 草稿进入候选层并打开 AI 抽屉；
  - 「采用」→ `port.accept_current()` → 正文替换为草稿、修订号推进、进入 CLEAN；
  - 「放弃」→ `port.discard_current()` → 候选清空；
  - 未注入端口时诚实提示「模型生成端口未配置，无法生成草稿（F4 接线点）」，不伪造 AI 输出；
- 演示（mock）模式：生成/采用/放弃维持 F1 行为。

## 2. 修改文件（全部位于前端允许清单）

```text
src/ai_novel_studio/ui_qml/
├── bridge/draft_port.py                      DraftPort Protocol + ProjectSessionDraftPort（新增）
└── bridge/mock_novel_studio_facade.py        project 模式 requestDraft/accept/discard 走端口
tests/ui_qml/test_draft_port.py               真实 session 全链路 + PARTIAL 失败 + discard（新增 4）
tests/ui_qml/test_mock_facade.py              FakeDraftPort + 编排测试（新增 5）
tests/ui_qml/test_qml_shell.py                QML 层注入端口全链路（新增 1）
docs/frontend/2026-08-03-frontend-wave-f4-ai-drawer-wiring.md  本记录
```

## 3. 验证

| 门禁 | 结果 |
|---|---|
| `pytest tests/ui_qml` | 75 passed |
| 完整 `pytest` | 897 passed |
| Ruff / MyPy（194 文件）/ `git diff --check` | 全部通过 |

关键测试证据（`test_draft_port.py`，真实服务、无网络）：
- 用 stub gateway（配置 prose 路由 + 流式事件）构造真实 `ProjectGenerationSession`：
  `prepare → generate → accept_current` 后，磁盘正文 == 草稿、修订 +1、run 状态 ACCEPTED；
- PARTIAL_FAILURE：保留已生成文本、返回错误、run 状态 PARTIAL；
- `discard_current`：run 状态 DISCARDED；
- facade/QML 编排（FakeDraftPort）：生成→候选→采用（正文更新、修订 7、CLEAN）、
  放弃（正文不变）、无端口提示、采用失败保留候选。

## 4. 接线细节、风险与下一步

- **UI 线程阻塞**：`ProjectSessionDraftPort.generate` 同步消费流式迭代器；这是记录在案的
  接线点，后续需前端自有后台协调器（镜像 `ui/qt` 线程模式但不 import 它）把模型调用移出 UI 线程。
- **默认运行时未注入端口**：无模型凭据环境下 bootstrap 不创建 `ProjectSessionDraftPort`，
  UI 走演示数据并显示「端口未配置」，不伪造 AI 结果；注入端口是 F5 或打包期的接线点。
- **生成配置固定**：端口固定 `CreationMode.BASIC`、`AuditPolicy.MINIMAL`、
  `output_token_limit=8192`、`target_words=max(500, 当前字数×2)`；目标字数/创作档位/审校策略
  弹层属延期（方案 Phase 5 的生成配置）。
- **草稿对照三视图未做**（当前正文/草稿/差异、段落级采用）：本轮只提供
  「候选卡片 + 整章采用/放弃」垂直切片。
- 采用仍走 `GenerationAcceptanceService` 的 expected_revision 校验，F3 的 CONFLICT
  恢复逻辑对采用路径同样生效（草稿采用失败不会覆盖正文）。

## 5. 下一步建议

- F5：生成后台化 + 状态/进度（前端自有 QThreadPool 协调器、可取消）；
- 或 F5 先行：生成配置弹层（目标字数、创作档位、审校策略透传端口）。
