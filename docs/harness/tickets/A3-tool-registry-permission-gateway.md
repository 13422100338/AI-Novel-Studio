# HARNESS-V1-A3:Core Tool Registry + Permission Gateway(骨架)

- 日期:2026-08-14
- 设计来源:v0.3 §28-§31;契约 §12"可立即独立实现"第 3 项
  (Tool/Skill Catalog 骨架、PermissionGateway 骨架)
- 分支:agent/ai-agent-v1;基线:A2 提交 43fde96

## 目标

- ToolDefinition:按设计 §29 元数据冻结单工具版本(id/version/scope/
  risk_level/write_effect/requires_approval/input_schema/output_schema)
- ToolRegistry:版本化目录;同 id 同版本拒绝重复注册;resolve 取最高版本;
  snapshot 按 (id, version) 确定性排序
- PermissionGateway:按设计 §31 做确定性预执行检查,输出
  ALLOWED / REQUIRES_APPROVAL / DENIED 决策;Prompt 与 Skill 无法绕过

## 决策规则(本票冻结)

1. 工具未注册 -> DENIED
2. run 处于终态(COMPLETED/CANCELLED/FAILED)-> DENIED(设计 §54)
3. PROJECT 工具在 project_scope_enabled=False 时 -> DENIED;RUN 工具同理
4. FORMAL_WRITE:缺 expected_revision 或缺 idempotency_key -> DENIED;
   齐全 -> 强制 REQUIRES_APPROVAL(即使定义 requires_approval=False)
5. PROPOSAL_ONLY:缺 idempotency_key -> DENIED;否则按 requires_approval
6. NONE:按 requires_approval;默认 ALLOWED

## 允许文件

- 新增 src/ai_novel_studio/harness/tool_registry.py
- 新增 src/ai_novel_studio/harness/permission_gateway.py
- 新增 tests/unit/harness/test_tool_registry.py
- 新增 tests/unit/harness/test_permission_gateway.py
- 新增 docs/harness/tickets/A3-tool-registry-permission-gateway.md

## 禁止事项

- 不实现工具执行/provider 接线(后续票据)
- 不实现审批持久化与审批解决器(A8)
- 不新增 schema / 迁移 / 表
- 不修改 main;不触碰后端领域

## 验收

    .venv\Scripts\python.exe -m pytest tests/unit/harness -q --basetemp .test-temp/pytest
    .venv\Scripts\python.exe -m ruff check src tests
    .venv\Scripts\python.exe -m mypy src/ai_novel_studio
