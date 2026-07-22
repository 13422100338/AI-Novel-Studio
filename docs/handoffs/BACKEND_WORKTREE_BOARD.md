# Backend Worktree Master Board

## Control Plane

- Master controller: current pinned Codex task.
- Integration policy: `main`-only integration. Worker tasks never merge or push `main`.
- Superpowers: disabled for this project workflow.
- Initial code baseline: `e35b50d`.
- Planning sources:
  - `docs/handoffs/2026-07-22-backend-refactor-handoff.md`
  - `C:\Users\钟子诚\Downloads\AI_Novel_Studio_后端改进方案_Subject_View_Time_Context_Compiler_修订版.md`

## Worktree Startup Rules

- Create each new Codex Worktree task from the latest `main`.
- A new worktree may start in detached `HEAD`; before beginning work, use **Create branch here** and confirm that the worktree is on its assigned `codex/...` branch.
- Use an independent `.venv` or Local Environment setup in each worktree. Do not copy the main worktree's `.venv`.

## Wave 1

All Wave 1 tasks start from the initial baseline unless the master controller issues a newer baseline.

| Task | Model / reasoning | Thread | Worktree | Branch | Status |
| --- | --- | --- | --- | --- | --- |
| `embedding-production` | `gpt-5.6-sol` / `high` | TBD | TBD | `codex/embedding-production` | Not started |
| `generation-profile-audit-policy` | `gpt-5.6-terra` / `medium` | TBD | TBD | `codex/generation-profile-audit-policy` | Not started |
| `view-operations-ui` | `gpt-5.6-terra` / `medium` | TBD | TBD | `codex/view-operations-ui` | Not started |

Suggested integration order: `embedding-production` -> `generation-profile-audit-policy` -> `view-operations-ui`.

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
- Workers must not modify manuscripts, databases, backups, exports, API keys, or secrets.
- Only one active worktree may own schema changes at a time. The master controller records and assigns the schema owner before work begins.
- Do not introduce a second architecture, parallel service layer, replacement pipeline, or duplicate persistence path. Extend the existing boundaries with the smallest correct change.
- Each worker changes only its assigned ticket and explicitly reports anything discovered outside scope.
- Structured model output is untrusted and must be validated before persistence.

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

A worker branch may be integrated only when all applicable gates pass:

1. The delivery uses the `READY FOR MASTER REVIEW` template and identifies an auditable final commit.
2. The diff is limited to the assigned ticket and does not violate file ownership or worker guardrails.
3. `git diff --check` is clean and the branch contains no secrets, user content, local-only files, generated junk, or unintended schema changes.
4. Narrow tests pass; relevant lint and type checks pass. Any skipped check is explained and approved by the master controller.
5. Public contracts, migrations, backward compatibility, error handling, and model-output validation are reviewed where applicable.
6. The branch is based on the current integration baseline, or has been resynchronized and revalidated after `main` advanced.
7. The master controller performs the integration, runs post-merge relevant checks, and records the merged SHA before dispatching dependent work.
8. At the end of each wave, the master controller runs the full Pytest, Ruff, and MyPy suites before the next wave is declared ready.
