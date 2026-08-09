# Backend Worktree Master Board

## Control Plane

- Master controller: current pinned Codex task.
- Master task ID: `019f87b5-ce06-7f82-bb24-871f43b98f32`.
- Integration policy: `main`-only integration. Worker tasks never merge or push `main`.
- Superpowers: disabled for this project workflow.
- Initial business-code baseline: `e35b50d` (the backend code state before the governance-only dispatch commit).
- Wave 1 dispatched baseline: `3382dd36c2a4aeb4acdab411e9211885b633e678`.
- Latest integrated business commit: `1feaf58` (R2b-C production content-revision caller routing through RevisionImpact maintenance, including prior R1a-R2a-F, S1, P0-1, A1-A4, B1-B14, C1-C14, M1, E1a, E1b-SR1, E1b-SS1, E1b-CR1, E1b-CS1, E1b-CE1, E1b-SM1, SE1-SE3, and ST1 increments).
- Planning sources:
  - `docs/handoffs/2026-07-22-backend-refactor-handoff.md`
  - `docs/handoffs/2026-08-09-backend-refactor-supplemental-upgrade.md`
  - `docs/architecture/0022-formal-manuscript-evidence-index.md`
  - `C:\Users\钟子诚\Downloads\AI_Novel_Studio_后端改进方案_Subject_View_Time_Context_Compiler_修订版.md`

## Worktree Startup Rules

- The user makes the final decision to start, resume, or advance lanes A, B, and C, including each new increment. The master may recommend sequencing and prepare read-only tickets, but must not authorize implementation without explicit user approval.
- Debugging and bug fixes inside an already authorized active increment may proceed without a new lane-start decision, provided they stay within the approved scope.
- The active master or worker may autonomously select, upgrade, or downgrade its model/reasoning effort when the current Codex surface supports it. This requires no separate user approval, but the `READY_FOR_REVIEW` report must record the final model/effort and any escalation reason. Model switching must never authorize a new lane, expand a ticket, or bypass a `DECISION_REQUIRED` product/architecture choice.
- Route using **accepted-commit cost**, not nominal token price alone. Measure comparable tickets by first-pass narrow-test success, correction rounds, elapsed time, credits, and post-merge regressions. Review the route after ten comparable tickets; never promote a model based on a single anecdote.
- `gpt-5.6-luna / max` is the default **executor** for a frozen, narrow ticket: bounded read-only investigation, fixtures/tests, local UI changes, or implementation whose target files, non-goals, and acceptance commands are already explicit. Luna must not be the sole owner of an unresolved semantic decision, a public/persisted contract, or final integration/review. Do not force Max for a no-code status report or simple mechanical output merely because it uses Luna.
- `gpt-5.6-terra / high` is an opt-in pilot only for routine multi-file work with an existing pattern and a fully specified contract. Run it against the same kind of B/C tickets as Luna and retain it only when its accepted-commit cost is demonstrably better. Do not use Terra for high-risk or cross-cutting work by default.
- `gpt-5.6-sol / high` owns ticket decomposition, architecture and semantic decisions, cross-module implementation, difficult debugging, final differential review, and main integration. Escalate to `gpt-5.6-sol / xhigh` only for schema/migrations, security or untrusted external-input boundaries, concurrency/atomicity, public persisted contracts, Context/Manifest identity, or other mistakes that are expensive to reverse. Do not use `max` or `ultra` by default.
- Upgrade from Luna/Terra to Sol when a frozen ticket reveals an unresolved semantic decision, contradictory evidence, a public/persisted contract, a security/concurrency boundary, or repeated correction that makes the cheaper route uneconomic. Downgrade from Sol after it has produced a frozen, independently testable slice and the remaining work is mechanical. Prefer a handoff/new task over a mid-turn switch when the current surface cannot change the model safely.
- Tests, Ruff, MyPy, `git diff --check`, and scoped Git audits are the correctness authority. A stronger model complements these gates; it never substitutes for them. Model selection never bypasses the user's lane-start decision.
- Pricing evidence reviewed on 2026-08-02: the current official Codex rate card is token-based and lists Luna at one twenty-fifth of Sol's listed input/cache/output credit rates, but total credit use still depends on task token mix and reasoning output. Keep this policy evidence-based and re-check it when the rate card changes: <https://help.openai.com/en/articles/20001106-codex-rate-card.docx>.
- Create each new Codex Worktree task from the latest `main`.
- A new worktree may start in detached `HEAD`; before beginning work, use **Create branch here** and confirm that the worktree is on its assigned `codex/...` branch.
- Use an independent `.venv` or Local Environment setup in each worktree. Do not copy the main worktree's `.venv`.

