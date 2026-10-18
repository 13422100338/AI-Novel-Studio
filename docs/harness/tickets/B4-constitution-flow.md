# HARNESS-V1-B4:A11 Agent 侧宪法提案流

- 日期:2026-08-14
- 设计来源:v0.3 §37.1、§38;契约 §9
- 分支:agent/ai-agent-v1(已快进至合并后的 main @ 3f1b9d8)
- 依赖:后端 ProjectConstitutionService(已合入 main)

## 目标

ConstitutionFlowService:propose(经 A8a 审批,kind=PROJECT_CONSTITUTION,
payload 存提案 JSON)-> resolve(批准才调后端 commit,expected_revision=
base_revision 并发控制;拒绝零写入)-> to_prompt_component(已提交修订渲染
为 PROJECT_CONSTITUTION / PROJECT 稳定性组件,进 PromptCompiler 项目前缀)。

## 允许文件

- 新增 src/ai_novel_studio/harness/constitution_flow.py
- 新增 tests/integration/harness/test_constitution_flow.py
- 新增 docs/harness/tickets/B4-constitution-flow.md

## 禁止事项

- 无 schema 变更;不改后端服务;不绕过审批直接 commit
- 不改 main

## 已知限制

- 批准决议后 commit 若因并发失败(Stale),审批记录已为 APPROVED——由
  Harness 以新提案重试;审批与提交的跨系统原子性留 RunEngine 硬化票

## 验收

- 新测试全绿 + harness 全量;ruff;mypy;diff --check
