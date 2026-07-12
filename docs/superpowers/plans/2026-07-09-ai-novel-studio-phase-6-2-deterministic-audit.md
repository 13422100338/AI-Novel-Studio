# Phase 6.2 Deterministic Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a pure deterministic audit service that detects mechanical chapter issues without calling models, writing storage, changing UI, or modifying manuscript content.

**Architecture:** The service lives in the application layer and returns immutable finding candidates typed with Phase 6 audit enums. It does not know SQLite, project layout, model gateway, or UI widgets. Later tasks can persist these candidates into `audit_findings`.

**Tech Stack:** Python 3.11+, dataclasses, regex, pytest, ruff.

## Global Constraints

- Make the smallest correct change.
- Do not modify user manuscripts, databases, backups, exports, API keys, or secrets.
- Keep UI, data storage, model calls, and pipeline logic separated.
- Phase 6.2 must not call any model.
- Phase 6.2 must not write SQLite.
- Phase 6.2 must not modify formal chapter content.
- Write tests before production code.

---

## File Structure

- Create `src/ai_novel_studio/application/deterministic_audit_service.py`
  - Owns `DeterministicAuditRequest`, `DeterministicFinding`, and `DeterministicAuditService`.
- Create `tests/unit/application/test_deterministic_audit_service.py`
  - Covers empty text, empty requirement, model residue, duplicate paragraphs, unbalanced quotes, and missing required requirement phrases.

## Task 1: Pure Deterministic Audit Service

**Files:**
- Create: `src/ai_novel_studio/application/deterministic_audit_service.py`
- Test: `tests/unit/application/test_deterministic_audit_service.py`

**Interfaces:**
- Consumes:
  - `AuditFindingCategory`
  - `AuditSeverity`
  - `AuditFindingSource`
- Produces:
  - `DeterministicAuditRequest`
  - `DeterministicFinding`
  - `DeterministicAuditService.run(request) -> tuple[DeterministicFinding, ...]`

- [ ] **Step 1: Write failing tests**

Create tests that import the service and assert findings for mechanical issues.

- [ ] **Step 2: Run test to verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/application/test_deterministic_audit_service.py -q -p no:cacheprovider
```

Expected: FAIL because the service module does not exist.

- [ ] **Step 3: Implement minimal service**

Implement rule functions for:

- empty target text;
- empty current chapter requirement;
- common model-output residue;
- duplicate non-trivial paragraphs;
- unbalanced quote/bracket pairs;
- missing required phrases from requirement lines prefixed with `must:`, `必须`, `需要`, or `硬性`.

- [ ] **Step 4: Run test to verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/application/test_deterministic_audit_service.py -q -p no:cacheprovider
```

Expected: PASS.

- [ ] **Step 5: Narrow regression**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/application/test_deterministic_audit_service.py tests/unit/domain/test_audit_records.py -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m ruff check src/ai_novel_studio/application/deterministic_audit_service.py tests/unit/application/test_deterministic_audit_service.py
```

Expected: PASS.

