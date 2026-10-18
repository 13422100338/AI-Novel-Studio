# Harness 审查修复(F1–F7)检查指导(给检查模型)

> 日期:2026-08-15 · 分支:`agent/ai-agent-v1`(工作树 `<repo>/`)
> 修复基线:审查在 `fd7607b`(B10)上进行;修复提交区间 `4b83832..523c1e6`(F1–F7,共 10 个提交)
> 验证基线(修复后):harness+storage 447 测试通过;仓库全量 1497 通过 + 1 个与
> Harness 无关的 GBK 环境失败(`tests/unit/test_windows_scripts.py`,main 上同样存在);
> ruff 0;mypy strict 0

## 1. 修复内容与对应提交

| 票 | 提交 | 改动文件(要点) |
|---|---|---|
| F1 工具过闸 | `4b83832` | 新增 `harness/tool_executor.py`(`ToolExecutor.execute` 先 GateContext→evaluate 再派发;DENIED/REQUIRES_APPROVAL 只抛错不执行;ALLOWED 补 TOOL_CALL_STARTED/COMPLETED/FAILED 事件);`permission_gateway.py` 删除 GateContext.caller_skill_id 死字段 |
| F2 装包补全 | `01487d0` | `constitution_flow.py` 新增 `to_writer_prompt_component`(只渲染 shared_creative_rules+writer_only_rules);`agent_loop.py` 的 `build_draft_messages` 补知识边界/故事时间/关系边界/不可揭示进任务块,并注入 writer 宪法组件 |
| F3 生成门禁 | `773cb7c` | `agent_loop.py`:`generate_candidate` 在 PACKAGE_READY 后查 `ready_for_draft_model`,未决剧情 → 不发流式、transition INTERRUPTED+failure_code=DRAFT_BLOCKED,抛 `DraftBlockedError`;新增 `unresolved` 参数 |
| F4 模式配对 | `dc69382` | `agent_loop.py`:`generation_profile` 参数 + `validate_generation_pairing`(QUICK↔MINIMAL、NORMAL↔STANDARD,DEEP 拒绝) |
| F5a 合并并发控制 | `7ea33b2`+`c0e40a2` | `subject_tools.py` 提案审批带 `expected_revisions`(源卡状态事件数)与 preview 快照;`approval_resolver.py` 决议前只读复核,失配 → 拒绝、审批保持 PENDING、run 转 STALE+SUBJECT_REVISION_CONFLICT |
| F6 门面对齐 | `fa43975` | `core_tools.py` 宪法工具改走 `ProjectConstitutionService.get_project_constitution`;缺口记录进审查票附录 A |
| F7-1 状态机 | `3725114` | `run_state.py` 新增 `LEGAL_TRANSITIONS`+`validate_transition`;`event_store.py` transition 前校验(INTERRUPTED/STALE 保持开放可恢复) |
| F7-2 压缩禁区 | `b4b979b` | `compaction.py` 增查:工具调用未闭合(TOOL_CALL_STARTED 无配对)、批准后提交在途(APPROVAL_RESOLVED approved 且 run 未关) |
| F7-3 边界扩层 | `2d267ff` | `test_harness_boundaries.py` 扫描层扩到 application/infrastructure |
| F7-4 事件瘦身 | `523c1e6` | `draft_stream.py` DELTA payload 改存 {delta_length, cumulative_chars}(schema_version=2),全文只进 DRAFT_CHECKPOINT 工件 |

## 2. 要参考的 MD

- `docs/handoffs/2026-08-15-harness-audit-fix-tickets.md` — 本批修复的来源(含"已验证符合、勿重复审查"清单、每票允许文件/禁止项/验收、附录 A)
- `docs/handoffs/2026-08-15-harness-verification-guide.md` — 上一轮 Harness 整体检查指导(代码地图与环境坑)
- `docs/harness/agent-harness-design-v0.3.md`(设计权威;本批涉及 §15、§19、§31、§37.1、§41、§41.1、§52、§63、§67)
- `docs/harness/agent-implementation-backend-contract-v0.1.md`(契约;本批涉及 §2、§3、§8.2、§14)
- `docs/harness/tickets/`(B1–B10 原实施票)

## 3. 验证命令(工作树内)

```text
.venv\Scripts\python.exe -m pytest tests/unit/harness tests/integration/harness tests/integration/storage -q --basetemp .test-temp\pytest
.venv\Scripts\python.exe -m ruff check src tests
.venv\Scripts\python.exe -m mypy src/ai_novel_studio
```

新增测试文件:`test_tool_executor.py`、`test_draft_messages.py`、`test_agent_loop_block_gate.py`、
`test_generation_pairing.py`;扩展:`test_approval_resolver.py`、`test_subject_tools.py`、
`test_event_store.py`、`test_compaction.py`、`test_harness_boundaries.py`。

## 4. 检查要点(对照审查票验收逐条)

1. F1:关闭态 run 工具调用被拒;PROPOSAL_ONLY 缺幂等键被拒;FORMAL_WRITE 永不执行
   (伪造定义验证);事件序列含 TOOL_CALL_*;`caller_skill_id` 已无处引用。
2. F2:writer 请求含 writer 层规则且不含 agent_only/overridable/non_overridable;
   同输入两次 build_draft_messages 结果一致;知识边界出现在任务块;冒烟仍绿。
3. F3:unresolved 时全程零模型调用、run 停 INTERRUPTED、failure 字段原因可读。
4. F4:配对校验拒绝 QUICK+STANDARD、NORMAL+MINIMAL、任意+DEEP。
5. F5a:revision 失配 → 拒绝提交、审批 PENDING、run STALE;匹配 → 正常提交。
6. F6:core_tools 的宪法路径走门面;附录 A 三项缺口(manuscript/memory/subject
   查询门面不存在)已记录,未新建后端门面。
7. F7:非法迁移边抛错且关态语义不变;压缩在工具未闭合/提交在途时被拒;边界扫描
   覆盖四层仍零违规;DELTA 事件不含正文全文(检查 payload 与 schema_version=2)。

## 5. 边界声明

只检查 F1–F7 修复是否符合审查票。后端侧事项(F5b 事务内校验、F2 字段暴露、
F6 三项门面、Provider 主动取消)在审查票附录 A,本批明确不做——若检查发现
"必须改后端才能满足某条验收",请记录问题,不要直接改后端。
