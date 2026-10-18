# ADR 0025: Freeze Harness approval execution receipts and crash recovery

## Status

Accepted

## Date

2026-08-28

## Context

ADR 0024 separates an author's approval decision from the deterministic backend commit, the
Harness run stage, and the result shown to the author. The current implementation does not yet
preserve those four facts across a process crash:

- `harness.approvals.ApprovalStatus` contains only `PENDING`, `APPROVED`, and `REJECTED`;
- `ApprovalService.resolve_approval` persists the decision and emits `APPROVAL_RESOLVED`, but does
  not finalize the backend commit or the run;
- persisted `APPROVAL_RESOLVED` schema-version-1 events carry
  `{request_id, approved}` and are historical author-decision evidence, not execution receipts;
- `ApprovalResolver.resolve_and_commit` dispatches commits after resolving the approval and only
  has a special pre-commit `STALE` transition for one SubjectMerge revision check;
- the exact S2b baseline's `ChangeSetService.commit` checks that `idempotency_key` is non-empty but
  does not persist it as a commit receipt; S2a now preflights all operations and uses one
  caller-owned SQLite transaction plus in-memory `ChapterFileTransaction` compensation, but a
  process crash can still strand published history/canonical files outside SQLite rollback;
- S2a accepts a same-title `CHAPTER_TITLE_CHANGE` as `APPLIED` with unchanged revision/content and
  no history/canonical file action, so S2b must represent that result as a typed `NO_OP` rather than
  force indistinguishable database pre/final predicates;
- the S2a `OperationOutcome` now has typed failure class/code in addition to `READY`, `APPLIED`,
  `FAILED`, and a display `message`, but that complete result is not yet persisted as the terminal
  approval execution receipt;
- `ApprovalRepository` remains the author-decision owner, while the integrated v25
  `ApprovalExecutionReceiptRepository` is a constrained foundation that the current resolver does
  not yet wire atomically to ChangeSet execution, events, and the run row;
- schema v22 constrains `payload_json` only as non-null text with default `{}`; historical rows may
  therefore contain JSON `null`, `{}`, malformed JSON, or a shape that cannot yield a stable
  kind-specific commit target;
- `SubjectMergeService` reaches a transactional `character_identity_merges` record, but that record
  is not bound to an approval request or its idempotency key;
- `HarnessEventRepository` updates the run row and appends events through separate transactions,
  while `HarnessEventStore` rejects late events after `COMPLETED`, `CANCELLED`, or `FAILED`;
- `HarnessRunEngine.recover_open_runs` restores in-process cancellation tokens but does not recover
  an approval commit;
- `CompletionChecker` detects pending approvals and some stage inconsistencies, while
  `CompactionGate` infers a possible in-flight commit from an `approved` event boolean rather than
  durable execution state;
- `HarnessAgentPort`, `HarnessAgentTimelineController`, and `MockNovelStudioFacade` return no typed
  disposition; the live QML path currently treats `approved=True` as `APPLIED` and reloads the
  chapter immediately.

At the original 2026-08-28 decision baseline, the migration registry in
`infrastructure.storage.schema_migrations` ended at schema v24; schema v22 had created
`harness_approvals`, so this ADR reserved v25 rather than guessing or reusing an older number. At
the exact S2b correction baseline `113799cffac44f2e110046042e95dad59c92084d`, the v25 receipt/event
foundation and S2a ChangeSet UoW are present. S2b introduces no migration or schema v26; S2c later
wires the already-reserved v25 receipt/event/run transaction contract.

The trust boundaries are the author command, persisted proposal payload, deterministic backend
facade, SQLite transaction, append-only run log, and QML projection. Proposal and model data are
untrusted. A receipt is an audit and recovery primitive, not a second manuscript store, and must
not become a new channel for novel text, credentials, provider output, or internal exceptions.

## Decision

### 1. Keep four facts separate

The system has four distinct facts:

| Fact | Owner | Vocabulary |
|---|---|---|
| Author decision | Harness approval lifecycle | `PENDING -> APPROVED | REJECTED` |
| Deterministic commit outcome | Backend facade plus durable execution receipt | typed success or typed failure |
| Run lifecycle | Harness | existing `RunStage` |
| User-facing result | Harness projection | `ApprovalDisposition` |

`ApprovalDisposition` is exactly:

```text
APPLIED | DISCARDED | STALE | FAILED
```

It is neither an `ApprovalStatus` nor a new `RunStage`. `ApprovalStatus.APPROVED` means only that
the author authorized an attempt. It never proves that a formal write occurred.

The receipt also has an internal execution state:

```text
PENDING_DECISION | READY | EXECUTING | RECOVERY_REQUIRED | FINALIZED
```

Only `FINALIZED` may carry a non-null disposition. `RECOVERY_REQUIRED` represents an ambiguous
pre-v25 or interrupted execution that must be reconciled from exact domain evidence; it is not a
user-facing result.

### 2. Freeze the terminal mapping

| Decision and deterministic commit fact | Run stage | Disposition |
|---|---|---|
| `APPROVED` and every intended operation is durably `APPLIED` | `COMPLETED` | `APPLIED` |
| `APPROVED` and a typed revision, content-hash, or patch-replay conflict is proven | `STALE` | `STALE` |
| `APPROVED` and validation, persistence, integrity, unsupported-kind, partial, or missing outcome occurs | `FAILED` | `FAILED` |
| `REJECTED` / discard, with no formal commit | `COMPLETED` | `DISCARDED` |

A ChangeSet is `APPLIED` only when its durable result contains exactly one outcome for every
intended operation and every outcome is `APPLIED`. `READY`, `FAILED`, a shorter result, a duplicate
operation result, or a partial result can never map to `APPLIED`.

`STALE` is terminal for this approval execution even though the current run state machine keeps the
run stage open for later recompilation. A later attempt must create or select a new approval
identity; it must not reopen or recommit the terminal stale approval.

Typed stale failures are limited to explicit codes under a stale-conflict classification, including
`REVISION_CONFLICT`, `CONTENT_HASH_CONFLICT`, and `PATCH_REPLAY_CONFLICT`. Validation,
serialization, unsupported approval kind, idempotency-identity mismatch, database error, missing
outcome, and partial outcome are ordinary failures and map to `FAILED`. Implementations must not
inspect `message`, translated UI text, exception text, or a substring such as "stale" to choose a
disposition.

### 3. Use an independent durable receipt table

Two shapes were considered:

| Shape | Advantages | Problems | Decision |
|---|---|---|---|
| Add execution columns to `harness_approvals` | Fewer joins; superficially fewer objects | Mixes author intent with commit fact; many nullable columns; harder lifecycle constraints and rollback | Rejected |
| Add a one-to-one `harness_approval_execution_receipts` table | Preserves fact separation; additive v25; independently constrained and queryable; reversible before use | One join and one repository | Chosen |

The logical v25 table is one-to-one with `harness_approvals` and freezes these fields:

```text
approval_request_id       primary key and foreign key
run_id                    stable Harness run identity
idempotency_key           stable execution identity
kind                      ApprovalKind snapshot
decision                  null | APPROVED | REJECTED
execution_state           PENDING_DECISION | READY | EXECUTING |
                          RECOVERY_REQUIRED | FINALIZED
disposition               null | APPLIED | DISCARDED | STALE | FAILED
commit_target_kind        CHANGESET | SUBJECT_MERGE | PROJECT_CONSTITUTION |
                          UNSUPPORTED_APPROVAL | LEGACY_UNRESOLVED
commit_target_id          stable target, proposal, or approval identity
target_identity_json      bounded, validated identity evidence
domain_receipt_id         nullable exact backend commit-record identity
result_evidence_json      bounded, validated result evidence
failure_class             nullable typed failure classification
failure_code              nullable bounded machine code
failure_summary           nullable sanitized author-safe summary
created_at
updated_at
started_at
finalized_at
revision                  non-negative CAS revision
```

`UNIQUE(run_id, idempotency_key)` preserves the current approval identity. The receipt's
`approval_request_id`, `run_id`, `idempotency_key`, and `kind` must exactly match its approval row.
The commit-target vocabulary is closed for v25:

- ChangeSet: `change_set_id`, intended operation IDs, operation kinds, target IDs, expected
  revisions, and relevant source hashes; `commit_target_kind=CHANGESET` and `commit_target_id` is
  the `change_set_id`;
- SubjectMerge: approval request identity, source and target subject IDs, and expected revisions;
  `commit_target_kind=SUBJECT_MERGE`; because the current proposal has no separate ID,
  `commit_target_id` is the `approval_request_id`;
- ProjectConstitution: approval request identity, project ID, base revision, and a canonical
  proposal digest; `commit_target_kind=PROJECT_CONSTITUTION`; because the current proposal has no
  separate ID, `commit_target_id` is the `approval_request_id`;
- Unsupported approval: `commit_target_kind=UNSUPPORTED_APPROVAL` for an ApprovalKind such as
  `PROMPT_CHANGE` or `SKILL_CHANGE` that has no V1 commit facade. `commit_target_id` is the
  `approval_request_id`, and the identity DTO is exactly
  `{schema_version: unsupported-approval-v1, approval_request_id, approval_kind,
  reason_code: UNSUPPORTED_KIND}`;
- Unresolved legacy target: `commit_target_kind=LEGACY_UNRESOLVED` only for a receipt created by
  v25 migration/backfill when a pre-v25 commit-capable approval payload is absent, JSON `null`,
  empty, malformed, unknown, or cannot be reduced to a fully validated allowlisted target identity.
  `commit_target_id` is the `approval_request_id`, and the identity DTO is exactly
  `{schema_version: legacy-unresolved-v1, approval_request_id, approval_kind,
  reason_code: MISSING_OR_INVALID_TARGET_IDENTITY}`.

The two non-commit identities never authorize a backend write. Their identity DTOs have no optional
raw-data field and may not include or hash the legacy payload as a substitute for target identity.

`target_identity_json` and `result_evidence_json` use allowlisted DTOs, have fixed item and byte
caps, and use stable ordering before hashing or serialization. ChangeSet evidence is capped by the
existing maximum of 50 operations; each JSON field is capped at 16 KiB of UTF-8. Result evidence
may include operation ID, typed status, committed revision/hash, merge record ID/status, or
constitution revision. `failure_class` and `failure_code` use an ASCII machine vocabulary capped
at 64 characters each, and `failure_summary` is capped at 512 Unicode code points. None of these
fields may include manuscript text, replacement text, the complete selection payload, complete
proposal payload, filesystem paths, raw exception text, raw provider request/response data,
prompts, tokens, credentials, or secrets. Diagnosis uses machine codes and separately protected
logs, not a receipt payload dump.

State combinations are closed and enforced by the receipt-table `CHECK`, the receipt DTO, and the
repository transition API:

- `CHANGESET`, `SUBJECT_MERGE`, and `PROJECT_CONSTITUTION` may use `PENDING_DECISION`, `READY`,
  `EXECUTING`, `RECOVERY_REQUIRED`, and `FINALIZED`. `PENDING_DECISION` requires null
  decision/disposition; `READY`, `EXECUTING`, and `RECOVERY_REQUIRED` require `APPROVED` with null
  disposition; `FINALIZED` allows only `APPROVED + APPLIED|STALE|FAILED` or
  `REJECTED + DISCARDED`.
- `LEGACY_UNRESOLVED` may use only `PENDING_DECISION`, `RECOVERY_REQUIRED`, or `FINALIZED`; it can
  never enter `READY` or `EXECUTING`. `PENDING_DECISION` requires null decision/disposition;
  `RECOVERY_REQUIRED` requires `APPROVED` with null disposition; `FINALIZED` allows only
  `REJECTED/DISCARDED` with no failure or `APPROVED/FAILED` with the required typed failure. A
  pending migrated row remains the same visible approval. Later rejection maps to
  `FINALIZED/DISCARDED` with no failure and no formal write. Later approval maps directly to
  `FINALIZED/FAILED` with `failure_class=INTEGRITY` and
  `failure_code=MISSING_TARGET_IDENTITY`, with no formal write.
- `UNSUPPORTED_APPROVAL` may use only `PENDING_DECISION` or `FINALIZED`;
  `PENDING_DECISION` requires null decision/disposition. Rejection maps to
  `FINALIZED/DISCARDED` with no failure; approval maps to `FINALIZED/FAILED` with
  `failure_class=UNSUPPORTED` and `failure_code=UNSUPPORTED_KIND`. It never calls a backend facade.
