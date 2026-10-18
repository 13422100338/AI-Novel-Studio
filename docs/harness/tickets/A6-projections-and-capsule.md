# HARNESS-V1-A6:AgentStateCapsule + UI Projection 骨架

- 日期:2026-08-14
- 设计来源:v0.3 §14、§55、§64、§66;契约 §12"可立即独立实现"清单
  最后一项(UI Projections)与 §14 回归门禁(前端不得自行推断领域状态)
- 分支:agent/ai-agent-v1;基线:A5 提交 0a5eef0 + 探测修复 371bf96
- 注:附录 D 的 A5/A6/A7 依赖后端 DTO 冻结,按契约 §12 推迟;
  本票承接纯 Harness 的投影层

## 目标

- AgentStateCapsule:设计 §14 全字段运行事实快照(含 ContextHealth /
  OptimizationStatus 枚举),是 UI/恢复/压缩的输入,不是真相源
- HarnessProjectionService 四个只读投影:
  RunStatusProjection / ProcessTimelineProjection(不含敏感 payload)/
  UsageProjection(按角色拆账 + 测量标签)/ RecoveryProjection
  (INTERRUPTED -> RESUME_RUN;STALE -> RECOMPILE_CONTEXT;
  WAITING_APPROVAL -> RESTORE_APPROVAL_VIEW)
- HarnessEventRepository.list_runs / HarnessEventStore.list_runs
  (恢复中心需要枚举 run,无 schema 变更)

## 允许文件

- 新增 src/ai_novel_studio/harness/state_capsule.py / projections.py
- 修改 src/ai_novel_studio/harness/event_repository.py / event_store.py(仅加 list_runs)
- 新增 tests/unit/harness/test_state_capsule.py
- 新增 tests/integration/harness/test_projections.py
- 新增 docs/harness/tickets/A6-projections-and-capsule.md

## 禁止事项

- 不新增 schema / 迁移 / 表
- 不修改前端 UI 代码(前端工作树隔离;本票只交付数据投影)
- 不实现 AgentContextStatusProjection(依赖后端 ContextManifest,A13 再做)
- 不修改 main

## 策略

- UsageProjection 骨架沿用进程级 UsageTracker 拆账(run 级记账需
  ModelRequestManifest 持久化,A4 已定义结构、落库留给后续票)
- 投影不含隐藏思维链、API Key、完整敏感工具输出(设计 §64.1)

## 验收

    .venv\Scripts\python.exe -m pytest tests/unit/harness tests/integration/harness -q --basetemp .test-temp/pytest
    .venv\Scripts\python.exe -m ruff check src tests
    .venv\Scripts\python.exe -m mypy src/ai_novel_studio
