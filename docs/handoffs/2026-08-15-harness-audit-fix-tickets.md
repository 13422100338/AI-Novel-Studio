# Harness 审查修复票(给实施模型)

> 日期:2026-08-15 · 来源:对 `agent/ai-agent-v1` @ `fd7607b`(B10)的只读合规审查
> 工作树:`<repo>/`(分支 agent/ai-agent-v1)
> 验证基线(已复核,与事实一致):harness 194 + storage 228 = 422 测试通过;ruff 0;mypy 247 文件 0
> 设计依据:`docs/harness/agent-harness-design-v0.3.md`(下称"设计§"),
> `docs/harness/agent-implementation-backend-contract-v0.1.md`(下称"契约§")

## 0. 已验证符合、请勿重复审查或改动的部分

- 三条红线:无第二套领域存储(harness 仅 runs/events/approvals/manifests 四张编排表);
  backend domain/core/application/infrastructure 对 harness 的 import 为 0;harness 不 import ui。
- 无旧 Pipeline 双编排(GenerationPipeline/AuditPipeline/RepairPipeline 类已不存在)。
- 状态机 13 态、关闭态拒绝迟到事件、event_id 幂等、取消单向不复活、重启恢复
  (含 WAITING_APPROVAL 审批卡恢复数据)、失败分类、完成校验、并发闸门、保留策略、
  压缩禁区、PromptCompiler 稳定性分层与 `_TURN_ONLY_KINDS` 封禁、ModelRequestManifest
  落库(v24)、九个核心工具清单与元数据、Subject 四工具只读/提案、宪法提案流。
- 端到端冒烟 `tests/integration/harness/test_end_to_end_smoke.py` 含重启恢复断言,通过。

## 通用规则(每票都适用)

- 最小正确改动;不改后端 Facade/检索语义;不动前端;不合并 main。
- 无 schema 变更(当前最新 v24;本批票均不需要新表)。
- 每票完成后跑窄测试 + 全量 harness 测试,命令见文末。
- 环境坑:测试必须带 `--basetemp .test-temp/pytest`;不要用 PowerShell
  Get-Content/Set-Content 读写 UTF-8 源码;FTS5 检索测试用完整中文 token。
- 发现"必须改后端才能完成"的地方:记录进本文件附录 A,不要直接改后端
  (验证指南 §6 边界声明)。

---

## F1 · PermissionGateway 接入工具执行路径(设计§31,契约§3/§14)

**问题**:`PermissionGateway.evaluate` 在 src 内没有任何生产调用方,
`CoreToolService.execute` / `SubjectToolService.execute` 执行前不过闸;
`GateContext.caller_skill_id` 定义了但从未被检查。当前 13 个工具全部只读/提案型,
风险低,但接工具循环前必须补上,否则"Prompt/Skill 不能绕过权限"没有运行期保证。

**证据**:harness/permission_gateway.py:55-112;core_tools.py:345-366(execute 无闸);
GateContext 仅出现在 tests/。

**目标**:新增(或接线)一个带闸执行器,例如 `harness/tool_executor.py`:

1. 每次执行前构造 GateContext(run_stage 从事件库读、idempotency_key 由调用方给),
   先 `evaluate`,DENIED 即拒绝并记录事件;REQUIRES_APPROVAL 走 ApprovalService
   建审批,不执行;ALLOWED 才委托 `CoreToolService`/`SubjectToolService.execute`。
2. 执行过程补发 `TOOL_CALL_STARTED` / `TOOL_CALL_COMPLETED` / `TOOL_CALL_FAILED`
   事件(设计§63 词汇已有,目前无人发)。
3. `caller_skill_id` 要么参与裁决(来源 Skill 白名单),要么从 GateContext 删除,
   二选一,不留死字段。

**允许文件**:harness/permission_gateway.py、core_tools.py、subject_tools.py、
新增 harness/tool_executor.py、run_engine.py(仅接线)、
tests/unit/harness/test_permission_gateway.py、
tests/integration/harness/test_core_tools.py、test_subject_tools.py、
新增 tests/integration/harness/test_tool_executor.py。

**禁止**:不改后端;不放松现有网关规则;工具保持只读/提案;不加新表。

**验收**:新测试证明——关闭态 Run 的工具调用被拒;PROPOSAL_ONLY 缺幂等键被拒;
FORMAL_WRITE 永远只到审批;事件序列含 TOOL_CALL_*;既有 194 测试全绿。

---

## F2 · 正文模型请求装包补全(设计§15/§37.1/§41,契约§7/§9)