- A `LEGACY_UNRESOLVED/RECOVERY_REQUIRED` row may leave that target kind only when an exact
  approval-bound durable domain receipt supplies and validates a normal kind-specific target
  identity. Recovery first CAS-reclassifies the receipt to the matching normal commit-target kind,
  then finalizes solely from that durable result; it never executes the commit during
  reclassification. `LEGACY_UNRESOLVED` itself can never be `APPLIED` or `STALE`.

The SQL `CHECK` must enforce the five-value commit-target vocabulary and the cross-field
target-kind/state/decision/disposition/failure combinations. The DTO repeats those invariants and
validates the exact allowlisted identity shape; the repository repeats them before every insert,
CAS transition, reclassification, and load. A row that violates any layer fails closed rather than
being coerced into a valid-looking state.

The existing `harness_approvals.payload_json` remains the current proposal transport at this
baseline. This ADR does not endorse duplicating it into the receipt and does not expand its
retention. A broader proposal-payload retention redesign is a separate ticket.

Every receipt transition uses compare-and-swap:

```text
UPDATE ... SET ..., revision = revision + 1
WHERE approval_request_id = ? AND revision = ? AND execution_state = ?
```

Exactly one row must change. A zero-row update means another worker won, the state is terminal, or
identity drift occurred; the caller reloads and returns/reconciles the durable state rather than
executing again.

### 4. Reserve schema v25 for H-APPR1b

H-APPR1b is the exclusive owner of schema v25. No other ticket may claim v25 or modify the receipt
shape while H-APPR1b is open. The integrated v25 foundation creates the receipt table, constraints,
and indexes, registers `APPROVAL_EXECUTION_FINALIZED` in `RunEventType`, extends the
`harness_run_events.event_type` constraint to admit it, and performs the bounded receipt backfill
defined here. Backfill validates each historical row independently; an empty, malformed,
JSON-null, or unknown legacy payload must not abort the whole project upgrade. S2b consumes none of
this as a filesystem preimage and adds no schema; S2c later supplies the end-to-end transactional
wiring.

| Historical ApprovalKind and target parse | Historical status | Backfilled target/state |
|---|---|---|
| Commit-capable kind with fully validated normal target identity | `PENDING` | Normal target kind + `PENDING_DECISION` |
| Commit-capable kind with fully validated normal target identity | `REJECTED` | Normal target kind + `FINALIZED/DISCARDED` |
| Commit-capable kind with fully validated normal target identity | `APPROVED` | Normal target kind + `RECOVERY_REQUIRED`; never guess application |
| Commit-capable kind with missing/invalid target identity | `PENDING` | `LEGACY_UNRESOLVED/PENDING_DECISION` |
| Commit-capable kind with missing/invalid target identity | `REJECTED` | `LEGACY_UNRESOLVED/FINALIZED/DISCARDED` |
| Commit-capable kind with missing/invalid target identity | `APPROVED` | `LEGACY_UNRESOLVED/RECOVERY_REQUIRED`; exact domain receipt or fail closed |
| `PROMPT_CHANGE` / `SKILL_CHANGE` without a V1 facade | `PENDING` | `UNSUPPORTED_APPROVAL/PENDING_DECISION` |
| `PROMPT_CHANGE` / `SKILL_CHANGE` without a V1 facade | `REJECTED` | `UNSUPPORTED_APPROVAL/FINALIZED/DISCARDED` |
| `PROMPT_CHANGE` / `SKILL_CHANGE` without a V1 facade | `APPROVED` | `UNSUPPORTED_APPROVAL/FINALIZED/FAILED`, `UNSUPPORTED_KIND` |

For a safely parseable legacy ChangeSet, SubjectMerge, or ProjectConstitution row, migration may
use the normal target kind only after the complete kind-specific DTO, identifiers, revisions,
digests, caps, and allowlist validate. Any parse/validation failure degrades that single receipt to
`LEGACY_UNRESOLVED`; migration does not invent `change_set_id`, proposal identity, revision, digest,
or any other target field.

`LEGACY_UNRESOLVED` is migration provenance, not a compatibility escape hatch. A fresh v25
commit-capable approval must have a complete valid normal target identity before approval
persistence, or in the same request-creation transaction before any row/event becomes visible.
Invalid fresh input fails before persistence. Fresh request code, DTO constructors, and repository
APIs must reject `commit_target_kind=LEGACY_UNRESOLVED`.

Upgrade verification must assert schema version 25, table/index presence, foreign-key integrity,
one receipt per approval, stable identity equality, valid state/disposition combinations, and no
duplicate `(run_id, idempotency_key)`. Because SQLite cannot alter the existing event-type
`CHECK` in place, v25 may use a constraint-only table rebuild, but it must copy every historical
event field-for-field: ID, run ID, sequence, event type, schema version, timestamp, causation,
correlation, and exact payload JSON. Verification must compare row counts and per-row values before
the swap.

Migration/backfill must not update, reinterpret, delete, resequence, or synthesize append-only
historical events. In particular, it must not rewrite schema-version-1 `APPROVAL_RESOLVED`
booleans into a terminal disposition and must not backdate synthetic
`APPROVAL_EXECUTION_FINALIZED` events. Migration, constraint rebuild, and receipt backfill execute
in one SQLite transaction; a failure rolls back to v24.

Upgrade tests must cover legacy payload JSON that is `null`, `{}`, malformed JSON, an unknown
shape, and a valid shape for each commit-capable kind; every ApprovalStatus branch for
`LEGACY_UNRESOLVED`; both unsupported kinds; and fresh-v25 rejection of the migration-only target
kind. Tests must also prove that target/result/failure evidence does not contain or derive from raw
payload, manuscript, selection/proposal content, path, or exception data.

The receipt table is additive; the event change is a vocabulary-constraint extension with an exact
history copy. Before any v25 event/receipt is used, rollback can transactionally restore the v24
constraint and drop the new table after verifying that no v25 event exists. After a v25 receipt has
authorized or recorded a formal commit or an `APPROVAL_EXECUTION_FINALIZED` event exists, a lossy
downgrade is unsafe. Binary rollback must preserve v25 in read-only compatibility mode or restore a
verified pre-upgrade backup. A downgrade rehearsal on a copy must verify schema v24, foreign keys,
approval/event row preservation, exact historical event payloads, and the absence of v25-only
writes before release.

This section records the migration contract implemented by the integrated v25 foundation. This
accepted-contract correction neither changes nor reruns that migration.

### 5. Freeze phased transaction, filesystem, and idempotency boundaries

Approval request creation, its initial receipt, `APPROVAL_REQUESTED`, and the transition to
`WAITING_APPROVAL` must share one SQLite transaction. Author decision persistence and the receipt
transition to `READY` or `FINALIZED/DISCARDED` must share a transaction with
`APPROVAL_RESOLVED`, whose only fact is that author decision. A rejection may additionally append
`APPROVAL_EXECUTION_FINALIZED(DISCARDED)`, then `RUN_COMPLETED`, and close the run in that same
transaction, but the two approval events retain separate payloads and meanings.

For approved commits, the accepted S2c endpoint is that a short CAS transaction claims
`READY -> EXECUTING`, then the canonical domain SQLite write, durable domain result, receipt
finalization, `APPROVAL_EXECUTION_FINALIZED`, terminal run event(s), and run-row transition share
one project SQLite transaction whenever those writes are in the same database. Repositories
participating in this unit of work must accept the caller-owned connection; nested independent
`connect()` transactions are not an atomic substitute.

That SQLite transaction does not and cannot include canonical Markdown or history-snapshot file
publication. A SQLite commit, rollback, or savepoint does not make filesystem writes atomic. The
exact S2a baseline at `113799cffac44f2e110046042e95dad59c92084d` provides complete projected
preflight, one `BEGIN IMMEDIATE` ChangeSet transaction, and `ChapterFileTransaction` rollback for
ordinary same-process exceptions. It writes history snapshots and canonical Markdown before the
outer SQLite commit and keeps file preimages only in process memory. It is therefore
failure-atomic for handled same-process failures, not process-crash-atomic and not power-loss
atomic. It has no durable filesystem journal and no receipt/event/run finalization.

The implementation phases are strict:

- S2a owns all-operation preflight, caller-owned SQLite transaction close, complete typed results,
  and same-process file compensation;
- S2b adds the metadata-only durable filesystem journal, strengthened project-lock owner identity,
  and project-reopen reconciliation defined below. It does not add or change a receipt, event, run,
  QML surface, migration, or schema;
- S2c later joins canonical domain SQLite result, receipt, execution event, terminal run event, and
  run row in the one project SQLite transaction described above. S2c does not erase the S2b
  filesystem boundary.

A backend facade may instead provide its own durable receipt only when that receipt is written
atomically with the domain mutation and is uniquely queryable by
`approval_request_id + run_id + idempotency_key + kind + commit target identity`. A generated
revision number, current body text, merge side effects, or approximately matching domain state is
not a domain receipt.

Across S2a, S2b, and S2c, a multi-operation ChangeSet must:

1. parse and validate the complete ChangeSet;
2. preflight every intended operation before the first mutation;
3. create and durably register the complete S2b filesystem action plan before the first file
   publication;
4. execute all canonical SQLite operations in one caller-owned transaction while S2b records and
   compensates the corresponding file publications;
5. persist one complete, bounded pre-commit result-evidence set in the S2b journal before attempting
   SQLite commit;
6. in S2c, persist the same complete domain result and terminal receipt/event/run facts in that
   SQLite transaction;
7. roll back the SQLite ChangeSet and compensate every published file action on any pre-commit
   operation failure.

If an existing operation cannot join the shared transaction, H-APPR1b must fail before the first
mutation rather than retain sequential partial execution. Derived indexes and projections may be
refreshed idempotently after the canonical transaction, but their refresh does not decide
`APPLIED`.

SubjectMerge already has a single transaction and a durable
`character_identity_merges` record. H-APPR1b must join receipt finalization to that same transaction
and record the exact merge ID as `domain_receipt_id`. The current merge record alone is
insufficient because it is not bound to the approval/idempotency identity.

The dedicated ProjectConstitution flow is included in this backend contract. Its revision commit
has the same decision-before-commit crash window and must join the v25 receipt/recovery protocol
before it reports an applied result. This inclusion does not add ProjectConstitution controls to
the chapter QML surface. `PROMPT_CHANGE` and `SKILL_CHANGE` have no current V1 commit facade; an
approval request of either kind uses `UNSUPPORTED_APPROVAL`. Approval is
`FAILED/UNSUPPORTED_KIND`, rejection is `DISCARDED`, and neither path calls a backend commit.

### 6. Freeze the H-APPR1b-S2b metadata-only filesystem journal

#### Authority, location, identity, and bounds

S2b accepts Option A: one `changeset-file-journal-v1` JSON journal under
`.ai_pipeline/recovery`. The journal is recovery metadata only. It never becomes a manuscript,
proposal, receipt, event, or retry-tombstone authority. Existing repository history snapshots are
the only file preimages: S2b does not store manuscript bytes in JSON, SQLite blobs, or a second
sidecar manuscript tree.

The journal identity is deterministic:

```text
idempotency_key_digest =
    lowercase_sha256(UTF-8(raw idempotency key))

journal_id =
    lowercase_sha256(
        length-prefixed UTF-8(
            "changeset-file-journal-v1",
            project_id,
            change_set_id,
            idempotency_key_digest
        )
    )
```

Length-prefixing is part of the identity algorithm and prevents concatenation ambiguity. The active
filename is derived only as `<journal_id>.json` under the recovery directory. The journal stores
`idempotency_key_digest`, never the raw idempotency key. Reopening recomputes and validates all
available deterministic identities; an identity mismatch fails closed.

There may be at most one active journal per project. An active journal is capped at 64 KiB of UTF-8
bytes, checked before JSON parsing. It contains at most 50 operations and 100 ordered file actions.
An existing active journal blocks creation of another ChangeSet journal until reconciliation and
cleanup complete.

#### Closed journal DTO

The top-level JSON object has exactly these five fields and rejects duplicate or extra fields:

```text
header
owner
operations
file_actions
pre_commit_result_evidence
```

`header` has exactly:

```text
schema_version             exactly changeset-file-journal-v1
journal_id                 lowercase SHA-256
project_id                 canonical project ID
change_set_id              canonical ChangeSet ID
idempotency_key_digest     lowercase SHA-256
state                      PREPARED | PUBLISHING | DATABASE_READY |
                           RECOVERY_REQUIRED
state_revision             non-negative integer used for journal CAS
recovery_failure_code      null or one closed code
```

