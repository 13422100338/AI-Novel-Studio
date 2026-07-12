# Phase 6.1 Audit Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the Phase 6.1 audit domain records, enum boundaries, and SQLite schema migration without adding UI, model calls, or repair behavior.

**Architecture:** The audit layer starts as storage-safe domain data and schema only. UI, model audit services, deterministic audit services, and repair services remain future tasks. The migration follows the existing append-only migration pattern and preserves all v3 data.

**Tech Stack:** Python 3.11+, dataclasses, `StrEnum`, SQLite, pytest.

## Global Constraints

- Make the smallest correct change.
- Do not modify user manuscripts, databases, backups, exports, API keys, or secrets.
- Keep UI, data storage, model calls, and pipeline logic separated.
- Model outputs are untrusted; validate structured outputs before saving them in later tasks.
- Phase 6.1 must not call any model.
- Phase 6.1 must not modify formal chapter content.
- Write tests before production code.

---

## File Structure

- Create `src/ai_novel_studio/domain/audit.py`
  - Owns audit enums and immutable records only.
- Modify `src/ai_novel_studio/infrastructure/storage/migration_manager.py`
  - Bumps `LATEST_SCHEMA_VERSION` from 3 to 4.
  - Adds `_migration_4` with audit tables and constraints.
- Create `tests/unit/domain/test_audit_records.py`
  - Covers enum values, immutable records, confidence validation, non-negative revision/token fields, and required text validation.
- Create `tests/integration/storage/test_audit_schema.py`
  - Covers v3 to v4 migration, audit table creation, CHECK constraints, indexes, and data preservation.

## Task 1: Audit Domain Records

**Files:**
- Create: `src/ai_novel_studio/domain/audit.py`
- Test: `tests/unit/domain/test_audit_records.py`

**Interfaces:**
- Produces enums:
  - `AuditTargetKind`
  - `AuditRunStatus`
  - `AuditFindingCategory`
  - `AuditSeverity`
  - `AuditFindingSource`
  - `AuditFindingStatus`
  - `RepairStrategy`
  - `RepairProposalStatus`
  - `ProvenanceEventType`
- Produces records:
  - `AuditRun`
  - `AuditFinding`
  - `RepairProposal`
  - `ProvenanceEvent`

- [ ] **Step 1: Write failing domain tests**

Create `tests/unit/domain/test_audit_records.py` with tests for stable enum values, immutable records, confidence bounds, required text fields, and non-negative revisions/tokens.

- [ ] **Step 2: Run test to verify RED**

Run:

```powershell
python -m pytest tests/unit/domain/test_audit_records.py -q
```

Expected: FAIL because `ai_novel_studio.domain.audit` does not exist.

- [ ] **Step 3: Implement minimal domain records**

Create `src/ai_novel_studio/domain/audit.py` with immutable dataclasses and validation helpers mirroring the existing generation domain style.

- [ ] **Step 4: Run test to verify GREEN**

Run:

```powershell
python -m pytest tests/unit/domain/test_audit_records.py -q
```

Expected: PASS.

## Task 2: Audit Schema Migration

**Files:**
- Modify: `src/ai_novel_studio/infrastructure/storage/migration_manager.py`
- Test: `tests/integration/storage/test_audit_schema.py`

**Interfaces:**
- Consumes enum values from the Phase 6.1 spec.
- Produces SQLite tables:
  - `audit_runs`
  - `audit_findings`
  - `repair_proposals`
  - `provenance_events`

- [ ] **Step 1: Write failing migration tests**

Create `tests/integration/storage/test_audit_schema.py` that migrates a v3 database to v4, confirms existing v3 rows remain, confirms new audit tables exist, and verifies CHECK constraints for invalid statuses and confidence.

- [ ] **Step 2: Run test to verify RED**

Run:

```powershell
python -m pytest tests/integration/storage/test_audit_schema.py -q
```

Expected: FAIL because `LATEST_SCHEMA_VERSION` is still 3 and audit tables do not exist.

- [ ] **Step 3: Implement migration 4**

Add `_migration_4`, bump `LATEST_SCHEMA_VERSION` to 4, and register it in `MIGRATIONS`.

- [ ] **Step 4: Run test to verify GREEN**

Run:

```powershell
python -m pytest tests/integration/storage/test_audit_schema.py -q
```

Expected: PASS.

## Task 3: Narrow Regression

**Files:**
- Test only.

- [ ] **Step 1: Run related domain and storage tests**

Run:

```powershell
python -m pytest tests/unit/domain/test_audit_records.py tests/unit/domain/test_generation_records.py tests/integration/storage/test_audit_schema.py tests/integration/storage/test_generation_schema.py -q
```

Expected: PASS.

- [ ] **Step 2: Run lint on touched Python files**

Run:

```powershell
python -m ruff check src/ai_novel_studio/domain/audit.py src/ai_novel_studio/infrastructure/storage/migration_manager.py tests/unit/domain/test_audit_records.py tests/integration/storage/test_audit_schema.py
```

Expected: PASS.

- [ ] **Step 3: Commit**

Run:

```powershell
git add docs/superpowers/plans/2026-07-09-ai-novel-studio-phase-6-1-audit-schema.md src/ai_novel_studio/domain/audit.py src/ai_novel_studio/infrastructure/storage/migration_manager.py tests/unit/domain/test_audit_records.py tests/integration/storage/test_audit_schema.py
git commit -m "feat: add phase 6 audit schema"
```