**问题**:`build_draft_messages` 只拼 GLOBAL 系统语 + RUN 任务块 + TURN 投影 +
CURRENT_INPUT。缺:① ProjectConstitution 的 writer 专用投影;② 知识边界
(known/unaware/unknown)、人物状态、故事时间、叙事边界等 §41 硬约束进任务块
(GenerationPackage 有字段但没人消费);③ StyleProjection/文风样本完全没进请求。
另外 `constitution_flow._render_constitution` 把 5 层规则全量渲染,若直接喂正文模型
会违反 §37.1「正文模型只接收 shared_creative_rules + writer_only_rules」。

**证据**:agent_loop.py:54-120、242-263;constitution_flow.py:175-193。

**目标**:

1. 新增 writer 专用宪法投影函数(如 `to_writer_prompt_component`):
   只渲染 shared_creative_rules + writer_only_rules,PROJECT 稳定级,
   ordering_priority 200;`to_prompt_component`(全 5 层)保留给 Main Agent。
2. `_package` 从后端 `CompiledContext` 实际暴露的数据填充 package 字段
   (pov/story_time/knowledge_* 等);**后端没暴露的字段不准编造,记入附录 A**。
3. `build_draft_messages` 补上:writer 宪法组件(PROJECT)+ 任务块中的
   知识边界/禁止事项/故事时间等硬约束(RUN);文风样本若接线,按 §15.4
   属动态内容,只能 TURN 稳定级,不得进稳定前缀。
4. 保持 §15.1:CURRENT_INPUT 永远最后;同一 Revision 前缀 hash 可复现。

**允许文件**:agent_loop.py、constitution_flow.py、generation_package.py(仅在
必须时)、tests/unit/harness/(新增 test_agent_loop 或并入现有)、
tests/integration/harness/test_end_to_end_smoke.py(仅断言更新)。

**禁止**:不改后端;不把胶囊/摘要/工具结果放进稳定前缀;不建第二套文风存储。

**验收**:单测证明——writer 请求含 writer 规则且不含 agent_only/overridable/
non_overridable 层;同 Revision 前缀 hash 一致;知识边界出现在任务块;冒烟仍绿。

---

## F3 · 生成前阻断门禁接线(设计§41)

**问题**:`GenerationPackage.draft_blocked_reasons` / `ready_for_draft_model` 存在
且有单测,但 `ChapterGenerationLoop.generate_candidate` 流式生成前从不检查,
「没想好/重大缺失禁止调用正文模型」没有执行。

**证据**:generation_package.py:150-162;agent_loop.py:196-231。

**目标**:`generate_candidate` 在 PACKAGE_READY 之后、MODEL_RUNNING 之前检查
`package.ready_for_draft_model`;被阻断时不发起流式调用,把原因写进事件/运行
失败字段(可 transition 到 INTERRUPTED 并带 failure_code="DRAFT_BLOCKED",
failure_message 为合并原因),由恢复中心向作者展示。

**允许文件**:agent_loop.py、tests/unit/harness/、tests/integration/harness/。

**禁止**:不自动补全未决剧情;不为绕过门禁而放宽 `draft_blocked_reasons`;
不新增事件类型词汇(除非确有必要,且需在票内说明)。

**验收**:新测试——package 带 unresolved 时全程无模型调用、运行停在非 MODEL_RUNNING
态、原因可查;既有测试全绿。

---

## F4 · GenerationProfile 可按 §41.1 选择

**问题**:`_package` 硬编码 `GenerationProfile.QUICK`(agent_loop.py:259),
普通模式(NORMAL+STANDARD)走不到。

**目标**:`ChapterGenerationLoop.__init__`/`for_project` 增加 `generation_profile`
参数(默认 QUICK,与 audit_policy 同样注入);按 §41.1 校验配对:
QUICK↔MINIMAL、NORMAL↔STANDARD,不配即拒绝;AuditPolicy.DEEP 仍是审校动作,
不得变成第三种生成模式。

**允许文件**:agent_loop.py、tests/unit/harness/。

**验收**:配对校验单测;NORMAL+STANDARD 能构造出正确 package;既有测试全绿。

---

## F5 · Subject 合并提交补 Revision 并发控制(契约§8.2/§14)

**问题**:审批记录存了 `expected_revisions`,但合并提交路径从不校验;
后端 `SubjectMergeService.merge(source, target, *, reason, confirmed_by_user)`
签名没有期望修订参数(已核实)。契约要求"Revision 冲突拒绝提交"。

**证据**:approval_resolver.py:175-182;subject_tools.py:232-262;
backend application/subject_merge_service.py merge 签名。

**目标(分两半)**:

- **F5a(Harness 侧,本票可做)**:`subject.propose_merge` 的审批 payload 增加
  expected_revisions(源/目标卡当前 revision,取自 preview/inspect 结果)与
  MergePreview 摘要快照;`ApprovalResolver.resolve_and_commit` 派发前用只读查询
  比对当前 revision,不一致则拒绝提交、把 Run 标记 STALE 并给出冲突说明。