The closed `recovery_failure_code` vocabulary is:

```text
OWNER_NOT_PROVABLY_STALE
OWNER_IDENTITY_UNKNOWN
JOURNAL_IDENTITY_MISMATCH
JOURNAL_CORRUPT
JOURNAL_OVERSIZE
JOURNAL_VERSION_UNSUPPORTED
JOURNAL_COUNT_EXCEEDED
QUARANTINE_LIMIT_EXCEEDED
ROOT_CONTAINMENT_FAILED
FILE_STATE_MISMATCH
DATABASE_STATE_AMBIGUOUS
DATABASE_EVIDENCE_INCONSISTENT
COMPENSATION_INCOMPLETE
FILESYSTEM_SHARING_FAILURE
```

`recovery_failure_code` is null in `PREPARED`, `PUBLISHING`, and `DATABASE_READY`, and non-null in
`RECOVERY_REQUIRED`. It contains no free-form detail.

`owner` has exactly:

```text
owner_session_id           random UUIDv4 generated for this writer session
pid                        positive process ID
process_start_identity     lowercase SHA-256 of the platform/PID/native process-start token
```

The process-start digest is domain-separated and excludes executable paths, command lines, user
names, and environment data. These three fields are the journal's immutable owner binding.

The strengthened `ProjectLock` stores those same three immutable fields plus exactly:

```text
heartbeat_sequence         non-negative monotonically increasing integer
heartbeat_at               canonical UTC timestamp
lease_expires_at           canonical UTC timestamp later than heartbeat_at
```

Only `ProjectLock` stores and renews heartbeat/lease state. Its immutable owner fields must match
the journal owner after owner handoff; mutable heartbeat fields never appear in the journal and are
never required to match across two files.

Each ordered `operations` item uses one of three strict variants. The common fields are exactly
`operation_id`, `kind`, `chapter_id`, and non-negative `expected_revision`. `kind` is exactly
`CHAPTER_CONTENT_REPLACE`, `CHAPTER_TITLE_CHANGE`, or `REPAIR_APPLY`.

- `CHAPTER_CONTENT_REPLACE` has only the four common fields.
- `CHAPTER_TITLE_CHANGE` additionally has exactly `effect`, `before_title_hash`, and
  `after_title_hash`. `effect` is `MUTATING | NO_OP`; both hashes are lowercase SHA-256 digests.
  `MUTATING` requires unequal title hashes. `NO_OP` requires equal title hashes. It never stores
  either title.
- `REPAIR_APPLY` additionally has only canonical `proposal_id`. It never stores a proposal,
  selection, replacement, finding, or provenance payload.

Each ordered `file_actions` item has these exact common fields:

```text
action_id                  deterministic lowercase SHA-256 action identity
operation_id               owning operation ID
kind                       HISTORY_SNAPSHOT_CREATE |
                           CANONICAL_CONTENT_REPLACE
chapter_id                 canonical chapter ID
base_revision              non-negative revision before this action
version_id                 canonical existing-history snapshot version ID
state                      REGISTERED | PUBLISHED | COMPENSATED
```

The strict variants are:

- `HISTORY_SNAPSHOT_CREATE` additionally has exactly `before_state=ABSENT` and `after_hash`, the
  lowercase SHA-256 of the exact snapshot bytes. It has no `before_hash`.
- `CANONICAL_CONTENT_REPLACE` additionally has exactly `before_hash` and `after_hash`, both
  lowercase SHA-256 digests. Its `version_id` references the history snapshot that contains the
  `before_hash` preimage.

`action_id` binds the journal ID, list ordinal, all common fields except mutable action `state`, and
every field present in its strict variant using the same length-prefixed hashing rule. Content
replacement and repair use both ordered actions. A `MUTATING` title change uses only the
history-snapshot action; a `NO_OP` title change uses zero file actions. Title identity remains only
in the operation digests above.

No action persists a path. Every snapshot and canonical target is re-derived from validated
`project_id`, `chapter_id`, `base_revision`, `version_id`, action kind, and current repository
layout rules. The implementation must resolve the real project root and repeat root-containment
validation immediately before every create, replace, restore, unlink, quarantine, or journal
operation.

`pre_commit_result_evidence` is null until every intended operation has produced a complete applied
result. When present it has exactly:

```text
schema_version             exactly changeset-pre-commit-result-v1
intended_operation_ids     ordered list exactly equal to operations
outcomes                   ordered list with exactly one item per operation
```

Each outcome has exactly `operation_id`, `kind`, `chapter_id`, `status`, `committed_revision`, and
`committed_content_hash`. `status` is exactly `APPLIED`; revisions are non-negative and hashes are
lowercase SHA-256. Operation-specific final evidence is completed by the matching operation and
file-action metadata: title final state uses the two title digests, and repair final state follows
the canonical `proposal_id` to its finding and provenance relations. A partial, duplicate,
reordered, unknown-kind, non-`APPLIED`, or extra-field result is invalid and cannot reach
`DATABASE_READY`.

For a title `NO_OP`, the outcome must have `committed_revision == expected_revision`; its committed
content hash must be unchanged in the ordered operation chain; and the operation must own zero file
actions. A title `MUTATING` outcome must use the mutating revision/history behavior and exactly one
`HISTORY_SNAPSHOT_CREATE` action. Untyped title equality is invalid.

The journal, every nested object, and every recovery blocking marker use strict UTF-8, strict JSON
object parsing with duplicate-key rejection, closed field sets, closed enums, canonical IDs,
bounded strings/arrays, and stable serialization. They may not contain manuscript or snapshot
bytes, raw title, selected/replacement text, selection patch, ChangeSet/proposal payload, prompt,
provider request/response, raw idempotency key, filesystem path, raw exception, raw OS/SQLite
error, token, credential, or secret.

#### Durable publication protocol and state machine

Every journal rewrite is a whole-document compare-and-swap on the expected `state_revision`.
Writers serialize to a sibling temporary file, flush and sync it, atomically replace the active
journal, and sync the containing directory where the platform supports that operation. A failure
to establish the new durable journal state stops before the next publication. Each successful CAS
increments `state_revision`; each file-action state moves only
`REGISTERED -> PUBLISHED -> COMPENSATED`.

The root state machine is:

```text
PREPARED -> PUBLISHING -> DATABASE_READY -> delete only after SQLite commit
     \            \              \
      +------------+---------------> RECOVERY_REQUIRED
```

The protocol is ordered:

1. While holding the strengthened exclusive project lock, validate the complete ChangeSet,
   operation/action DTOs, caps, deterministic identities, and root containment.
2. Persist the complete `PREPARED` journal with every file action `REGISTERED` before publishing
   any snapshot or canonical file.
3. Begin or continue the S2a caller-owned SQLite transaction and CAS to `PUBLISHING`. Execute
   operations in ChangeSet order; for each operation, publish its registered actions in list order
   and execute its canonical SQLite statements. For content/repair, publish and verify the
   existing-history snapshot before replacing canonical Markdown. After each exact publication,
   CAS its action to `PUBLISHED`.
4. After every intended SQLite operation/result is complete and every file action is published,
   validate the complete result, atomically persist `pre_commit_result_evidence`, and CAS to
   `DATABASE_READY`.
5. Only after `DATABASE_READY` is durable may the owner attempt SQLite commit.
6. After a successful SQLite commit, delete the journal. Failure to replace or unlink on Windows
   sharing semantics retains the last durable journal and is retried by later reconciliation.

`DATABASE_READY` is written before SQLite commit and never proves that commit happened. There is no
state meaning "the database definitely committed"; reopen classification supplies that fact. A
handled same-process exception rolls back SQLite and compensates file actions in reverse order. The
journal is deleted only after compensation completes; otherwise it enters `RECOVERY_REQUIRED` with
`COMPENSATION_INCOMPLETE` or `FILESYSTEM_SHARING_FAILURE`.

All actions are registered before publication. For `HISTORY_SNAPSHOT_CREATE`, an absent derived
target proves unpublished/already-compensated state and is an idempotent no-op; a regular file with
the exact `after_hash` proves published state and may be unlinked during compensation. Any
different bytes, non-regular target, or other pre-existing target is
`RECOVERY_REQUIRED/FILE_STATE_MISMATCH`. For `CANONICAL_CONTENT_REPLACE`, exact `before_hash`
proves unpublished/already-compensated state and exact `after_hash` proves published state; the
published canonical file is restored atomically from its exact history snapshot before that
snapshot is unlinked. Actions are traversed in strict reverse publication order.

A crash may occur after a file publication but before the action-state CAS. Therefore action state
is not used alone: the recovery worker re-derives targets and applies the action-kind-specific
`ABSENT | exact before_hash | exact after_hash` rules above. A crash during compensation is handled
by the same rules, so repeated reopen is idempotent.

#### Owner identity, lock acquisition, and project-open order

The baseline `ProjectLock` records only PID and creation time, and
`ProjectWorkspaceService.open_project` currently opens/migrates before `_set_project` acquires that
lock. S2b must strengthen both boundaries before enabling journal recovery.

The exclusive lock and active journal share only the immutable `owner_session_id`, PID, and
process-start identity. `ProjectLock` is the sole heartbeat/lease liveness authority and renews its
mutable heartbeat sequence/timestamp/expiry through owner-checked CAS while a journal is active.
The journal is not rewritten for heartbeat. Lease expiry is only a liveness hint; it never
authorizes stealing a lock, taking over a journal, or compensating files.

A contender may replace an existing lock only after the previous lock owner is provably stale from
PID plus process-start identity. It must then hold the newly created exclusive project lock before
examining or reconciling a journal, and it must separately prove the journal owner stale before an
owner-handoff CAS changes the journal's immutable three-field owner block. The replacement lock's
immutable owner fields must match the new journal owner after that CAS. PID reuse is not stale proof
unless the live PID's process-start identity is successfully read and differs from the recorded one.
`OpenProcess` access denied, unavailable creation-time identity, malformed identity, transient
query failure, or any unknown result fails closed as `OWNER_IDENTITY_UNKNOWN`; a live matching
process fails as `OWNER_NOT_PROVABLY_STALE`. Release may unlink a lock only when its on-disk
immutable owner identity still matches the releasing session.

The required writer-open order is:

```text
ProjectWorkspaceService
-> resolve and validate the project layout root
-> acquire and validate the strengthened exclusive ProjectLock
-> open ProjectRepository and run migrations
-> scan, validate, and reconcile S2b recovery evidence
-> expose ProjectWorkspaceService / ProjectRuntime writer surfaces
```

Recovery or quarantine failure leaves the workspace unexposed and blocks writer-open. Before
releasing its owner-matched lock, the failing opener must durably preserve the journal/quarantine
and sanitized blocking marker. QML, a direct repository constructor, a background maintenance
worker, and an individual file repository must never initiate or bypass reconciliation.

#### Exact reopen classification and reverse compensation

After owner handoff, recovery reads the database in one consistent snapshot. It evaluates two
complete, disjoint predicates over mutating operations only:

- **complete database pre-state**: every affected chapter is at the first operation's exact
  pre-revision and pre-hash/title digest, none of the journal's `version_id` rows or final
  operation-kind side effects exists, and every repair proposal/finding/provenance relation reached
  through `proposal_id` is in its exact pre-apply state;
- **complete database final-state**: every outcome has its exact committed revision/content hash,
  every journal `version_id` row has the exact chapter/base-revision/hash identity, and every
  operation-kind side effect is complete.

For `CHAPTER_CONTENT_REPLACE`, final evidence includes the exact chapter revision/content hash and
history-version rows. A title `MUTATING` effect additionally hashes the current title and requires
`after_title_hash`; its pre-state requires `before_title_hash`. For `REPAIR_APPLY`, recovery follows
the canonical `proposal_id`. Its pre-state requires a `VALIDATED` proposal whose target
revision/hash matches the chapter, its linked finding in `OPEN`, and no provenance row for that
proposal. Its final-state requires the same proposal to be `APPLIED`, its linked finding to be
`ACCEPTED_REPAIR`, and exactly one matching `REPAIR_APPLIED` provenance row whose source repair,
source finding, chapter, and before/after revisions match the operation and outcome. No message,
payload, current-text similarity, or approximate state may substitute for these checks.

A title `NO_OP` is evaluated separately from the mutating pre/final predicates. Its ordered evidence
must prove `before_title_hash == after_title_hash`, `committed_revision == expected_revision`,
unchanged content hash across adjacent operation evidence, and zero owned file actions. In a mixed
ChangeSet, mutating operations alone select pre-state versus final-state; every NO_OP must still
form an exact unchanged link in the ordered revision/content/title chain.

