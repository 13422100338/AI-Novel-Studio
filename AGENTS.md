# AI Novel Studio Agent Rules

## Project Rules

1. Make the smallest correct change.
2. Do not rewrite architecture unless explicitly asked.
3. Do not modify user manuscripts, databases, backups, exports, API keys, or secrets.
4. Do not scan `.venv`, `build`, `dist`, `__pycache__`, backups, exports, or large generated files unless explicitly asked.
5. Keep UI, data storage, model calls, and pipeline logic separated.
6. Model outputs are untrusted; validate structured outputs before saving them.
7. Prefer deterministic program logic over prompt-only solutions.
8. Before changing files, identify the exact files involved and explain the minimal plan.
9. After changing files, run the narrowest relevant test or provide the exact test command.
10. If a task is large, split it into small implementation tickets and complete only the current ticket.
11. Never silently delete, truncate, or overwrite user content.
12. End with a concise summary: changed files, verification result, risks, and next step.

## Subagent Policy

- Do not enable internal subagents by default.
- Use internal subagents only for independent, read-only codebase investigation, risk review, or test-coverage analysis.
- A parent task may run at most two internal subagents concurrently.
- Internal subagents are read-only. They must not edit files, run database migrations, commit, push, merge, or otherwise change repository state.
- Internal subagents must not recursively create other subagents.
- Before starting internal subagents, the main agent must explain why they are needed, assign a distinct scope to each one, and explain why their work does not overlap.
- The main agent must independently verify subagent findings and must not treat their conclusions as project facts without checking the cited evidence.
- Within each Codex task, its main agent owns all file edits and final code changes; internal subagents remain read-only.
- Project architecture decisions, schema changes, migrations, and cross-module refactors require approval and coordination by the master task.
- Parallel coding must use separate Codex tasks with separate Git worktrees. Independent worktree tasks are not internal subagents and may edit only their assigned branch and ticket.
- Subagent reports must include evidence such as file paths, symbols, test results, or concrete call chains.

## Worktree Worker Reporting

- Worktree workers must proactively report `BLOCKED`, `SCOPE_CHANGE`, `DECISION_REQUIRED`, and `READY_FOR_REVIEW` events to the master task registered in `docs/handoffs/BACKEND_WORKTREE_BOARD.md`.
- Workers must use Codex cross-task messaging when available and must not rely only on a reply in their own task.
- Reports must include the task, branch, baseline SHA, evidence, impact, recommendation, requested master action, changed files, tests, and commit state.
- If cross-task messaging is unavailable, output a `MASTER REPORT` block for the user to paste into the master task.
