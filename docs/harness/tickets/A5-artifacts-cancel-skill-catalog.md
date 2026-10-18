# HARNESS-V1-A5:ArtifactStore + CancelToken + SkillCatalog 骨架

- 日期:2026-08-14
- 设计来源:v0.3 §20、§32-§33、§54、§67;契约 §12"可立即独立实现"剩余项
  (ArtifactStore、Cancel Token、Skill Catalog 骨架)与 §A.3 并行清单
- 分支:agent/ai-agent-v1;基线:A4 提交 c983208
- 注:附录 D 的 A5(Context Compiler Facade)依赖后端 DTO 冻结,按契约 §12
  移到后续;本票编号 A5 承接"可立即独立实现"的剩余基础设施

## 目标

- ArtifactStore:内容寻址(sha256)存储,首次写入去重;工具结果/候选稿存
  大对象,模型上下文只带摘录 + artifact_id(设计 §20)
- FileArtifactBackend:<root>/artifacts/<hash>.bin + .json 侧车;后端协议可替换
- CancelToken:单向线程安全取消标志;CancellationError 供协作检查点抛出;
  cancel_run = token.request + run 转入 CANCELLED(设计 §54,与 EventStore
  终态拒绝和 PermissionGateway DENIED 联动,已测试)
- SkillCatalog:轻量条目目录 + 按需加载完整 Skill;Skill 只含方法/检查项/
  输出结构/推荐工具,不含任何权限(设计 §33)

## 允许文件

- 新增 src/ai_novel_studio/harness/artifacts.py / cancel_token.py / skill_catalog.py
- 新增 tests/unit/harness/test_artifacts.py / test_cancel_token.py / test_skill_catalog.py
- 新增 docs/harness/tickets/A5-artifacts-cancel-skill-catalog.md

## 禁止事项

- 不新增 schema / 迁移 / 表;不定义 Artifact 保留清理策略(设计 §67 的 30 天
  保留执行留给后续运维票)
- 不实现 SkillChangeProposal / Skill 权限(DCP 与审批属 V1.1)
- 不修改 main;不触碰后端领域

## 验收

    .venv\Scripts\python.exe -m pytest tests/unit/harness -q --basetemp .test-temp/pytest
    .venv\Scripts\python.exe -m ruff check src tests
    .venv\Scripts\python.exe -m mypy src/ai_novel_studio