If a journal contains no mutating operations, complete typed NO_OP evidence plus exact unchanged
current chapter revision/content/title state, zero file actions, and no journal history-version rows
permits filesystem-safe journal cleanup. That cleanup proves only that S2b has no file/domain
mutation to reconcile. It does not manufacture an `APPLIED` approval receipt or terminal retry
result; S2c must finalize or recover the existing v25 receipt without a formal manuscript mutation.

Classification is exact:

- pre-state only -> reverse-compensate all actually published file actions, verify the restored
  pre-state, then delete the journal;
- final-state only -> verify every committed snapshot/canonical file hash, delete the journal, and
  do not replay any domain operation;
- for a ChangeSet with mutating operations, neither, both, or internally inconsistent predicates ->
  retain all evidence, CAS the journal to
  `RECOVERY_REQUIRED` with `DATABASE_STATE_AMBIGUOUS` or
  `DATABASE_EVIDENCE_INCONSISTENT`, persist a sanitized blocking marker, and block writer-open.

SQLite transaction atomicity explains why pre-state or final-state should normally be observable,
but it is supporting evidence, not permission to guess. Recovery must still prove one complete
predicate. It must not infer commit from a higher revision, matching current content, a status
message, an expired lease, or the mere presence of `DATABASE_READY`.

#### Corruption, quarantine, and disclosure

The opener reads no more than 64 KiB plus one sentinel byte before parse. Oversize bytes, invalid
UTF-8, invalid/duplicate-key JSON, non-object roots, unknown schema versions, extra fields, invalid
caps, and identity mismatches are never auto-deleted or partially interpreted. While holding the
exclusive lock, it atomically moves the offending file into a quarantine name derived from a
digest, without logging or copying its raw bytes into another metadata record, and atomically
persists a marker capped at 4 KiB with exactly
`schema_version=changeset-recovery-block-v1`, `project_id`, `recovery_failure_code`,
`offending_name_digest`, and `observed_at`. The name digest is lowercase SHA-256 over a bounded name
identity, never a local path or raw journal bytes; it is null only when no single offending name
exists. The failure code comes from the closed journal recovery vocabulary.

Any quarantine marker blocks writer-open until an explicit repair workflow validates and clears it;
normal open never auto-deletes quarantined evidence. One open scan examines at most one active
journal, 16 quarantined items, and 1 MiB of quarantined bytes in total. A second active journal,
more than 16 quarantine items, or more than 1 MiB becomes the corresponding sanitized blocking
code without scanning additional content.

An atomic quarantine, journal replace, canonical restore, snapshot unlink, or final journal unlink
can fail on Windows because another handle denies sharing. That failure retains the original file
and journal, persists `FILESYSTEM_SHARING_FAILURE` when safely possible, exposes only a sanitized
machine code, and retries on a later locked open. UI and ordinary logs must never include a local
path, raw OS/SQLite error, raw journal bytes, manuscript content, title, or secret.

#### S2b process-crash windows

S2b guarantees reconciliation for an application process crash/restart while the journal exists.
It does not claim controller, drive-cache, kernel, filesystem, or power-loss atomicity.

| Window | Last possible durable state | Required restart behavior |
|---|---|---|
| W0: before durable `PREPARED` | no journal; no file publication permitted | SQLite rolls back; no S2b work |
| W1: `PREPARED`/`PUBLISHING`, before first publication | all actions registered; snapshot targets are `ABSENT` and canonical targets match exact `before_hash` | idempotent action-kind no-op compensation, then delete journal |
| W2: during ordered snapshot/canonical publication | `PUBLISHING`; any prefix may be physically published even if its action CAS lags | classify snapshot `ABSENT|after_hash` and canonical `before_hash|after_hash`, then reverse-compensate the published prefix |
| W3: after all file publication, before durable `DATABASE_READY` | `PUBLISHING`; SQLite transaction cannot survive process exit | prove complete DB pre-state and reverse all file actions |
| W4: after durable `DATABASE_READY`, before or during SQLite commit | journal never proves whether SQLite chose rollback or commit | mutating set: exact pre-state -> compensate, exact final-state -> cleanup, otherwise block; all-NO_OP set: exact unchanged state -> filesystem-safe cleanup only |
| W5: after SQLite commit, before successful journal unlink | complete DB/file final-state and retained journal | verify final evidence, delete journal, never replay |

Registered-but-unpublished actions, partially published actions, partially compensated actions, and
repeated W1-W5 reopen attempts all use the same action-kind-specific state/hash algorithm and remain
idempotent.

While the journal exists, S2b supplies ChangeSet process-crash reconciliation. After its successful
deletion, S2b supplies no terminal client-retry identity. S2c must provide terminal retry
idempotency through the v25 receipt and matching execution/event/run facts. S2b must not equate
`APPROVED` with `APPLIED`, add a terminal retry tombstone, or add receipt, event, run, QML,
migration, schema-v26, or other schema work.

For an all-title-NO_OP ChangeSet, S2b cleanup means only that there was no filesystem or formal
manuscript mutation to compensate or replay. S2c remains responsible for recording and recovering
the typed APPLIED outcome, receipt, event, and run transition for that approved no-op execution.

### 7. Approval crash matrix

| Crash/retry point | Durable evidence | Required recovery | Forbidden result |
|---|---|---|---|
| (a) Before author decision | approval `PENDING`; receipt `PENDING_DECISION`; no `APPROVAL_RESOLVED` | Restore the same approval UI; perform no commit | Applying or discarding automatically |
| (b) Decision persisted, commit not started | approval `APPROVED`; receipt `READY`; `APPROVAL_RESOLVED` contains only decision | CAS-claim and execute once with the same identity | Treating the decision event as terminal or `APPLIED` |
| (c) Commit claimed or in progress | decision event; receipt `EXECUTING`; for ChangeSet, an S2b journal may be `PREPARED`, `PUBLISHING`, or `DATABASE_READY`, including a typed all-title-NO_OP set; no execution-finalized event | Reconcile any S2b journal first, then use exact transaction/domain/NO_OP evidence before S2c retry or finalization | Guessing from current domain state, using untyped equality, or reporting stale because evidence is absent |
| (d) Domain SQLite commit may have completed while filesystem/Harness finalization is incomplete | for a mutating ChangeSet, retained `DATABASE_READY` plus exact pre/final predicates; for all-NO_OP, exact unchanged evidence; after S2c, same-database domain/receipt/event/run facts commit together | Mutating pre-state -> compensate; mutating final-state -> cleanup/no replay; all-NO_OP unchanged -> filesystem-safe cleanup without manufacturing a receipt; then let S2c finalize from durable receipt facts | Calling the gap impossible merely because SQLite is atomic, treating NO_OP cleanup as terminal APPLIED, or repeating ChangeSet/SubjectMerge |
| (e) Receipt finalized, execution event/run stage/UI incomplete | decision event; terminal receipt and possibly domain receipt; any S2b journal has already reconciled; `APPROVAL_EXECUTION_FINALIZED` may be missing only on the explicitly supported external-receipt variant | Idempotently append/finalize execution and run evidence, then rebuild projection | Downgrading/changing disposition or overloading the decision event |
| (f) Client timeout and retry | same approval/idempotency identity and, after S2b cleanup, the S2c terminal receipt | Return the same terminal result, or the same in-progress state until recovery finishes | Treating the S2b journal or its deletion as a terminal retry receipt |
| (g) Migrated `LEGACY_UNRESOLVED/PENDING_DECISION` is decided | migration-only identity and durable author decision | Reject -> `DISCARDED`; approve -> `FAILED/INTEGRITY/MISSING_TARGET_IDENTITY`; finalize without `READY`, `EXECUTING`, or backend call | Inventing target identity, applying, or calling a commit facade |
| (h) `UNSUPPORTED_APPROVAL/PENDING_DECISION` is decided | allowlisted unsupported identity and durable author decision | Reject -> `DISCARDED`; approve -> `FAILED/UNSUPPORTED/UNSUPPORTED_KIND`; finalize without backend call | Treating unsupported as legacy recovery or attempting a commit |

No row in this matrix permits a second formal write, a false `STALE`, or a projection that equates
`APPROVED` with `APPLIED`.

### 8. Recovery algorithm

A resolved approval whose run remains `WAITING_APPROVAL` is a recovery state, never a steady state.
Project-open must complete the S2b lock/journal/quarantine algorithm in §6 before this receipt-level
algorithm can run. An active journal, recovery marker, quarantined item, unknown owner, incomplete
compensation, or ambiguous database classification blocks writer-open and receipt execution; the
approval resolver, QML, and a direct repository call may not recover around it.

After S2b is clear, receipt recovery and an explicit retry use the same S2c algorithm:

1. Load the approval, receipt, run row, and correlated events in one read snapshot.
2. Parse `APPROVAL_RESOLVED` by event schema version. Version 1 requires a boolean `approved` and
   maps it only to author decision; version 2 requires `decision=APPROVED|REJECTED`. Neither version
   supplies disposition. Unknown or malformed versions are retained for diagnostics and fail
   closed for recovery/projection. If a recoverable open run has a durable resolved approval but no
   decision event, recovery appends one schema-version-2 decision event with its stable ID before
   execution; this is a current recovery append, not a migration rewrite or backdated event.
3. Cross-check decision-event evidence with `ApprovalRepository`, validate the stable receipt
   identity tuple, and enforce the commit-target-kind/state matrix. A decision mismatch, illegal
   target kind, illegal transition, or identity mismatch is a typed integrity failure; do not
   commit.
4. If the approval remains `PENDING`, return the same approval projection. This includes
   `LEGACY_UNRESOLVED/PENDING_DECISION`; recovery neither repairs its payload nor hides it.
5. For `LEGACY_UNRESOLVED`, never claim execution and never call a backend facade. `REJECTED`
   CAS-finalizes `DISCARDED`. A newly approved migrated pending row directly finalizes
   `FAILED/INTEGRITY/MISSING_TARGET_IDENTITY`. A pre-v25 `APPROVED/RECOVERY_REQUIRED` row may query
   an exact approval-bound durable domain receipt; if that receipt supplies a complete valid normal
   target identity, CAS-reclassify to that normal target kind and finalize only from its evidence,
   without executing a commit. If it supplies no target, finalize
   `FAILED/INTEGRITY/MISSING_TARGET_IDENTITY`; if it supplies a target but no complete outcome,
   reclassify and finalize `FAILED/MISSING_OUTCOME`. Missing identity alone never maps to `STALE`.
6. For `UNSUPPORTED_APPROVAL`, never claim execution and never call a backend facade. `REJECTED`
   CAS-finalizes `DISCARDED`; `APPROVED` CAS-finalizes
   `FAILED/UNSUPPORTED/UNSUPPORTED_KIND`.
7. For a normal commit-capable target, `REJECTED` verifies or CAS-finalizes `DISCARDED` without a
   backend call.
8. If a normal receipt is `FINALIZED`, validate any existing
   `APPROVAL_EXECUTION_FINALIZED` against it, return the existing disposition, and proceed only to
   idempotent execution-event/run projection finalization.
9. If a normal receipt is `READY`, claim `EXECUTING` by CAS and invoke the backend with the same
   stable identity.
10. If a normal receipt is `EXECUTING` or `RECOVERY_REQUIRED`, query exact domain receipt evidence.
    If it proves the commit, finalize from that result. If it proves a typed conflict before
    mutation, finalize `STALE`. If it proves no mutation and the backend is durably idempotent,
    retry with the same key. If execution evidence is absent or ambiguous, finalize
    `FAILED/MISSING_OUTCOME` without committing again and retain a sanitized manual-audit marker.
11. Validate the complete typed result and finalize exactly one disposition/stage mapping.
12. Append `APPROVAL_EXECUTION_FINALIZED` with its stable event ID, append the mapped run event when
    applicable, update the run row idempotently, and then rebuild QML and other projections from
    durable facts.

A retry of a terminal resolution returns the same typed result. It does not call
`ApprovalService.resolve_approval` again, does not update the author decision timestamp, does not
run the backend commit again, and does not append duplicate events.

S2b journal identity is deliberately insufficient for this terminal retry behavior. Once a
successfully committed journal is deleted, only the S2c v25 receipt plus matching domain,
execution-event, and run evidence may answer a client retry.