## Wave 1

All Wave 1 tasks were dispatched from `3382dd36c2a4aeb4acdab411e9211885b633e678`; their initial business-code baseline remains `e35b50d`.

- Active implementations authorized by the user: none.
- Completed read-only audit: `Gate S0` across A/B/C. Its reports froze the dependency direction
  `R1 -> R2 -> R3 -> R4`, require R1 and O1 schema ownership to be serialized, require O2 to
  consume R2 revision impact, and require H1 to reuse the R3 evidence facade.
- Integrated increments:
  - `embedding-production` increment A1 (provider and gateway embedding contract), merged as `fdbfb088278c18a0efb3e062cd5f9e8a6ddd01f4`.
  - `embedding-production` increment A2 (Gateway-backed document/query embedding provider plus fail-open semantic recall), merged as `03b2263043262cdf371f1929a1255162decabfac`.
  - `embedding-production` increment A3 (production embedding composition and bounded backend manual rebuild), merged as `1c1d26bafa78cc95d0251bfc88d9b5d88bcb3453`.
  - `embedding-production` increment A4 (retry only transient provider failures: HTTP `408`, `429`, and `5xx`), merged as `db03eddf227a2bd09e9831c365ccbf5384dceded`.
  - `generation-profile-audit-policy` increment B1 (domain and v17 persistence compatibility foundation), merged as `7802d8d9c5f2a9e2f16884b0c24de6199e8f2537`.
  - `generation-profile-audit-policy` increment B2 (application/UI migration from new `STRICT` creation to explicit generation profile and audit policy), merged as `840fcbdfff94e9c81073ba95e4a92065b7988259`.
  - `generation-profile-audit-policy` increment B3 (independent post-generation deep audit with single-model-audit ownership), merged as `ba13a2e`.
  - `view-operations-ui` increment C1 (single-record Legacy Reader Knowledge to Reader View UI), merged as `6f19d0a180ed72b9eafca6fb57d8eb550f429845`.
  - `view-operations-ui` increment C2 (single-record model View Assertion approve/reject UI), merged as `0b8c4006f396ea2024cd38de7a5b2e8b5f2d055b`.
  - `view-operations-ui` increment C3 (confirmed single-record pending model-candidate content editing with optimistic concurrency), merged as `4d2465f00173a6ffb758f7e4e5a3c493fa33e5a1`.
  - `view-operations-ui` increment C4 (unsaved pending-candidate edit guard), merged as `912ee211470a6b96c8a00b0145acb4883fb5373c`.
  - `manifest-eligibility-v2` increment M1 (versioned Context Manifest JSON envelope and compatible reader), merged as `812a737`.
  - `manifest-eligibility-v2` increment E1a (hard-filter authoritative stale history before Writer context), merged as `5233ccd`.
  - `manifest-eligibility-v2` increment E1b-SR1 (bounded audit omissions for unapproved CURRENT Style Rules), merged as `453a709`.
  - `view-operations-ui` increment C5 (confirmed single-current-chapter model extraction into atomically source-validated review candidates), merged as `8f3e851`.
  - `view-operations-ui` increment C6a (bounded sequential batch extraction with exact-revision idempotency), merged as `1e72d30`.
  - `generation-profile-audit-policy` increment B4 (latest read-only DEEP audit results for generated and recovered drafts), merged as `2d05ca4`.
  - `view-operations-ui` increment C6b (explicit multi-chapter selection, background coordination, progress, and cooperative cancellation UI), merged as `6f7d5b8`.
  - `generation-profile-audit-policy` increment B5 (exact evidence anchors for model-audit findings, fail-closed before persistence), merged as `f91a66a`.
  - `manifest-eligibility-v2` increment E1b-SS1 (metadata-only audit omissions for REVIEW/REJECTED Style Samples), merged as `5e1062e`.
  - `view-operations-ui` increment C7 (ephemeral, safe per-chapter batch extraction outcomes), merged as `a9ddfff`.
  - `manifest-eligibility-v2` increment E1b-CR1 (bounded, body-free omission candidates for CURRENT REVIEW Canon entries), merged as `14b1a1f`.
  - `view-operations-ui` increment C8 (correct View Assertion candidate-edit guidance), merged as `940ede1`.
  - `generation-profile-audit-policy` increment B6 (deterministic evidence provenance and safe editor-focus guard), merged as `5c0d128`.
  - `view-operations-ui` increment C9 (disambiguated pending View Assertion selector entries by source ID), merged as `59d40fc`.
  - `generation-profile-audit-policy` increment B7 (freshness gate for formal model-audit evidence), merged as `663f932`.
  - `manifest-eligibility-v2` increment E1b-CS1 (bounded, body-free omissions for prior REVIEW Character State events), merged as `ce4e7ba`.
  - `view-operations-ui` increment C10 (explicit manual refresh for pending View Assertion reviews), merged as `bc41148`.
  - `manifest-eligibility-v2` increment E1b-CE1 (bounded, body-free omissions for prior REVIEW Narrative Clue Events under approved current clues), merged as `0a8bb42`.
  - `view-operations-ui` increment C11 (bounded loaded pending View Assertion queue count/status feedback), merged as `6d56e03`.
  - `generation-profile-audit-policy` increment B8 (live formal model-audit completion snapshot guard), merged as `9e74afe`.
  - `view-operations-ui` increment C12 (fail-closed View Assertion review-list refresh feedback), merged as `6b40765`.
  - `generation-profile-audit-policy` increment B9 (validation-before-write for model audit findings), merged as `0c30227`.
  - `manifest-eligibility-v2` increment E1b-SM1 (hard-filter selected REVIEW SummaryNodes from prose context), merged as `c737b87`.
  - `generation-profile-audit-policy` increment B10 (deterministic premature Reader View exposure audit), merged as `139126d`.
  - `manifest-eligibility-v2` increment SE1 (schema-v18 physical Character State foundation), merged as `ef894fd`.
  - `manifest-eligibility-v2` increment SE2a (read-only physical Character State DTO projection), merged as `1fc4fed`.
  - `view-operations-ui` increment C13 (read-only physical Character State sidebar display), merged as `8d4e9bd`.
  - `generation-profile-audit-policy` increment B11 (deterministic contested-location Timeline audit), merged as `9a43bf5`.
  - `generation-profile-audit-policy` increment B12 (deterministic contested injury-status Character Consistency audit), merged as `853ae96`.
  - `generation-profile-audit-policy` increment B13 (deterministic contested current-goal Character Consistency audit), merged as `91ce02b`.
  - `generation-profile-audit-policy` increment B14 (tolerant ChapterRequirement provenance hardening), merged as `5266d47`.
  - `manifest-eligibility-v2` increment SE2c-W1 (Writer physical CharacterCard projection), merged as `eafeb8c`.
  - `manifest-eligibility-v2` increment SE3 (model-derived physical Character State extraction to REVIEW candidates), merged as `418f9bd`.
  - `style-engine` increment ST1 (bounded Writer Style Exemplar Retrieval), merged as `f55065f`.
  - `view-operations-ui` increment C14 (read-only Character physical-state semantics hint), merged as `fe91b52`.
  - `fix-p0-logging` increment P0-1 (model-boundary exception logging with path and credential redaction), merged as `ab13f98` plus security correction `36b0c2f`.
  - `view-operations-ui` increment S1 (canonical cross-volume chapter sequence and Reader visibility boundary), merged as `03f223e`.
  - `manifest-eligibility-v2` increment R1a (schema-v19 Formal Manuscript storage and structured embedding-cache identity foundation), merged as `4bba49a`.
  - `manifest-eligibility-v2` increment R1b (deterministic paragraph-aware Formal Manuscript chunk projection and bounded manual build), merged as `c4450e3`.
  - `manifest-eligibility-v2` increment R2a-F (RevisionImpact maintainer and bounded fail-closed Formal recovery foundation), merged as `dbb32f4`.
  - `manifest-eligibility-v2` increment R2b-C (manual save, generation acceptance, and repair routing through RevisionImpact maintenance), merged as `1feaf58`.
