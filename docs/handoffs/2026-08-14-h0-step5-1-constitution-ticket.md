# H0 步骤 5.1:ProjectConstitution 版本化宪法(方案 A,schema v23)

- 日期:2026-08-14
- 依据:设计 v0.3 §37.1;契约 §9;H0 步骤 5 DCP D-1/D-2(用户批准推荐项)
- 分支:ds/r3b-q1(已本地合并 harness v21/v22,按方案 A;集成时先合 harness
-  分支到 main,再合本分支,相同 SHA 无冲突)
- Schema:v23 由本票占用(方案 A:harness v21/v22 先合并,后端新迁移 v23 起)

## 目标

- domain:ConstitutionRule / ProjectConstitution(不可变修订,五层规则 +
-  来源决定 + 未决排除 + 作者批准标记)/ ProjectConstitutionProposal
- 仓储:project_constitutions 表(schema v23,UNIQUE(project_id, revision),
-  历史版本全保留);save 以 expected_revision 做并发控制(BEGIN IMMEDIATE +
-  最高修订比对,失配抛 StaleConstitutionRevisionError)
- 门面:get_project_constitution / build_proposal(校验 + 五层 Diff 预览)/
-  commit(必须 approved_by_author + expected_revision)
- 保留现有 ProjectGuidance 职责(剧情商讨只读提示),最终合并迁移留后续票

## 允许文件

- 新增 src/ai_novel_studio/infrastructure/storage/schema_migrations_v23.py
- 修改 schema_migrations.py(注册 v23)
- 新增 domain/project_constitution.py
- 新增 infrastructure/storage/project_constitution_repository.py
- 新增 application/project_constitution_service.py
- 新增三个测试文件;机械升级 10 个 schema 断言 22->23 与 occurrence probe 23->24
- 新增 docs/handoffs/2026-08-14-h0-step5-1-constitution-ticket.md

## 禁止事项

- 不改 ProjectGuidance 及其 UI 写入路径;不改 harness 分支/main/看板
- 最高提示词不得改变程序权限(commit 不触任何权限面)

## 验收

- 新测试全绿 + 全量回归;ruff;mypy;diff --check

## 回滚

- 删除 v23 迁移与新文件,断言改回 22
