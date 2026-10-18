# H0 步骤 4.1:audit_claims 公共门面(适配)

- 日期:2026-08-14
- 依据:H0"reuse or adapt the existing Audit authority";契约 §A.2 audit_claims;
- 分支:ds/r3b-q1 续用

## 目标

给既有确定性审校路径一个统一有界入口:AuditClaimsRequest(目标类型/文本/
修订/mode/policy/要求文本)-> AuditWorkflowService -> AuditWorkflowResult
(复用,含持久化 AuditFinding[])。不重写工作流,不造近义 DTO。

## 允许文件

- 新增 src/ai_novel_studio/application/audit_claim_service.py
- 新增 tests/integration/application/test_audit_claim_service.py
- 新增 docs/handoffs/2026-08-14-h0-step4-audit-claims-ticket.md

## 禁止事项

- 无 schema 修改;不改 AuditWorkflowService/DeterministicAuditService/仓储
- 不做 claim-vs-evidence 新语义(需另行设计决策)
- 不改 harness 分支/main/看板

## 验收

- 新测试全绿 + 既有审校测试全绿;ruff;mypy;diff --check

## 回滚

- 删除新文件即可
