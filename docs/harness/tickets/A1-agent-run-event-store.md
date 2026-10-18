# HARNESS-V1-A1:AgentRun + RunEvent + EventStore

- 日期:2026-08-14
- 设计来源:《agent-harness-design-v0.3》§14、§52-§57、§62.1、§63-§64;
  《agent-implementation-backend-contract-v0.1》§12"可立即独立实现"清单第 1 项
- 分支:agent/ai-agent-v1;工作树:.codex/worktrees/ds-agent;基线 main @ e6a9873

## 目标

建立 Harness 自己的不可变事件日志基础:run 生命周期记录 + 强类型事件 +
追加式 EventStore(严格序列、event_id 幂等、终态拒绝迟到事件、重放)。

## 允许文件

- 新增 src/ai_novel_studio/domain/agent_run.py(RunStage / RunEventType / HarnessRun / RunEvent)
- 新增 src/ai_novel_studio/infrastructure/storage/schema_migrations_v21.py
- 修改 src/ai_novel_studio/infrastructure/storage/schema_migrations.py(仅注册 v21)
- 新增 src/ai_novel_studio/infrastructure/storage/harness_event_repository.py
- 新增 src/ai_novel_studio/application/harness_event_store.py
- 新增 tests/unit/domain/test_agent_run.py
- 新增 tests/integration/storage/test_harness_schema.py
- 新增 tests/integration/storage/test_harness_event_store.py
- 机械更新 9 个既有测试文件中的 LATEST_SCHEMA_VERSION == 20 断言为 21
  (agent / audit / character_identity / embedding / generation / memory /
  occurrence / project_repository / subject_registry 的 schema 测试)

## 禁止事项

- 不修改 legacy Phase-7 AgentRun / agent_repository / agent_loop_service
  (旧 Pipeline 的处置按契约 §4 留给后续票据)
- 不建立第二套领域表:harness_runs / harness_run_events 是运行编排事件,
  不是小说领域真相
- 不修改正文权威链、Context Compiler、Context/Manifest、审批链
- 不引入 Backend -> Harness 反向依赖(本票没有)

## DCP-1(命名,需作者知悉)

设计文档称运行记录为 AgentRun(事件表 agent_run_events);仓库已有 Phase-7 的
AgentRun(表 agent_runs),同名冲突。本票采用 harness_runs / harness_run_events /
HarnessRun / RunEvent。如作者要求其他命名,请在本票评审时提出。

## Schema v21 集成注意

- 当前 schema 所有权已释放(O1a-S 集成完毕),v21 是纯追加、无数据迁移。
- 后端分支若也推进到 v21,集成时由用户协调版本序号;回滚 = 删除
  schema_migrations_v21.py 与注册行,并把 9 处断言改回 20。

## 事件语汇

36 个 RunEventType,与设计 §63 列表一致。不含 RUN_STAGE_CHANGED:阶段变更
记录在 harness_runs.stage,是否追加阶段事件留给后续票据。

## 策略(A1 冻结范围)

- 终态(COMPLETED / CANCELLED / FAILED)拒绝追加事件与阶段变更;
  INTERRUPTED / STALE 保持开放以便恢复(设计 §55)。
- RUN_CREATED 由 start_run 独占,固定 sequence 0。
- 调用方提供 event_id 时幂等:同 run + 同 type -> 返回已有事件;
  跨 run 或异 type -> HarnessEventIdempotencyError。
- 事件不可变:repository 不提供 update / delete。

## 验收

    .venv\\Scripts\\python.exe -m pytest tests/unit/domain/test_agent_run.py tests/integration/storage/test_harness_schema.py tests/integration/storage/test_harness_event_store.py tests/integration/storage/test_agent_schema.py -q
    .venv\\Scripts\\python.exe -m ruff check src tests
    .venv\\Scripts\\python.exe -m mypy src/ai_novel_studio
