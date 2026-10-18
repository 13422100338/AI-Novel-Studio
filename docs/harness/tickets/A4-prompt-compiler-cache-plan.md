# HARNESS-V1-A4:PromptCompiler + CachePlan + ModelRequestManifest

- 日期:2026-08-14
- 设计来源:v0.3 §15、§15.1、§15.2、附录 E.1;契约 §5.2
- 分支:agent/ai-agent-v1;基线:A3 提交 62e1f8a

## 目标

- PromptComponent:不可变提示词片段(id/kind/role/stability/revision/content/
  ordering_priority/cache_eligible/sensitive/content_hash),hash = sha256(content)
- PromptCompiler:确定性物理请求装配——按(稳定性层级, ordering_priority, id)
  排序,CURRENT_INPUT 强制最后;稳定前缀哈希只覆盖 cache_eligible 的
  GLOBAL/PROJECT/RUN 内容;输入组件集合顺序无关(同一集合 -> 同一字节序列)
- CachePlan:provider + 三级前缀哈希 + breakpoints + cache_key + retention
- ModelRequestManifest:设计 §15.2 全部字段,本地复现"模型当时看到了什么"

## 结构护栏

- STATE_CAPSULE / TOOL_RESULTS / CONTEXT_PROJECTION / CONVERSATION_SUMMARY /
  RECENT_CONVERSATION / CURRENT_INPUT 六类强制 TURN 层级,结构上无法进入稳定前缀
- 组件角色限定 system/user/assistant(仓库 LLMMessage 词汇);developer 角色映射
  属 provider 层职责,不在本票
- 哈希字段必须 64 位小写 hex;内容相同必须同 hash(附录 E.1)

## 允许文件

- 新增 src/ai_novel_studio/harness/prompt_compiler.py
- 新增 tests/unit/harness/test_prompt_compiler.py
- 新增 docs/harness/tickets/A4-prompt-compiler-cache-plan.md

## 禁止事项

- 不新增 schema / 迁移 / 表(Manifest 持久化留给 A5/A6 与 Artifact Store 一起)
- 不接触 Context Compiler / 领域检索 / CANON 判断(契约 §5.2)
- 不修改基础设施 LLM 层;不修改 main

## 策略

- cache_key 默认 = run_prefix_hash(provider 通用确定性默认)
- cache_eligible=False 的组件不进入前缀哈希,但仍进入 messages
- 显式缓存统计回填 UsageProjection 属 A5+;本票只定义 CacheStatus

## 验收

    .venv\Scripts\python.exe -m pytest tests/unit/harness -q --basetemp .test-temp/pytest
    .venv\Scripts\python.exe -m ruff check src tests
    .venv\Scripts\python.exe -m mypy src/ai_novel_studio