- **F5b(后端侧,本票不做)**:后端 commit 接口加 expected_revisions 做事务内
  校验。记入附录 A,等作者/后端负责人立项。

**允许文件**:subject_tools.py、approval_resolver.py、tests/integration/harness/
test_subject_tools.py、tests/unit/harness/test_approval_resolver.py。

**禁止**:不改后端;不静默合并;拒绝提交时不得留下半截审批状态
(审批保持 PENDING 或按既有生命周期显式处理)。

**验收**:revision 失配时提交被拒且原因可读;匹配时正常提交;既有测试全绿。

---

## F6 · 核心工具直注 Repository 的对齐(契约§3 字面)

**问题**:`CoreToolService` 直注 ChapterRepository / SubjectRepository /
SearchRepository / ProjectConstitutionRepository(core_tools.py:299-343)。
契约§3 字面禁止「Tool → 直接访问 Repository」,要求走稳定 Facade 返 DTO。
实际全部只读、同进程、无 SQL 拼接,风险低。

**目标(二选一,默认 A)**:

- **A**:改注 H0 已冻结的应用门面——subject.query 用 query_subject_evidence、
  plan.query 已用 PlanQueryService(保持)、constitution 用 get_project_constitution、
  context.compile 已用 CompileContextService(保持);manuscript.read /
  get_selection / memory.query 没有现成门面,**不准新建后端门面**,记入附录 A。
- **B**:若作者认可,在契约/设计文档登记「同进程只读仓储直注」为明示豁免项,
  本票即关闭。

**验收**:工具测试保持全绿;选 A 时 harness 对 infrastructure.storage 的直 import
收敛到 ProjectRepository/Artifact 路径等最小集。

---

## F7 · 小项打包(一票一项 commit,可拆分领取)

1. **状态机转移边校验**(设计§52):为 open 态之间定义合法迁移表
   (CREATED→TASK_ANALYZED→… 顺序 + 异常态),非法迁移抛错;
   注意 INTERRUPTED/STALE 必须保持开放供恢复(§55),CLOSED_STAGES 语义不变。
   位置:run_state.py / event_store.py。
2. **压缩禁区补两条**(设计§19):CompactionGate 增查「工具调用未闭合」
   (replay 中存在无配对 COMPLETED/FAILED 的 TOOL_CALL_STARTED)与
   「事务提交中」。位置:compaction.py + 测试。
3. **边界测试扩层**:test_harness_boundaries.py 目前只扫 domain/core,
   把 application、infrastructure 纳入同一断言。
4. **CHAPTER_STREAM_DELTA 全文出事件表**(设计§67):delta 事件 payload 改存
   长度/累计字符数/检查点 artifact 引用,全文只进 DRAFT_CHECKPOINT 工件
   (保留策略已有);同步更新投影与冒烟测试的 delta 断言。注意这是事件 payload
   结构变更,schema_version 语义要在票内写明(事件表不变,仅 payload 约定变)。
5. **记录已知限制(不改代码)**:Provider 取消目前为协作式 token 轮询,
   不主动断 HTTP(§54-b 半满足),写入附录 A,接真实 Provider 时再处理。

---

## 附录 A · 需后端/作者协调的事项(本批票不做,只记录)

1. F5b:SubjectMergeService.commit 增加 expected_revisions 事务内并发校验。
2. F2:CompiledContext/ContextManifest 未暴露、§41 要求进 GenerationPackage 的
   字段:pov、story_time、narrative_sequence_boundary、knowledge_known/
   unaware/unknown、character_states、relationship_boundaries、
   non_revealable_constraints、StyleProjection 文风样本。当前 generate_candidate
   仅能由调用方经参数提供 unresolved,其余字段保持空,F2 只保证"字段一旦有值
   即进任务块/请求,绝不编造"。
3. F6-A:manuscript.read / manuscript.get_selection(无正文读取门面)、
   memory.query(无记忆检索门面)、subject.query(无主体注册表查询门面;
   核实后 query_subject_evidence 门面并不存在,FormalEvidenceQueryService
   是证据文本检索,语义不符;inspect_subjects 只接受 subject_id)仍直注
   只读 Repository,等后端立项提供门面。
4. F7-5:Provider 级主动取消能力。

## 通用验收命令(工作树内)

```text
.venv\Scripts\python.exe -m pytest tests/unit/harness tests/integration/harness -q --basetemp .test-temp\pytest
.venv\Scripts\python.exe -m pytest tests/integration/storage -q --basetemp .test-temp\pytest
.venv\Scripts\python.exe -m ruff check src tests
.venv\Scripts\python.exe -m mypy src/ai_novel_studio
```

完成标准:每票独立 commit 到 agent/ai-agent-v1;全部票完成后 harness+storage
422+新增测试全绿,ruff/mypy 0;不合并 main(集成由作者指示)。