`CompletionChecker` must reject `COMPLETED` when any commit-producing approval lacks a terminal
receipt or when disposition and run stage disagree. `CompactionGate` must use receipt execution
state, not either version of `APPROVAL_RESOLVED`, to decide whether a commit may be in flight.
Compaction may still use the decision event or `ApprovalRepository` as author-decision evidence,
but it must not project application from either.

Migration does not manufacture execution history for already-closed legacy runs. If a pre-v25
closed `LEGACY_UNRESOLVED/APPROVED` run has no exact approval-bound domain evidence, compatibility
projection keeps its execution outcome unverified and receipt `RECOVERY_REQUIRED`, surfaces a
manual-audit diagnostic, and never appends a late event or projects `APPLIED`. The fail-closed
`MISSING_TARGET_IDENTITY` / `MISSING_OUTCOME` finalization above applies to recoverable open runs
where the execution event and mapped run transition can still be recorded safely.

### 9. Freeze separate decision and execution events

`APPROVAL_RESOLVED` keeps its existing single meaning: the author decision is durable. It never
means that execution is terminal and never carries `ApprovalDisposition`.

Replay is schema-version aware:

- `APPROVAL_RESOLVED` schema version 1 is the persisted legacy payload
  `{request_id, approved}`. `approved=true` maps only to decision `APPROVED`, and
  `approved=false` maps only to decision `REJECTED`.
- New `APPROVAL_RESOLVED` events use schema version 2 with
  `{request_id, decision}`, where decision is exactly `APPROVED | REJECTED`.
- A schema-version-1 boolean, including `approved=true`, is never terminal evidence and never
  proves `APPLIED`, disposition, commit success, or a run transition.

Execution finalization uses a new independent `RunEventType` allowed by design §63's extensible
"at least" vocabulary:

```text
APPROVAL_EXECUTION_FINALIZED
```

Its schema-version-1 payload contains:

```text
request_id
disposition              APPLIED | DISCARDED | STALE | FAILED
receipt_revision
evidence_refs            bounded allowlisted identities only
failure_class            nullable typed classification
failure_code             nullable bounded machine code
```

It contains no proposal/manuscript payload and does not repeat or replace the author decision. The
event is projection/audit evidence and must exactly match the finalized receipt; the event alone
cannot override a missing or contradictory receipt/domain result.

The causal sequence is:

```text
APPROVAL_REQUESTED
-> APPROVAL_RESOLVED(author decision only)
-> approved: READY -> EXECUTING -> durable domain commit/result
   rejected: no domain commit -> durable DISCARDED receipt
-> APPROVAL_EXECUTION_FINALIZED(disposition)
-> APPLIED/DISCARDED: RUN_COMPLETED
   FAILED: RUN_FAILED
   STALE: the execution-finalized event is the typed stale evidence
-> run row at COMPLETED | FAILED | STALE
-> UI projection
```

All approval events use `correlation_id = approval_request_id`.
`APPROVAL_RESOLVED.causation_id` references `APPROVAL_REQUESTED`;
`APPROVAL_EXECUTION_FINALIZED.causation_id` references `APPROVAL_RESOLVED`; and
`RUN_COMPLETED` / `RUN_FAILED` causation references `APPROVAL_EXECUTION_FINALIZED`.

New decision-event and execution-finalized event IDs are stable and idempotent. The execution event
ID is deterministically derived from the approval request ID, terminal receipt revision, and
disposition (for example with a fixed UUIDv5 namespace), so a recovery retry returns the existing
event rather than appending another. Historical schema-version-1 IDs remain unchanged.

For `APPLIED` and `DISCARDED`, append `APPROVAL_EXECUTION_FINALIZED` and then `RUN_COMPLETED`
before setting the run row to `COMPLETED`. For `FAILED`, append
`APPROVAL_EXECUTION_FINALIZED` and then `RUN_FAILED` before setting the run row to `FAILED`. For
`STALE`, `APPROVAL_EXECUTION_FINALIZED(disposition=STALE,
failure_class=STALE_CONFLICT)` is the generic typed stale evidence; a kind-specific conflict event
may precede it, and the run row then moves to `STALE`.

Rejection may persist the decision, finalize `DISCARDED`, append both approval events in their
causal order, append `RUN_COMPLETED`, and close the run in one transaction. This atomic shortcut
does not collapse the two event types or their meanings.

For an approval, the decision row/receipt transition and `APPROVAL_RESOLVED` share the author
decision transaction. When domain, receipt, execution event, terminal run event, and run row are in
project SQLite, those execution writes share the final commit transaction. A separate "domain
commit first, add the execution event later" sequence is forbidden. On the explicitly supported
domain-owned-receipt variant, recovery may finish Harness execution events and the run row in a
later Harness transaction, but only from the exact durable domain receipt and with the stable event
ID.

The existing `HarnessEventStore` closed-stage rule means
`APPROVAL_EXECUTION_FINALIZED` and terminal run events must be appended before the run row enters
`COMPLETED` or `FAILED`. The finalization API must accept a caller-owned transaction and perform the
event inserts before the stage update; it must not call the current independent append and
transition methods as separate commits.

Recovery, Compaction, and Projection must parse events by type and schema version. They may use
legacy `APPROVAL_RESOLVED` only to corroborate `ApprovalRepository` decision. Terminal execution
truth comes from matching receipt/domain evidence plus
`APPROVAL_EXECUTION_FINALIZED` and mapped terminal run facts. Unknown versions, boolean-only
decision events without receipts, or cross-source disagreement fail closed and never project
`APPLIED`.

For migrated approvals on an already-closed legacy run, the absence of
`APPROVAL_EXECUTION_FINALIZED` is an explicit compatibility gap because migration may neither
rewrite history nor append through a closed EventStore. A legacy `REJECTED` decision may project
`DISCARDED` only when its finalized receipt and existing `COMPLETED` run fact agree. A legacy
`APPROVED` decision without exact approval-bound domain evidence remains unverified and never
projects `APPLIED`.

### 10. Limit H-APPR1a to the QML boundary

After the durable backend contract exists, H-APPR1a may make only the live typed-mapping and QML
correctness changes:

- `HarnessAgentPort.resolve_approval` returns a typed execution result containing decision,
  disposition, run stage, receipt identity/revision, and bounded safe failure data;
- `HarnessAgentCoordinator` forwards that result rather than returning `None`;
- `HarnessAgentTimelineController` derives state and text from `ApprovalDisposition`;
- `MockNovelStudioFacade` reloads the chapter and emits editor refresh signals only for `APPLIED`;
- `DISCARDED` performs no formal write and does not reload as if content changed;
- `STALE` and `FAILED` preserve the current editor content and must not display "already applied".

H-APPR1a does not implement H-STATUS1's complete Harness projection or redesign every status
surface. QML must not synthesize a terminal disposition from an approval boolean, local card state,
message text, timers, or the presence of changed domain content.

### 11. Tighten the implementation order

The current S2a ChangeSet flow has neither a durable filesystem journal nor end-to-end S2c terminal
receipt wiring. The v25 foundation alone cannot distinguish every post-file-publication crash
window or answer a terminal client retry. Therefore this accepted-contract correction freezes the
executable order:

```text
H-APPR1b-S2a (same-process failure-atomic ChangeSet UoW; integrated baseline)
-> H-APPR-S2b-D0 (this one-document accepted-contract correction)
-> integrate D0 and establish a new exact S2b baseline
-> H-APPR1b-S2b (metadata-only journal, owner/lock, reopen reconciliation)
-> H-APPR1b-S2c (v25 receipt/event/run same-SQLite-transaction wiring)
-> H-APPR1a
-> H-UNIFY1
```

After the D0 correction is committed and integrated, the S2b implementation branch must be
rebased or fast-forwarded to the new exact integrated baseline and reverified clean before any S2b
edit. It must not continue from `113799cffac44f2e110046042e95dad59c92084d` as though this
correction were already present.

Within S2b, the implementation order is exact:

1. strengthen `ProjectLock` owner identity, stale proof, owner-checked release, and heartbeat/lease;
2. move `ProjectWorkspaceService` writer-open lock acquisition before repository open/migration;
3. implement strict journal DTO/store, caps, root containment, quarantine, and blocking marker;
4. integrate all-action durable registration and ordered publication with
   `ChapterFileTransaction` / ChangeSet UoW;
5. implement exact project-reopen pre/final classification and reverse compensation before
   workspace exposure;
6. add focused process-crash/reopen, owner/PID-reuse, corruption/quarantine, Windows sharing, and
   repeated-reopen regression tests and pass final documentation/code gates.

Only after S2b is integrated may S2c add the v25 receipt/event/run transaction wiring. H-APPR1a
then wires the typed result into the Port/Controller/Facade without schema work. Neither H-UNIFY1
nor H-STATUS1 may be mixed into these tickets, and H-UNIFY1 cannot begin until the approval slices
are accepted and verified.

## Authoritative existing entrypoints

Implementations extend these authorities rather than introducing parallel approval or domain
systems:

- `harness.approval_service.ApprovalService` and
  `harness.approval_repository.ApprovalRepository` own author decision lifecycle;
- `harness.approval_resolver.ApprovalResolver` owns decision-to-commit coordination for ChangeSet
  and SubjectMerge;
- `application.changeset_service.ChangeSetService` and its typed operation outcomes own ChangeSet
  validation and commit results;
- `application.project_workspace_service.ProjectWorkspaceService` owns the writer-open sequence and
  must not expose a workspace before locked S2b reconciliation succeeds;
- `infrastructure.storage.project_lock.ProjectLock` owns exclusive writer identity, stale-owner
  proof, and owner-checked release;
- `infrastructure.storage.chapter_repository.ChapterFileTransaction` remains the same-process
  compensation boundary and is extended by S2b rather than replaced; `ChapterRepository` and its
  existing `.ai_pipeline/history` snapshot rules remain the sole file-preimage authority;
- `application.subject_merge_service.SubjectMergeService` and the existing
  `character_identity_merges` record own SubjectMerge domain commit evidence;
- `harness.constitution_flow.ConstitutionFlowService` and the stable backend constitution service
  own the dedicated ProjectConstitution flow and are included in receipt semantics;
- `harness.run_engine.HarnessRunEngine`, `harness.event_store.HarnessEventStore`,
  `harness.event_repository.HarnessEventRepository`, `harness.run_state.RunStage`,
  `harness.completion_check.CompletionChecker`, and `harness.compaction.CompactionGate` own run
  lifecycle, recovery gates, and event truth;
- `ui_qml.bridge.harness_agent_bridge.HarnessAgentPort`,
  `HarnessAgentCoordinator`, `HarnessAgentTimelineController`, and
  `ui_qml.bridge.mock_novel_studio_facade.MockNovelStudioFacade` remain command/projection
  adapters, not commit authorities.

## Prohibited patterns

- Adding only a `RunStage` transition is insufficient because it cannot prove the author decision,
  domain target, operation completeness, or idempotent commit identity.
- Treating `approved` as `applied` is forbidden.
- Adding disposition or execution evidence to `APPROVAL_RESOLVED` is forbidden; it is a
  decision-only event.
- Treating a legacy schema-version-1 `APPROVAL_RESOLVED {approved:true}` as terminal or `APPLIED`
  is forbidden.
- Rewriting, resequencing, deleting, or reinterpreting historical append-only events during v25
  migration/backfill is forbidden.
- Aborting the entire v25 migration because one legacy approval payload is empty, malformed,
  JSON-null, or unknown is forbidden.
- Inventing a target ID, deriving one from raw payload, or copying raw payload into
  `LEGACY_UNRESOLVED` evidence is forbidden.
- Using `LEGACY_UNRESOLVED` for a fresh v25 request is forbidden.
- Moving `LEGACY_UNRESOLVED` or `UNSUPPORTED_APPROVAL` into `READY` or `EXECUTING` is forbidden;
  neither kind may call a backend commit.
- Projecting `LEGACY_UNRESOLVED` as `APPLIED` or guessing `STALE` from its missing identity is
  forbidden.
- Parsing error messages, translated text, or exception strings to infer `STALE` is forbidden.
- Committing and then independently adding events or receipts is forbidden.
- Comparing current manuscript/domain state to guess that an operation was previously applied is
  forbidden.
- Calling filesystem publication part of a SQLite transaction, calling S2a crash-atomic, or calling
  S2b power-loss atomic is forbidden.
- Publishing any history/canonical file before the complete S2b action plan is durable is
  forbidden.
- Recovering from an active or quarantined journal without the strengthened exclusive project lock
  and provably stale prior owner is forbidden.