- Active schema owner: none.

| Task | Model / reasoning | Thread | Worktree | Assigned branch | HEAD state | Status |
| --- | --- | --- | --- | --- | --- | --- |

| `manifest-eligibility-v2` | `gpt-5.6-sol` / `high` | `019f87e8-6d32-7141-b9b4-4f1142e4db4e` | `C:\Users\钟子诚\.codex\worktrees\93d7\AI-Novel-Studio` | `codex/manifest-eligibility-r2b-c` | branch | R2b-C merged as `1feaf58`; lane paused pending explicit instruction |
| `generation-profile-audit-policy` | `gpt-5.6-terra` / `medium` | `019f87e8-696e-7f11-bcfe-1552f51cabc3` | `C:\Users\钟子诚\.codex\worktrees\4df4\AI-Novel-Studio` | `codex/generation-profile-audit-policy-b5` | branch | B1-B7 merged; B7 is `663f932`; lane paused pending explicit instruction |
| `view-operations-ui` | `gpt-5.6-luna` / `max` | `019f87e8-7a77-7902-b3d1-a38f32240136` | `C:\Users\钟子诚\.codex\worktrees\8802\AI-Novel-Studio` | `codex/view-operations-ui-s1` | branch | S1 merged as `03f223e`; lane paused pending explicit instruction |

