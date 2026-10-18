# H0 步骤 5.5:只读 plan.query 聚合(方案 A,V1 最小)

- 日期:2026-08-14
- 依据:H0 步骤 5 DCP D-9(用户批准推荐项 A);设计 PLAN != CANON
- 分支:ds/r3b-q1

## 目标

只读聚合现有计划来源:当前章要求(ChapterRequirement 快照:内容/锁定/
修订/哈希)+ 项目指引(ProjectGuidance 文本与修订)。PlanResult 显式携带
domain_kind="AUTHOR_PLAN" 标记,PLAN 与 CANON 分离由 Context 硬过滤保证。
完整 Plan 领域与 PlanCandidate 生命周期留 V1.1。

## 允许文件

- 新增 src/ai_novel_studio/application/plan_query_service.py
- 新增 tests/integration/application/test_plan_query_service.py
- 新增 docs/handoffs/2026-08-14-h0-step5-5-plan-query-ticket.md

## 禁止事项

- 无 schema 修改;不改既有仓储
- 不做写操作;不新建 Plan 领域
- 不改 harness 分支/main/看板

## 验收

- 新测试全绿;ruff;mypy;diff --check

## 回滚

- 删除新文件即可