- Mirroring mutable heartbeat/lease fields into the journal or requiring cross-file heartbeat
  equality is forbidden; `ProjectLock` is the sole liveness authority.
- Treating lease expiry, PID absence inferred from `OpenProcess` failure, a reused PID, message
  text, or approximate current state as recovery authority is forbidden.
- Treating equal title text as an untyped mutation or letting a typed title NO_OP contribute to the
  mutating pre/final predicate is forbidden.
- Giving `HISTORY_SNAPSHOT_CREATE` a synthetic `before_hash` is forbidden; its only pre-state is
  `ABSENT`.
- Persisting manuscript/snapshot bytes, raw title, selection/replacement/proposal payload, raw
  idempotency key, path, prompt, provider data, raw exception, OS/SQLite error, credential, or
  secret in the S2b journal or blocking marker is forbidden.
- Adding a SQLite manuscript blob authority, sidecar manuscript copy/pointer-flip protocol,
  terminal retry tombstone, migration, schema v26, receipt, event, run, or QML change in S2b is
  forbidden.
- Opening or migrating a writer workspace before exclusive lock acquisition, or allowing QML/direct
  repositories to reconcile recovery evidence, is forbidden.
- Re-running a ChangeSet because a previous response was lost is forbidden unless the same durable
  identity and domain receipt protocol proves the retry is idempotent.
- Copying the complete ChangeSet, selection patch, ProjectConstitution proposal, manuscript, path,
  provider payload, prompt, exception, or secret into the receipt is forbidden.
- Constructing disposition directly in QML is forbidden.
- Mixing H-UNIFY1 orchestration or H-STATUS1 full projections into H-APPR1a/H-APPR1b is forbidden.

## Machine-searchable contract assertions

- [H-APPR-D0-001] Author decision, deterministic commit outcome, RunStage, and ApprovalDisposition
  MUST remain four separate facts.
- [H-APPR-D0-002] ApprovalDisposition MUST be exactly APPLIED, DISCARDED, STALE, or FAILED.
- [H-APPR-D0-003] ApprovalDisposition MUST NOT be represented by ApprovalStatus.
- [H-APPR-D0-004] ApprovalDisposition MUST NOT introduce a new RunStage.
- [H-APPR-D0-005] APPROVED plus every intended durable APPLIED outcome MUST map to
  COMPLETED/APPLIED.
- [H-APPR-D0-006] APPROVED plus a typed revision, hash, or patch-replay conflict MUST map to
  STALE/STALE.
- [H-APPR-D0-007] APPROVED plus validation, persistence, partial, missing, unsupported, or integrity
  failure MUST map to FAILED/FAILED.
- [H-APPR-D0-008] REJECTED MUST perform no formal commit and MUST map to COMPLETED/DISCARDED.
- [H-APPR-D0-009] READY, FAILED, partial, duplicate, or missing operation outcomes MUST NOT map to
  APPLIED.
- [H-APPR-D0-010] Failure messages and exception strings MUST NOT determine stale classification.
- [H-APPR-D0-011] H-APPR1b MUST add an independent one-to-one execution receipt table.
- [H-APPR-D0-012] Every receipt MUST bind approval_request_id, run_id, idempotency_key, and kind.
- [H-APPR-D0-013] Every receipt MUST preserve the author decision separately from execution state.
- [H-APPR-D0-014] Only a FINALIZED receipt MAY carry an ApprovalDisposition.
- [H-APPR-D0-015] Every receipt MUST contain validated, bounded commit target identity and result
  evidence.
- [H-APPR-D0-016] A receipt MUST NOT contain manuscript text, complete selection/proposal payload,
  filesystem path, raw provider payload, credential, or secret.
- [H-APPR-D0-017] Receipt failure data MUST use typed codes and a bounded sanitized summary.
- [H-APPR-D0-018] Every receipt transition MUST use timestamps, revision, and compare-and-swap.
- [H-APPR-D0-019] The verified current schema version for this decision MUST be v24.
- [H-APPR-D0-020] H-APPR1b MUST be the exclusive owner of schema v25.
- [H-APPR-D0-021] The v25 upgrade MUST be transactional, verifiable, and fail back to v24 on error.
- [H-APPR-D0-022] Pre-v25 APPROVED approvals MUST enter RECOVERY_REQUIRED and MUST NOT be guessed
  APPLIED.
- [H-APPR-D0-023] Multi-operation ChangeSet preflight MUST finish before its first canonical write.
- [H-APPR-D0-024] Multi-operation ChangeSet writes and terminal receipt MUST share one transaction
  or fail before mutation.
- [H-APPR-D0-025] SubjectMerge MUST bind the exact merge record to the Harness receipt in the same
  transaction.
- [H-APPR-D0-026] A backend-owned receipt is acceptable only when it is atomic with the domain write
  and queryable by the full approval identity.
- [H-APPR-D0-027] Crash point (a), before decision, MUST restore the same pending approval without a
  commit.
- [H-APPR-D0-028] Crash point (b), after decision and before commit, MUST resume from READY without
  treating APPROVED as APPLIED.
- [H-APPR-D0-029] Crash point (c), during execution, MUST reconcile exact transactional/domain
  evidence before retry.
- [H-APPR-D0-030] Crash point (d), after domain commit, MUST finalize from exact domain evidence and
  MUST NOT repeat the formal write.
- [H-APPR-D0-031] Crash point (e), after receipt finalization, MUST idempotently finalize events,
  run row, and UI projection.
- [H-APPR-D0-032] Crash point (f), client timeout retry, MUST return the same terminal or in-progress
  result for the same identity.
- [H-APPR-D0-033] A resolved approval with WAITING_APPROVAL MUST be treated as recovery work, not a
  steady state.
- [H-APPR-D0-034] A retry of a terminal resolution MUST return the same disposition.
- [H-APPR-D0-035] A retry MUST NOT resolve the author decision or execute the domain commit twice.
- [H-APPR-D0-036] APPROVAL_RESOLVED MUST remain an author-decision-only event and MUST NOT carry
  disposition.
- [H-APPR-D0-037] Legacy schema-version-1 APPROVAL_RESOLVED approved booleans MUST be interpreted
  only as author-decision evidence and MUST NOT prove a terminal result.
- [H-APPR-D0-038] New APPROVAL_RESOLVED events MUST use an explicit APPROVED or REJECTED decision
  payload under a new event schema version.
- [H-APPR-D0-039] APPROVAL_EXECUTION_FINALIZED MUST be the independent typed event for disposition,
  receipt revision, bounded evidence references, and typed failure.
- [H-APPR-D0-040] APPROVAL_EXECUTION_FINALIZED event IDs MUST be stable and idempotent per terminal
  approval receipt.
- [H-APPR-D0-041] The v25 migration/backfill MUST NOT rewrite, reinterpret, resequence, delete, or
  synthesize append-only historical events.
- [H-APPR-D0-042] Recovery, Compaction, and Projection MUST parse approval events by type and schema
  version and MUST fail closed on unknown or contradictory evidence.
- [H-APPR-D0-043] APPROVAL_RESOLVED decision evidence MUST precede approved domain execution and
  APPROVAL_EXECUTION_FINALIZED.
- [H-APPR-D0-044] A rejected decision MAY finalize DISCARDED in the same transaction but MUST emit
  separate decision and execution-finalized events in causal order.
- [H-APPR-D0-045] APPROVAL_EXECUTION_FINALIZED MUST precede the mapped RUN_COMPLETED or RUN_FAILED
  event or the RunStage.STALE transition, and all required events MUST precede a closed run row.
- [H-APPR-D0-046] QML MUST consume a typed ApprovalDisposition returned by the Harness boundary.
- [H-APPR-D0-047] The Facade MUST reload formal chapter content only for APPLIED.
- [H-APPR-D0-048] DISCARDED MUST preserve formal content and MUST NOT trigger an applied reload.
- [H-APPR-D0-049] STALE and FAILED MUST NOT display an applied state or applied message.
- [H-APPR-D0-050] H-APPR1a MUST NOT implement the H-STATUS1 full projection.
- [H-APPR-D0-051] H-APPR1b MUST land before H-APPR1a live wiring is enabled.
- [H-APPR-D0-052] H-UNIFY1 MUST wait for verified H-APPR1b and H-APPR1a completion.
- [H-APPR-D0-053] ProjectConstitution commits MUST participate in the durable receipt and recovery
  contract.
- [H-APPR-D0-054] ProjectConstitution inclusion MUST NOT add a new chapter-QML approval surface.
- [H-APPR-D0-055] Unsupported PROMPT_CHANGE or SKILL_CHANGE commits MUST map to FAILED, never
  APPLIED.
- [H-APPR-D0-056] Current domain state or approximate content equality MUST NOT prove prior
  application.
- [H-APPR-D0-057] CompletionChecker MUST reject a completed run with a non-terminal or mismatched
  execution receipt.
- [H-APPR-D0-058] CompactionGate MUST use receipt execution state rather than an approved event
  boolean.
- [H-APPR-D0-059] commit_target_kind MUST distinguish CHANGESET, SUBJECT_MERGE,
  PROJECT_CONSTITUTION, UNSUPPORTED_APPROVAL, and LEGACY_UNRESOLVED.
- [H-APPR-D0-060] LEGACY_UNRESOLVED MUST be accepted only as v25 migration provenance for an
  existing row whose normal target identity cannot be fully validated.
- [H-APPR-D0-061] A LEGACY_UNRESOLVED receipt MUST use approval_request_id as commit_target_id and
  MUST store only the fixed legacy-unresolved-v1 identity DTO and typed reason code.
- [H-APPR-D0-062] LEGACY_UNRESOLVED MUST NOT copy, hash, or otherwise derive evidence from raw
  approval payload, manuscript, selection/proposal content, path, or exception data.
- [H-APPR-D0-063] LEGACY_UNRESOLVED MUST NEVER enter READY or EXECUTING and MUST NEVER call a
  backend commit facade.
- [H-APPR-D0-064] LEGACY_UNRESOLVED itself MUST NEVER become APPLIED or map missing identity to
  STALE.
- [H-APPR-D0-065] Rejecting a migrated LEGACY_UNRESOLVED pending approval MUST finalize
  DISCARDED with no formal write.
- [H-APPR-D0-066] Approving a migrated LEGACY_UNRESOLVED pending approval MUST finalize
  FAILED/INTEGRITY/MISSING_TARGET_IDENTITY with no formal write.
- [H-APPR-D0-067] A legacy approved unresolved receipt MAY reconcile only from an exact
  approval-bound domain receipt and MUST reclassify to a validated normal target kind before any
  evidence-backed APPLIED or STALE disposition.
- [H-APPR-D0-068] A legacy approved unresolved receipt without exact target evidence MUST fail
  closed with MISSING_TARGET_IDENTITY or MISSING_OUTCOME and MUST NOT retry a commit.
- [H-APPR-D0-069] UNSUPPORTED_APPROVAL MUST use approval_request_id as commit_target_id and only the
  fixed unsupported-approval-v1 identity DTO.
- [H-APPR-D0-070] Approving UNSUPPORTED_APPROVAL MUST finalize FAILED/UNSUPPORTED/UNSUPPORTED_KIND;
  rejecting it MUST finalize DISCARDED; neither path may call a backend commit.
- [H-APPR-D0-071] Migration MUST use a normal legacy target kind only after the complete
  kind-specific identity validates and MUST degrade a single invalid row to LEGACY_UNRESOLVED
  without aborting the project upgrade.
- [H-APPR-D0-072] Fresh v25 commit-capable approvals MUST NOT use LEGACY_UNRESOLVED and MUST fail
  before persistence when normal target identity is invalid or missing.
- [H-APPR-D0-073] Receipt table constraints, receipt DTO validation, and repository transitions
  MUST enforce the same target-kind/state/decision/disposition/failure matrix.
- [H-APPR-D0-074] Migration/backfill tests MUST cover empty, JSON-null, malformed, unknown, valid,
  unsupported, approve/reject, fresh-fallback rejection, and raw-payload non-disclosure cases.
- [H-APPR-D0-075] The exact S2a baseline MUST be described as same-process failure-atomic and MUST
  NOT be described as process-crash atomic, controller/power-loss atomic, or
  filesystem/SQLite-atomic.
- [H-APPR-D0-076] Filesystem publication MUST remain outside SQLite transaction atomicity; S2c MUST
  still place domain result, receipt, execution event, terminal run event, and run row in one
  project SQLite transaction.
- [H-APPR-D0-077] S2b MUST use one metadata-only `changeset-file-journal-v1` journal under
  `.ai_pipeline/recovery` and MUST reuse existing history snapshots as file preimages.
