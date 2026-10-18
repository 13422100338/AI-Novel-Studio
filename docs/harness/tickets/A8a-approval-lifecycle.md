# HARNESS-V1-A8a:审批生命周期骨架(Harness 所有)

- 日期:2026-08-14
- 设计来源:v0.3 §54、§55、§57、§63-§64;契约 §8.1;
  后端只读审计结论(2026-08-14):"ApprovalRequest 生命周期归 Harness 所有,
  后端只验证审批凭证并执行确定性提交"
- 分支:agent/ai-agent-v1;基线:A6b 提交 1410c81 + 文档提交 354aabe/4750b1b
- Schema:本票占用 v22(用户已决定方案 A:先合并 Harness v21/v22 再开后端
  新迁移;后端新迁移由主控从 v23 起分配)

## 目标

- ApprovalRequest 记录(PENDING -> APPROVED/REJECTED,五类 kind,payload 为
  不透明 JSON、内容由后端冻结 DTO 后填充;expected_revisions 并发控制元数据)
- ApprovalService:request_approval(终态 run 拒绝;按 (run_id, idempotency_key)
  幂等;追加 APPROVAL_REQUESTED 事件;run 转 WAITING_APPROVAL)与
  resolve_approval(仅 PENDING 可决议;追加 APPROVAL_RESOLVED 事件)
- 持久化:harness_approvals 表(schema v22,UNIQUE(run_id, idempotency_key))
- HarnessProjectionService.approvals(run_id):恢复中心审批卡数据(设计 §55)

## 允许文件

- 新增 src/ai_novel_studio/infrastructure/storage/schema_migrations_v22.py
- 修改 schema_migrations.py(注册 v22)
- 新增 harness/approvals.py / approval_repository.py / approval_service.py
- 修改 harness/projections.py(approvals 投影)
- 新增 tests/unit/harness/test_approvals.py
- 新增 tests/integration/harness/test_approval_service.py
- 修改 tests/integration/storage/test_harness_schema.py(v22 表测试)
- 机械更新 10 个测试文件的 LATEST_SCHEMA_VERSION 断言 21->22 与
  occurrence future probe 22->23
- 新增 docs/harness/tickets/A8a-approval-lifecycle.md

## 禁止事项

- 不实现审批解决器对后端 commit Facade 的调用(等 ChangeSet 等 DTO 冻结)
- 不修改 main;不触碰后端领域
- payload 内容语义(ChangeSet 等)留给后端冻结 DTO 后填充

## 已知限制(票内记录)

- 记录创建/事件追加/阶段迁移是三步非跨表事务;单写入者进程下安全,
  跨表原子化留到 RunEngine 硬化票

## 验收

    .venv\Scripts\python.exe -m pytest tests/unit/harness tests/integration/harness tests/integration/storage/test_harness_schema.py -q --basetemp .test-temp/pytest
    .venv\Scripts\python.exe -m ruff check src tests
    .venv\Scripts\python.exe -m mypy src/ai_novel_studio
