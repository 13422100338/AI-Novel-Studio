# HARNESS-V1-A12:EditorSnapshot + GenerationPackage 冻结 + RunEngine 骨架

- 日期:2026-08-14
- 设计来源:v0.3 §41、§46-§47;契约 §4;用户指示:核心工具暂缓
- 分支:agent/ai-agent-v1(ds-agent 工作树)

## 目标

1. EditorSnapshot 冻结 + 确定性分类(CURRENT / STALE_BUT_REBASABLE /
   STALE_CONFLICTED)+ 三方合并判定(CLEAN_APPLY / NO_CHANGE / NEEDS_REVIEW)
2. GenerationPackage:设计 §41 全字段,复用后端 GenerationProfile/AuditPolicy;
   ready_for_draft_model / draft_blocked_reasons(未决剧情阻断正文模型)
3. HarnessRunEngine 骨架:队列门禁启动、阶段迁移、取消(单向令牌)、
   审批请求/解决、完成校验、投影;compile 步骤端口化注入(真 Facade
   适配器等后端分支合并后接线);工具执行与正文流不在本票

## 允许文件

- 新增 harness/generation_package.py / run_engine.py
- 新增 tests/unit/harness/test_generation_package.py
- 新增 tests/integration/harness/test_run_engine.py
- 新增 docs/harness/tickets/A12-editor-snapshot-package-run-engine.md

## 禁止事项

- 无 schema 变更;不导入未合并的后端 Facade(端口化)
- 不改 main/后端分支

## 已知限制

- 进程内取消令牌注册表:重启后令牌需重建(恢复中心接续,记录在票)
- Run-frozen 模型角色绑定持久化留后续

## 验收

    .venv\Scripts\python.exe -m pytest tests/unit/harness tests/integration/harness -q --basetemp .test-temp/pytest
    .venv\Scripts\python.exe -m ruff check src tests
    .venv\Scripts\python.exe -m mypy src/ai_novel_studio