- [H-APPR-D0-078] `journal_id` MUST deterministically bind schema version, project_id,
  change_set_id, and lowercase SHA-256 of the idempotency key using length-prefixed encoding; the
  journal MUST NOT store the raw key.
- [H-APPR-D0-079] The journal root MUST contain exactly header, owner, operations, file_actions, and
  pre_commit_result_evidence; duplicate and extra fields MUST be rejected at every level.
- [H-APPR-D0-080] Journal header states, recovery failure codes, and state_revision CAS MUST use
  only the closed vocabularies and transitions frozen in §6.
- [H-APPR-D0-081] Journal state MUST progress PREPARED -> PUBLISHING -> DATABASE_READY ->
  delete-after-commit, with failures entering RECOVERY_REQUIRED; DATABASE_READY MUST be durable
  before SQLite commit and MUST NOT prove commit.
- [H-APPR-D0-082] Journal operations MUST be ordered, capped at 50, and limited to
  CHAPTER_CONTENT_REPLACE, CHAPTER_TITLE_CHANGE, and REPAIR_APPLY.
- [H-APPR-D0-083] Every journal operation MUST bind exactly operation_id, kind, chapter_id, and
  expected_revision as its common identity.
- [H-APPR-D0-084] A title operation MUST add exactly MUTATING|NO_OP effect plus lowercase
  before/after title SHA-256 digests, and a repair operation MUST add only canonical proposal_id;
  neither MAY persist raw title or payload.
- [H-APPR-D0-085] File actions MUST be ordered, capped at 100, and bind the closed common fields
  action_id, operation_id, kind, chapter_id, base_revision, history version_id, and action state plus
  only their action-kind strict variant.
- [H-APPR-D0-086] Journal and file paths MUST be derived from validated IDs plus repository rules,
  MUST NOT be persisted, and MUST pass renewed real-root containment before every filesystem action.
- [H-APPR-D0-087] The complete file-action plan MUST be durable with every action REGISTERED before
  the first history or canonical publication.
- [H-APPR-D0-088] HISTORY_SNAPSHOT_CREATE MUST bind `before_state=ABSENT` plus after_hash and no
  before_hash; CANONICAL_CONTENT_REPLACE MUST bind before_hash plus after_hash and reference that
  history version_id.
- [H-APPR-D0-089] Action updates MUST use whole-journal CAS and the closed
  REGISTERED -> PUBLISHED -> COMPENSATED lifecycle; a provably unpublished registered action MUST
  be an idempotent compensation no-op.
- [H-APPR-D0-090] Published file actions MUST be compensated in strict reverse order from the exact
  existing-history preimage, with hash verification before restore or unlink.
- [H-APPR-D0-091] Pre-commit result evidence MUST contain exactly one ordered APPLIED outcome for
  every intended operation and MUST reject partial, duplicate, reordered, unknown, or extra data.
- [H-APPR-D0-092] The journal and blocking marker MUST NOT contain manuscript/snapshot bytes, raw
  title, selection/replacement/proposal payload, prompt, path, provider data, raw key, raw
  exception/error, credential, token, or secret.
- [H-APPR-D0-093] S2b MUST allow at most one active journal per project, at most 64 KiB per active
  journal, at most 50 operations, and at most 100 file actions.
- [H-APPR-D0-094] W0 before durable PREPARED MUST permit no file publication and MUST require no S2b
  replay after SQLite rollback.
- [H-APPR-D0-095] W1 before first publication MUST require snapshot ABSENT and canonical
  before_hash states, then treat the registered action set as idempotent no-op compensation.
- [H-APPR-D0-096] W2 during publication MUST classify snapshot ABSENT|after_hash and canonical
  before_hash|after_hash even when action-state CAS lags, then reverse-compensate the published
  prefix.
- [H-APPR-D0-097] W3 after file publication but before DATABASE_READY MUST prove complete database
  pre-state and reverse all published file actions.
- [H-APPR-D0-098] W4 after DATABASE_READY but before/during SQLite commit MUST classify exact
  mutating pre-state versus final-state, or exact all-NO_OP unchanged state, and MUST NOT infer
  commit from journal state.
- [H-APPR-D0-099] W5 after SQLite commit but before journal unlink MUST verify complete final
  database/file evidence, delete the journal, and MUST NOT replay a domain operation.
- [H-APPR-D0-100] Complete database pre-state alone MUST cause exact reverse file compensation,
  restored-pre-state verification, and journal cleanup.
- [H-APPR-D0-101] Complete database final-state alone MUST cause exact committed-file verification
  and journal cleanup without domain replay.
- [H-APPR-D0-102] For a ChangeSet with mutating operations, neither, both, or inconsistent
  mutating pre/final predicates MUST retain evidence, enter RECOVERY_REQUIRED with a closed code,
  persist a sanitized marker, and block writer-open.
- [H-APPR-D0-103] Content and MUTATING-title final-state checks MUST verify exact revisions,
  content/history hashes, and for title the declared lowercase after-title digest.
- [H-APPR-D0-104] Repair final-state checks MUST follow proposal_id and verify APPLIED proposal,
  ACCEPTED_REPAIR finding, and exactly one matching REPAIR_APPLIED provenance relation.
- [H-APPR-D0-105] SQLite transaction atomicity MAY support expected pre/final classification but
  MUST NOT replace complete operation-kind evidence or authorize approximate-state inference.
- [H-APPR-D0-106] Journal owner and strengthened ProjectLock MUST bind the same immutable random
  session ID, PID, and process-start identity; journal owner MUST contain no heartbeat or lease.
- [H-APPR-D0-107] ProjectLock alone MUST store and owner-CAS update heartbeat sequence/time and
  lease expiry; mutable liveness fields MUST NOT be mirrored or equality-checked across two files,
  and lease expiry alone MUST NOT authorize takeover.
- [H-APPR-D0-108] Reconciliation MUST begin only after the new process holds the strengthened
  exclusive project lock with its immutable owner identity and separately proves the prior journal
  owner stale.
- [H-APPR-D0-109] PID reuse, Windows OpenProcess access denied, unavailable process-start identity,
  malformed identity, or unknown liveness MUST fail closed rather than prove staleness.
- [H-APPR-D0-110] Journal owner handoff MUST CAS only its immutable three-field owner block after
  stale proof, and lock release MUST unlink only an on-disk immutable owner identity matching the
  releasing session.
- [H-APPR-D0-111] Writer open MUST order layout/root validation -> exclusive lock ->
  open/migrate -> journal reconciliation -> workspace/runtime exposure.
- [H-APPR-D0-112] Recovery/quarantine failure MUST block writer-open; QML, direct repositories, and
  background maintenance MUST NOT initiate or bypass reconciliation.
- [H-APPR-D0-113] The opener MUST enforce the 64 KiB byte cap before parse and reject invalid UTF-8,
  duplicate-key/invalid JSON, unknown versions, extra fields, invalid caps, and identity mismatch.
- [H-APPR-D0-114] Corrupt, oversize, or unknown-version evidence MUST be atomically quarantined with
  a persistent sanitized blocking marker and MUST NOT be logged raw or auto-deleted.
- [H-APPR-D0-115] One open scan MUST examine at most one active journal, 16 quarantine items, and
  1 MiB of quarantine bytes; any excess MUST block without scanning more content.
- [H-APPR-D0-116] Windows replace/unlink sharing failure MUST retain the journal/evidence, expose
  only a closed code, block the current writer-open, and permit a later locked retry.
- [H-APPR-D0-117] Partial publication, partial compensation, and repeated reopen MUST remain
  idempotent through action state, derived paths, snapshot ABSENT|after_hash, canonical
  before_hash|after_hash, and reverse ordering.
- [H-APPR-D0-118] UI and ordinary logs MUST NOT expose raw journal bytes, manuscript/title data,
  local paths, raw OS/SQLite errors, provider data, credentials, tokens, or secrets.
- [H-APPR-D0-119] S2b MUST guarantee application process-crash/restart reconciliation only and MUST
  NOT claim controller, drive-cache, kernel, filesystem, or power-loss atomicity.
- [H-APPR-D0-120] While a journal exists S2b MUST reconcile ChangeSet crash state; after journal
  deletion terminal client-retry idempotency MUST come only from the S2c v25 receipt.
- [H-APPR-D0-121] S2b MUST NOT treat APPROVED as APPLIED and MUST NOT add receipt, event, run, QML,
  migration, schema, or terminal retry-tombstone state.
- [H-APPR-D0-122] S2b MUST NOT introduce SQLite manuscript blobs, sidecar manuscript
  copies/pointer flips, or another manuscript/preimage authority.
- [H-APPR-D0-123] Same-process compensation without a durable journal, message inference, and
  approximate current-state inference MUST NOT be accepted as process-crash recovery.
- [H-APPR-D0-124] Lease-only stealing and journal storage of payload, path, raw title, body, raw key,
  exception, provider data, credential, or secret MUST remain rejected.
- [H-APPR-D0-125] S2b MUST NOT add schema v26, any migration/schema change, or a terminal retry
  tombstone; those are outside the accepted slice.
- [H-APPR-D0-126] H-APPR-S2b-D0 MUST keep Status Accepted and modify only this existing ADR 0025;
  it MUST NOT modify ADR 0024, Board, source, test, migration/schema, QML, or any second file.
- [H-APPR-D0-127] A later S2b readiness proposal MUST cap production scope at six files and test
  scope at five files; any extra file or schema work MUST be reported as SCOPE_CHANGE before edit.
- [H-APPR-D0-128] After D0 commit/integration, the S2b branch MUST rebase or fast-forward to the new
  exact integrated baseline and reverify branch/HEAD/clean state before editing.
- [H-APPR-D0-129] S2b implementation MUST first strengthen ProjectLock owner/stale/release/heartbeat
  semantics and then move ProjectWorkspaceService lock acquisition before open/migrate.
- [H-APPR-D0-130] S2b implementation MUST next add the strict journal store, caps, containment,
  quarantine, and blocking marker before integrating file publication.
- [H-APPR-D0-131] S2b implementation MUST next integrate durable action registration/publication,
  then locked reopen classification/compensation, then the bounded crash/owner/quarantine/sharing
  regression suite.
- [H-APPR-D0-132] S2c receipt/event/run same-SQLite-transaction wiring MUST begin only after S2b is
  integrated and verified; S2c MUST NOT claim that its SQLite transaction includes files.
- [H-APPR-D0-133] CHAPTER_TITLE_CHANGE effect MUST be exactly MUTATING or NO_OP; MUTATING MUST have
  unequal title digests and one snapshot action, while NO_OP MUST have equal title digests and zero
  file actions.
- [H-APPR-D0-134] A title NO_OP outcome MUST have committed_revision equal expected_revision and
  MUST preserve the exact content hash in the ordered operation chain.
- [H-APPR-D0-135] In a mixed ChangeSet, only mutating operations MUST select database pre-state
  versus final-state; each NO_OP MUST remain an exact unchanged link in the ordered evidence.
- [H-APPR-D0-136] An all-NO_OP journal MAY be filesystem-safely cleaned only from exact unchanged
  chapter state, complete typed NO_OP evidence, zero actions, and no journal history rows.
- [H-APPR-D0-137] All-NO_OP S2b cleanup MUST NOT manufacture APPLIED or terminal retry evidence;
  S2c MUST finalize/recover the v25 receipt without a formal manuscript mutation.
- [H-APPR-D0-138] A snapshot target that is neither ABSENT nor a regular file with exact after_hash
  MUST become FILE_STATE_MISMATCH; snapshot actions MUST NOT persist a synthetic before_hash.

## Alternatives Considered

### Add execution columns to `harness_approvals`

Rejected. It is fewer SQL objects but erases the architectural separation between author intent and
backend execution, creates a sparse mixed-lifecycle row, and makes rollback and invariants harder.

### Add only a terminal `RunStage`

Rejected. A stage does not prove operation completeness, target identity, or whether retrying the
domain write is safe.

### Treat `APPROVED` as `APPLIED`

Rejected. The author decision is persisted before stale detection and before a backend write can
fail.

### Put disposition into `APPROVAL_RESOLVED`

Rejected. The event already has persisted schema-version-1 history and a stable meaning: durable
author decision. Overloading it would collapse decision and execution facts and make legacy replay
interpret `approved=true` as a terminal result. A new `APPROVAL_EXECUTION_FINALIZED` event preserves
both semantics.

### Rewrite historical decision events during v25 migration

