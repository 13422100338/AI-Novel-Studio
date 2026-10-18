# HARNESS-V1-B6:AgentContextStatusProjection + 上下文状态栏命令

- 日期:2026-08-15
- 设计来源:v0.3 §14、§64、§65-§66;handoff 2026-08-14 §4(B6)
- 分支:agent/ai-agent-v1(ds-agent 工作树)
- 依赖:A6 胶囊定义、B1 编译事件、B2 流式事件、A8a 审批、A2 用量(均已实现)

## 目标

在 HarnessProjectionService 上新增两条确定性命令(纯派生,零写入)——

1. capsule(run_id) -> AgentStateCapsule:从 run 记录 + 事件日志 + 审批库
   派生 §14 胶囊——
   - run_id/goal/stage/active_chapter_id ← run 记录;
   - context_manifest_id / context_budget(最近一次编译的 estimated
     input tokens)← 最近 CONTEXT_COMPILED 事件 payload;
   - pending_approvals ← 审批库 PENDING 请求 id;loaded_skills/loaded_tools
     ← SKILL_LOADED / TOOL_SCHEMA_LOADED 事件(去重保序);
   - context_health:无编译事件→UNKNOWN;STALE→CRITICAL;否则 HEALTHY;
   - optimization_status:无编译事件→UNKNOWN;STALE/INTERRUPTED→
     NEEDS_RECOMPILE;否则 OPTIMIZED;
   - 尚无生产者的字段(editor/formal/summary revisions 等)为 None,
     plan/assumptions/unresolved 为空——不发明第二真相;
2. context_status(run_id) -> AgentContextStatusProjection:上下文状态栏
   视图——胶囊字段 + 最近编译 manifest/证据命中/类别构成 + 最近
   CHAPTER_STREAM_COMPLETED 草稿工件与字数 + 检查点次数 + 待审批 +
   分角色用量(meter 未接线为空)。

## 允许文件

- 修改 src/ai_novel_studio/harness/projections.py(新增投影类型与两条命令)
- 修改 tests/integration/harness/test_projections.py(新增测试)
- 新增 docs/harness/tickets/B6-context-status-projection.md

## 禁止事项

- 无 schema 变更;不持久化胶囊/投影(纯派生);不改 run_engine 构造;
- 不把用量、事件、审批之外的任何存储当真相;不合并 main

## 已知限制

- health/optimization 为事件驱动启发式,后续 compaction(A10a 事件)
  与 STALE 传播接入时再细化
- editor_snapshot_revision / formal_revision 等字段待 GENERATION_PACKAGE_
  READY 事件生产者(B8)后填入

## 验收

    .venv\Scripts\python.exe -m pytest tests/integration/harness/test_projections.py tests/unit/harness tests/integration/harness -q --basetemp .test-temp/pytest
    .venv\Scripts\python.exe -m ruff check src tests
    .venv\Scripts\python.exe -m mypy src/ai_novel_studio
