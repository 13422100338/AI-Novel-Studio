# HARNESS-V1-B9:核心工具 9 个(薄门面 + 手写确定性校验)

- 日期:2026-08-15
- 设计来源:v0.3 §22、§29-§30、§45;handoff 2026-08-14 §4(B9,作者指示最后做)
- 分支:agent/ai-agent-v1(ds-agent 工作树)
- 决策:经 GitHub 调研(见会话),9 工具无现成开源实现可"拿来";采用
  薄门面 + 手写确定性校验(与 B1-B10 风格一致、零新依赖),不 vendor
  fastjsonschema(备选保留)

## 目标

9 个常驻工具:context.compile / manuscript.read / manuscript.get_selection /
subject.query / plan.query / memory.query / project_constitution.read /
artifact.read / tool.search——

1. 全部 ToolDefinition:PROJECT 域、READ_ONLY、NONE、免审批(§29);
2. CoreToolService.execute(tool_id, arguments, run_id):run 事实从事件库
   读取(active_chapter_id 作 manuscript/memory 默认边界,§45 无选区即整章);
   - context.compile:CompileContextService.build(预算构造时冻结,模型
     不可控;run_id 由执行器注入);输出 manifest_id/预算占比/证据命中+
     编译文本;
   - manuscript.read / get_selection:ChapterRepository,字符级确定性切片,
     get_selection 无偏移即整章、缺 chapter_id 回退 run 活动章;
   - subject.query:resolve_character_name 精确(正名/别名)+ 子串兜底,
     渲染 subject_id 供 B5 四件套使用;
   - plan.query:PlanQueryService 只读聚合,渲染时显式标注
     AUTHOR_PLAN(计划≠正典);
   - memory.query:SearchRepository.search_rows,before_chapter_id 为显式
     参数或 run 活动章,缺失即拒绝(§23 未来信息硬过滤);
   - project_constitution.read:ProjectConstitutionRepository.current(),
     无则明示;
   - artifact.read:ArtifactStore 按内容地址读取,节选 + 元数据;
   - tool.search:ToolRegistry 快照按 id 子串匹配,空查询拒绝;
3. 手写参数校验(_required_id/_int_arg 确定性钳制/证据需求结构化),
   模型输出不可信,一切经构造校验后才触达后端。

## 允许文件

- 新增 src/ai_novel_studio/harness/core_tools.py
- 新增 tests/integration/harness/test_core_tools.py
- 新增 docs/harness/tickets/B9-core-tools.md

## 禁止事项

- 无 schema 变更;不改后端 Facade/检索语义;不新增依赖;
- 工具不得绕 Context Compiler 拼正式生成上下文(§22:memory.query 等
  直接查询只用于回答/诊断,进入生成包必经 context.compile);
- 不合并 main

## 已知限制

- FTS5 unicode61 不切分中文:检索词需完整中文 token(已知坑,透传原样)
- 执行器不查 run 关闭态(由 A3 网关先行裁决,与 B5 一致)
- 编辑器选区状态由前端提供(工具接受显式偏移)

## 验收

    .venv\Scripts\python.exe -m pytest tests/integration/harness/test_core_tools.py tests/unit/harness tests/integration/harness -q --basetemp .test-temp/pytest
    .venv\Scripts\python.exe -m ruff check src tests
    .venv\Scripts\python.exe -m mypy src/ai_novel_studio
