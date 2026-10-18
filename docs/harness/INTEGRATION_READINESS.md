# Harness 分支集成就绪审计(agent/ai-agent-v1)

- 日期:2026-08-14
- 范围:main(e6a9873)..HEAD 全量审计
- 用途:作者方案 A 集成决策(先合并 Harness v21/v22 再开后端新迁移)的证据页

## 1. 差异范围

- 变更文件 64 个:53 个新增 + 11 个对 main 既有文件的修改。
- 11 个既有文件修改全部可解释:
  - src/ai_novel_studio/infrastructure/storage/schema_migrations.py:仅注册 v21/v22;
  - tests/integration/storage/ 下 9 个 schema 测试:LATEST_SCHEMA_VERSION 断言
    机械升级(20->21->22)与 occurrence future probe 21->22->23;
  - tests/test_package_layout.py:planned boundaries 增加 harness 包(1 行)。
- 无任何 backend domain/core/application/ui 业务代码改动;无 manuscript/
  SQLite 数据/备份/导出文件进入 diff。

## 2. 合并门禁验证结果

| 门禁 | 结果 |
| --- | --- |
| 全量 pytest(tests 全部) | 1264 passed(109s,含 A10a/A9b 后复测) |
| ruff check src tests | 0 issues(213 files) |
| mypy src/ai_novel_studio(strict) | 0 issues |
| git diff --check main...HEAD | clean |
| 敏感模式扫描(api_key / 路径 / 用户目录 / models.json) | 0 命中(仅设计文档的政策性文字) |
| Backend -> Harness 反向依赖 | 无,由 test_harness_boundaries 锁定 |

## 3. Schema 声明

- v21:harness_runs / harness_run_events(纯追加);
- v22:harness_approvals(纯追加);
- 均为 Harness 所有表,无数据迁移、无既有表结构变更。
- 按方案 A:本分支合并后,后端新迁移从 v23 起由主控分配。

## 4. 集成动作建议(作者/主控执行)

    1. git fetch 后按看板 Master Review Commands 复核 main...agent/ai-agent-v1;
    2. 合并 agent/ai-agent-v1 到 main(或按主控现有流程集成);
    3. 通知后端:R3b-Q1 可继续,新 schema 从 v23 起;
    4. 通知 Harness 侧:R3b-Q1 冻结后接 A5 context.compile 接线。