Rejected. Append-only event identity, sequence, schema version, and payload are audit evidence.
Migration extends the accepted event vocabulary and backfills receipt rows, but never edits old
events or fabricates backdated execution events.

### Fail the whole upgrade on one malformed legacy approval

Rejected. Historical v22 payloads were not constrained to a kind-specific receipt identity.
Failing the project migration would make unrelated valid data hostage to one dirty row. Migration
creates a minimal `LEGACY_UNRESOLVED` receipt for that row and continues atomically.

### Invent or derive a legacy target identity

Rejected. Approval request ID, current domain state, payload hash, message text, or a partial DTO
cannot prove the intended commit target. `LEGACY_UNRESOLVED` records only the approval identity,
original ApprovalKind, and typed missing-identity reason without copying raw payload.

### Use `LEGACY_UNRESOLVED` for new invalid proposals

Rejected. It would turn migration compatibility into a permanent validation bypass. Fresh v25
commit-capable proposals fail before persistence unless their normal kind-specific target identity
fully validates.

### Route unsupported kinds through recovery or a backend

Rejected. `PROMPT_CHANGE` and `SKILL_CHANGE` have no V1 commit facade. Their explicit
`UNSUPPORTED_APPROVAL` identity deterministically produces `DISCARDED` on reject or
`FAILED/UNSUPPORTED_KIND` on approve without execution.

### Infer stale from an error message

Rejected. Messages are lossy, localized, sanitized, and unstable. Stale is a typed backend fact.

### Commit first, then write the receipt and event

Rejected as independent commits. It creates the exact crash gap this ADR closes. Statements may be
ordered inside one SQLite transaction, but domain mutation, receipt, event evidence, and run row
must become visible atomically. The backend-owned-receipt exception still requires exact durable
evidence before Harness finalization.

### Infer application from current domain state

Rejected. Later author edits, coincidentally equal content, revision drift, or another operation can
produce the same visible state without proving this approval executed.

### Retry `ChangeSetService.commit` after a lost response

Rejected under the current contract. S2a removes ordinary same-process partial ChangeSet commits,
but its idempotency key is still not a terminal durable receipt and its in-memory file compensation
does not survive a process crash. Retry is allowed only after S2b has reconciled any active journal
and S2c provides receipt-backed terminal idempotency.

### Put manuscript preimages or the S2b journal in SQLite blobs

Rejected. The SQLite transaction can roll back while already published files survive a process
crash, so a journal stored only in that transaction can disappear exactly when it is needed.
Persisting manuscript bodies in another table would also create a second manuscript/preimage
authority and expand sensitive retention. S2b keeps bounded metadata outside the transaction and
reuses existing history snapshots.

### Create sidecar manuscript copies or switch current-content pointers

Rejected. A shadow manuscript tree or pointer-flip protocol would compete with canonical chapter
paths and existing history, multiply root-containment and cleanup states, and redesign storage far
beyond S2b. Existing history snapshots plus exact reverse compensation are sufficient.

### Keep only S2a same-process compensation

Rejected. In-memory preimages and exception handlers cannot run after process death. They provide
failure atomicity for a surviving controller, not restart reconciliation.

### Infer recovery from messages or approximate current state

Rejected. Message text, raw exceptions, a higher revision, equal-looking content, and SQLite's
general atomicity do not prove which operation-kind effects committed. Mutating recovery requires
one complete exact pre-state or final-state predicate; a typed all-NO_OP set uses the separate exact
unchanged-state contract and cannot be inferred from untyped equality.

### Steal ownership when the lease expires

Rejected. A suspended or slow live owner can outlast its lease, and PID reuse can make PID-only
liveness unsafe. Exclusive lock ownership plus PID/process-start proof is mandatory; denied or
unknown process inspection fails closed. The journal binds only immutable owner identity;
`ProjectLock` alone owns mutable heartbeat/lease liveness.

### Mirror mutable heartbeat fields into the journal

Rejected. ProjectLock and journal are separate files, so two atomic replaces cannot form one atomic
heartbeat update. A process crash between replaces would manufacture an owner mismatch. The journal
therefore stores only immutable owner identity, while ProjectLock is the sole mutable heartbeat and
lease authority.

### Store paths, titles, bodies, or proposal payload in the journal

Rejected. Paths can become stale or escape after layout changes, and raw titles, bodies, selections,
replacements, and proposals duplicate sensitive author/model data. Validated IDs, repository path
derivation, hashes, and canonical proposal identity provide the required evidence.

### Add schema v26 or a terminal retry tombstone in S2b

Rejected. Filesystem crash reconciliation does not need a database migration, and a side tombstone
would compete with the accepted v25 receipt. S2c owns receipt-backed terminal retry semantics after
the journal is deleted.

### Persist the complete proposal or selection payload in the receipt

Rejected. The receipt needs stable identity and bounded evidence, not another copy of manuscript or
untrusted payload data.

### Let QML synthesize the terminal result

Rejected. QML cannot observe the transaction boundary and is not a domain or Harness truth owner.

### Include H-UNIFY1 or H-STATUS1 in the approval tickets

Rejected. Approval execution safety is a prerequisite. Orchestration unification and full status
projection remain separately reviewable changes.

## Consequences

- H-APPR1b must add a small approval-specific unit-of-work surface so approval, domain, event, and
  run repositories can share a caller-owned SQLite transaction.
- The integrated v25 foundation adds `APPROVAL_EXECUTION_FINALIZED` and extends the v21 event-type
  constraint; its SQLite constraint rebuild preserves every historical event field-for-field and
  proves row-for-row equality, while S2c still must wire finalization into the shared transaction.
- Event consumers become schema-version aware: legacy `APPROVAL_RESOLVED` remains decision-only,
  while execution projections consume the new event only when it matches durable receipt/domain
  evidence.
- Dirty historical approval payloads no longer block the whole v25 upgrade. Each unparseable
  commit-capable row receives a minimal migration-only `LEGACY_UNRESOLVED` identity without copying
  or hashing its raw payload.
- A migrated unresolved pending approval remains visible and decidable, but approval fails closed
  with `MISSING_TARGET_IDENTITY`; rejection remains a no-write `DISCARDED` workflow.
- `UNSUPPORTED_APPROVAL` makes no-facade kinds deterministic and auditable without sending them
  through commit recovery.
- Fresh v25 commit-capable requests face a stricter persistence boundary: complete normal target
  identity is mandatory, and migration fallback cannot be requested by application code.
- Receipt SQL constraints, DTO validation, and repository transitions must enforce the same
  target-kind/state/decision/disposition/failure matrix; H-APPR1b tests must prove their agreement
  and raw-payload non-disclosure.
- S2a removes sequential same-process partial ChangeSet commit as an acceptable approval path, but
  its in-memory file compensation leaves the process-crash window that S2b closes.
- SubjectMerge can reuse its existing atomic merge record, but must bind it to the Harness receipt.
- The dedicated ProjectConstitution flow must adopt the same durable backend semantics even though
  its UI remains separate.
- Recoverable open pre-v25 approved approvals may require a manual audit after fail-closed
  `MISSING_TARGET_IDENTITY` or `MISSING_OUTCOME`, because current rows cannot prove whether a commit
  occurred. This ambiguity must be shown, not guessed away.
- Already-closed legacy runs without exact approval-bound evidence remain explicitly unverified;
  migration does not append late events or rewrite their run history to manufacture a disposition.
- Receipt storage and UI errors become smaller and safer because only allowlisted bounded evidence
  and sanitized failures cross those boundaries.
- S2b adds one bounded metadata journal and deliberately reuses existing history snapshots, so
  canonical manuscript authority does not move.
- Title operations distinguish `MUTATING` from exact `NO_OP`; an all-NO_OP journal can be cleaned
  without inventing a manuscript mutation or terminal receipt, while S2c remains the APPLIED-result
  authority.
- Snapshot-create actions model their real pre-state as `ABSENT`; only an exact `after_hash` proves
  publication.
- The project writer lock becomes a real recovery boundary: lock acquisition precedes
  open/migration, owner identity survives PID reuse, and unknown liveness blocks instead of
  deleting evidence. Only ProjectLock carries mutable heartbeat/lease state.
- Project open can now remain unavailable after corruption, ambiguous database evidence,
  incomplete compensation, or Windows sharing failure. This is intentional fail-closed behavior;
  later locked reopen retries safe transient failures.
- S2b restart recovery can clean up only while its journal remains. S2c remains necessary for
  receipt-backed terminal client retries after successful journal deletion.
- H-APPR1a is smaller after H-APPR1b: it maps one typed result and reloads only on `APPLIED`.
- Crash-injection and restart tests become mandatory in H-APPR1b, but no such tests are implemented
  by this decision-only ticket.

## Risks and mitigations

- A stale-owner false positive could allow two writers to compensate the same project. Immutable
  session/PID/process-start binding, exclusive lock acquisition, journal owner CAS, owner-checked
  release, and fail-closed unknown results prevent lease-only takeover. Keeping mutable
  heartbeat/lease exclusively in ProjectLock avoids a non-atomic two-file equality requirement.
- A crash between physical publication/compensation and journal CAS can make recorded action state
  lag reality. Snapshot `ABSENT|after_hash` and canonical `before_hash|after_hash` classification
  make each repeated step idempotent; any third state blocks.
- Same-title APPLIED outcomes can make raw database pre/final values equal. Typed `NO_OP`, exact
  unchanged result evidence, zero file actions, and separate all-NO_OP cleanup prevent false
  ambiguity without treating equality as a mutating receipt.
- A corrupt or adversarial journal could disclose data or exhaust startup. Pre-parse byte limits,
  strict no-extra-fields parsing, bounded counts, atomic quarantine, sanitized markers, and scan
  budgets bound that risk.
- A Windows sharing violation can delay restore or cleanup. The implementation retains all
  evidence, blocks writer-open, and retries later rather than deleting or overwriting uncertain
  files.
- Exact pre/final predicates can fail after external tampering or unsupported direct writes. The
  system preserves evidence and requires explicit repair; it never guesses a commit result.
- Process-crash durability does not prove power-loss durability. The contract states that boundary
  explicitly instead of relying on filesystem/controller behavior the application cannot guarantee.

## Delivery and later implementation scope

This H-APPR-S2b-D0 correction changes only this existing ADR 0025 and keeps its status `Accepted`.
It does not change ADR 0024, Board, source, tests, migration/schema, QML, or any second file, and it
runs no program tests.

A later S2b readiness proposal may name at most six production files and five test files. Any
additional production/test/documentation file, migration, schema change, receipt/event/run/QML
change, or authority expansion is `SCOPE_CHANGE` and requires current-master approval before edit.
After this D0 correction is committed and integrated, that S2b worktree must rebase or fast-forward
to the new exact integrated baseline and verify branch, HEAD, parent/merge-base, tracked/index/
untracked cleanliness before implementation.

## Non-goals

- Implementing production code, tests, migration, schema changes, or data backfill.
- Entering H-APPR1b-S2b, H-APPR1b-S2c, H-APPR1a, H-UNIFY1, or H-STATUS1 implementation.
- Modifying ADR 0024, the backend worktree board, or ticket ownership.
- Adding a second D0 document or changing any file other than this accepted ADR.
- Adding schema v26, a retry tombstone, SQLite manuscript blobs, sidecar manuscript authorities, or
  new receipt/event/run/QML state in S2b.
- Claiming controller, drive-cache, kernel, filesystem, or power-loss atomicity.
- Automatically deleting quarantine evidence or guessing through a recovery block.
- Redesigning every approval proposal payload or historical retention policy.
- Repairing, normalizing, or copying malformed legacy approval payloads into new receipt evidence.
- Adding a new `RunStage` or a full replacement event-sourcing architecture.
- Adding ProjectConstitution controls to the chapter QML timeline.
- Changing manual editor save, user manuscripts, databases, backups, exports, credentials, or
  provider configuration.

## Follow-up dependency

After this accepted-contract correction is reviewed, committed, and integrated:

```text
rebase/fast-forward S2b to the new exact integrated baseline
-> H-APPR1b-S2b (metadata journal, lock owner, reopen/quarantine, process-crash tests)
-> H-APPR1b-S2c (v25 receipt/event/run same-SQLite-transaction wiring)
-> H-APPR1a (typed Port/Controller/Facade mapping and QML correctness)
-> H-UNIFY1
```

H-STATUS1 remains a later, separate projection ticket. S2b production scope is capped at six files
and test scope at five files at readiness; any expansion or schema work stops as `SCOPE_CHANGE`.