Current dispatch override: no backend implementation ticket is active. A is paused after R2b-C.
Product decision A is approved: title rename and chapter relocation advance Chapter.revision and
create an unchanged-content ChapterVersion snapshot, but those lifecycle callers remain R2c-L
scope and are not authorized. B is paused after its Gate S0 report; `view-operations-ui` is paused
after S1; `style-engine` remains paused after ST1,
`generation-profile-audit-policy` remains paused after B14, and `fix-p0-logging` remains paused
after P0-1. P0-2 requires a separate ticket decision.

Supplemental planning status: shared Occurrence/View sparsification/Subject progressive history and
Formal Manuscript exact-evidence retrieval are now planned in
`2026-08-09-backend-refactor-supplemental-upgrade.md`. Gate S0 and its no-schema S1 prerequisite
are complete. ADR 0022 freezes the Formal Manuscript range, chunk identity, and structured
embedding-cache contract. R1a/schema v19, the no-schema R1b manual-build projection, and R2a-F
revision-local maintenance/recovery foundation and R2b-C production content-revision routing are
integrated. R2c-L remains unauthorized. R3-R4, O1-O2, H1, and V1 also remain unauthorized.

Product decision: Manual Pins are immutable materialized snapshots. They never automatically re-resolve or refresh from their source; authors update them only by removing and re-pinning. Do not add a live-pointer, automatic stale gate, or refresh behavior without a new explicit decision.

E1a, E1b-SR1, E1b-SS1, E1b-CR1, E1b-CS1, E1b-CE1, E1b-SM1, SE1, SE2a, SE2c-W1, SE3, ST1, S1, R1a, R1b, R2a-F, R2b-C, C6a, C6b, C7, C8, C9, C10, C11, C12, C13, C14, B4, B5, B6, B7, B8, B9, B10, B11, B12, B13, B14, and P0-1 are integrated. Every later increment still requires a new user decision.

## Later Waves and Dependencies

### Wave 2

- `manifest-eligibility-v2` begins only after `embedding-production` is reviewed and merged into `main`.
- `view-assertion-workflow` may run alongside `manifest-eligibility-v2` only when their file ownership is non-overlapping.
- Manifest and Eligibility remain one responsibility stream but must be delivered as separate commits.

### Wave 3

- `context-ranking-projection` begins only after the Context Compiler contract from Wave 2 is stable and merged.
- `state-events` and `style-engine` may run in parallel after their dependencies are on `main`.
- `context-ranking-projection` must not overlap active Manifest or Eligibility edits to Context Compiler core files.

### Wave 4

- `evidence-deep-audit` begins after the upstream compiler, state-event, and style contracts it audits are stable on `main`.
- `evaluation-harness` begins after the interfaces under evaluation are stable; its final results require master-controller review.
- Wave 4 is complete only after the consolidated full test, lint, and type-check gates pass on `main`.

## Worker Guardrails

- Workers must not merge into or push `main`.
- Workers run only ticket-specific narrow tests, lint for changed files, and type checks for the affected package. Do not run the full repository test suite unless the master explicitly requests it for a concrete cross-cutting risk.
- The master owns full-suite validation at wave boundaries and other explicit consolidation gates; workers should report their exact narrow scope instead of duplicating that cost.
- Workers must not modify manuscripts, databases, backups, exports, API keys, or secrets.
- Only one active worktree may own schema changes at a time. The master controller records and assigns the schema owner before work begins.
- Do not introduce a second architecture, parallel service layer, replacement pipeline, or duplicate persistence path. Extend the existing boundaries with the smallest correct change.
- Each worker changes only its assigned ticket and explicitly reports anything discovered outside scope.
- Structured model output is untrusted and must be validated before persistence.

