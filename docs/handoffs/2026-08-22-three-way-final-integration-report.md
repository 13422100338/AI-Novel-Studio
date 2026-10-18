# 2026-08-22 三端最终集成验收报告

## 状态

- 事件：`READY_FOR_FINAL_REVIEW`
- 分支：`codex/final-three-way-integration`
- 后端基线：`bc4216e6d091d8102d5b0f4532ad766bf4249fdb`
- 最新已验收业务 HEAD：`5408fa0`（本文档提交位于其后）
- 工作树/索引：干净
- 未执行：push、正式 main 合并、Board 更新、用户数据迁移

## 已整合来源

1. OpenCode Gate E1 后端最终波次：
   `opencode/backend-final-wave-stack@bc4216e6d091d8102d5b0f4532ad766bf4249fdb`
2. 同仓前端 Wave F1：
   `codex/frontend-wave-f1@eb1cb61`
3. 独立前端稳定线：
   `frontend-clean/main@cf74f21`
   - 仅重放稳定提交 `fdbb2fa..cf74f21`
   - 未纳入后续 BlockHelm/C1 实验线 `cf74f21..68302f7`，仅在
     2026-08-23 前端刷新中选择性移植末端 WebEngine 崩溃修复
4. 独立前端扁平壳刷新：
   `codex/frontend-agent-c1@7f04870`
   - `68302f7` — WebEngine 静态画布颜色修复
   - `bf8aa9e` — 扁平现代壳，原生玻璃改为 `--glass` 显式启用
   - `7f04870` — 扁平壳契约测试与截图
   - 未纳入中间 BlockHelm/GlassLab 诊断提交、实验脚本及实验截图
5. Agent Harness：
   `agent/ai-agent-v1@2dd9d6295c0fa2b8b233b33e2aff23b0842f467a`

主要集成提交：

- `a000fa4` — integrate frontend wave F1
- `0944282` — update editor test dependency security patch
- `5752e52` — add frontend interface contracts
- `2b4c26c` — normalize frontend integration whitespace
- `f3a90b2` — integrate agent harness v1
- `70e4744` — normalize integrated frontend checks
- `4d5f4a8` — port WebEngine static canvas crash fix
- `bb7b685` — integrate flat modern frontend shell
- `9e367be` — integrate flat shell contract tests and screenshots
- `5408fa0` — align integrated static canvas test contract

## 冲突解决与必要修正

### Context / Evidence

- 保留后端已验收的 Context Manifest v3 `retrieval_trace`，不恢复 Harness 旧
  `evidence_items`。
- Harness `CompileStepAdapter` 和 `CoreToolService` 复用公共
  `CompileContextService`。
- `FormalEvidenceQueryService` 收敛为公共 `EvidenceQueryService` 的兼容层，
  不保留第二套检索实现。

### Tool 边界

- 增加 `CoreToolQueryService` application facade。
- `harness/core_tools.py` 不再直接 import storage repository。
- 新增静态边界回归，禁止 Tool -> Storage。

### Subject merge 并发安全

- `expected_revisions` 继续在 Harness 层做早期冲突提示。
- 同时在 `CharacterIdentityRepository.apply_merge()` 的真实写事务中复核
  source state-event count，关闭预检后、提交前的竞态窗口。

### Frontend / npm

- 将测试链中的 `nanoid` 从 3.3.16 更新到 3.3.18。
- `npm audit` 为 0 vulnerabilities。
- 仅做 Ruff 所需的历史导入排序、未使用变量和安全 `zip(strict=True)` 机械清理。
- 2026-08-23 刷新后，生产壳默认使用不透明扁平界面；原生玻璃仅在显式
  `--glass` 时启用，`--no-glass` 保留为兼容 no-op。
- 导航改用矢量图标和整行选中态；章节保存/重载/取消操作收敛到章节菜单；
  AI 输入区使用内嵌圆形发送按钮。

## 最终门禁

- 全量 Pytest：`1987 passed in 220.38s`（2026-08-23 前端刷新后复验）
- Harness/Context/Evidence/Subject/schema 合并前门禁：`312 passed`
- Harness 与新增 facade/schema 门禁：`277 passed`
- UI/QML：`291 passed`
- Editor Vitest：`131 passed`
- Editor TypeScript typecheck：通过
- Editor build：通过
- npm audit：`0 vulnerabilities`
- Ruff 全仓：通过
- MyPy：`286 source files`，0 issues
- `git diff --check`：通过

## 明确未完成/不在本次范围

1. QML Agent 面板仍由 `MockNovelStudioFacade` 驱动；真实 Harness -> QML
   timeline/approval/cancel 接线是独立 UI 集成票。
2. 后端 `ProjectRuntime` 不直接 import Harness。现有边界规定
   application/core/domain/infrastructure 不得反向依赖 Harness；生产组合应由
   UI/启动层调用 Harness 的 `for_project(...)` 工厂。
3. 未对既有 CRLF 历史数据做原地修复；该动作会改用户数据，仍需逐项目授权。
4. 未纳入中间 BlockHelm/GlassLab 实验分支；仅选择性纳入 WebEngine 崩溃修复
   和最终扁平壳提交。

## 最终集成结论

三端代码、schema v21-v24、公共 Context/Evidence 契约和 Harness 后端能力已经在
专用集成分支中兼容合并并通过全量门禁。当前可以进入主控最终代码审查和正式
main 快进/合并决策；真实 Agent UI 接线应作为后续独立票，不应在本次合并中
混入。2026-08-23 已在同一分支完成最新扁平前端刷新，并再次通过全量门禁。