## Proactive Worker Feedback

Every worktree worker must send a cross-task report directly to the master task for these events:

- `BLOCKED`: the assigned ticket cannot continue safely.
- `SCOPE_CHANGE`: the required files or behavior exceed the approved ticket.
- `DECISION_REQUIRED`: multiple materially different solutions require a master decision.
- `READY_FOR_REVIEW`: the approved increment is complete and ready for master verification.

Workers must not rely only on a reply in their own task. When cross-task messaging is available, send the report to master task `019f87b5-ce06-7f82-bb24-871f43b98f32` and confirm delivery locally. Use this format:

```text
MASTER REPORT

Event: BLOCKED | SCOPE_CHANGE | DECISION_REQUIRED | READY_FOR_REVIEW
Task:
Branch:
Baseline main SHA:
Current commit state: uncommitted | committed-not-pushed | pushed
Evidence:
Impact:
Recommendation:
Requested master action:
Changed files:
Tests and checks:
```

If cross-task messaging is unavailable, output the same `MASTER REPORT` block for the user to paste into the master task.

### Frontend isolation exception

Tasks assigned to `codex/frontend-*` branches or an explicitly frontend-only redesign scope are not participants in this backend reporting plane. They must not contact the backend master or A/B/C tasks, must not edit this Board, and must keep all writes, tests, environments, and Git operations inside their dedicated frontend worktree. Their status and review output remain in their own frontend conversation unless the user explicitly requests cross-task communication.

Do not copy the following local-only or sensitive workspace files into any worktree:

- `.venv`
- `models.json`
- `PROJECT_LOCATION.md`
- `.privacy-blocklist`

## Worker Handoff Template

```text
READY FOR MASTER REVIEW

Task:
Branch:
Baseline main SHA:
Final commit SHA:
Commits:
Changed files:
Explicitly not changed:
Narrow tests:
Full Pytest:
Ruff:
MyPy:
Schema involved:
Compatibility and risks:
```

## Master Review Commands

Run from the master worktree, substituting the worker branch name:

```powershell
git log --oneline main..codex/<worker-branch>
git diff --stat main...codex/<worker-branch>
git diff --check main...codex/<worker-branch>
git diff main...codex/<worker-branch>
```

If `main` advanced after the worker baseline, the worker must first sync with the latest `main`, resolve conflicts in its own worktree, rerun its checks, and provide a new final commit SHA.

## Merge Gates

### Cost-aware master review

- Treat the worker's evidence, narrow tests, and self-review as the primary review record. The master does not automatically repeat the worker's full investigation or reread every changed line.
- For ordinary UI, documentation, and isolated low-risk tickets, the master checks branch/baseline, changed-file scope, commit cleanliness, reported gates, and a small integration smoke test or targeted spot-check.
- Use deep master review only for public-contract changes, schema or migration work, security and untrusted-input boundaries, persistence semantics, cross-module refactors, merge conflicts, or contradictory/incomplete worker evidence.
- Reuse completed read-only review findings instead of commissioning or manually duplicating the same review axis. Escalate only the concrete risk that remains unresolved.

A worker branch may be integrated only when all applicable gates pass:

1. The delivery uses the `READY FOR MASTER REVIEW` template and identifies an auditable final commit.
2. The diff is limited to the assigned ticket and does not violate file ownership or worker guardrails.
3. `git diff --check` is clean and the branch contains no secrets, user content, local-only files, generated junk, or unintended schema changes.
4. Narrow tests pass; relevant lint and type checks pass. Any skipped check is explained and approved by the master controller.
5. Public contracts, migrations, backward compatibility, error handling, and model-output validation are reviewed where applicable.
6. The branch is based on the current integration baseline, or has been resynchronized and revalidated after `main` advanced.
7. The master controller performs the integration, runs post-merge relevant checks, and records the merged SHA before dispatching dependent work.
8. At the end of each wave, the master controller runs the full Pytest, Ruff, and MyPy suites before the next wave is declared ready.
