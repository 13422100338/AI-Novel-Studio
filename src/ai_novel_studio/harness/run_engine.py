from __future__ import annotations

from typing import Protocol

from ai_novel_studio.harness.approval_repository import ApprovalRepository
from ai_novel_studio.harness.approval_service import ApprovalService
from ai_novel_studio.harness.approvals import ApprovalKind, ApprovalRequest
from ai_novel_studio.harness.cancel_token import CancelToken, cancel_run
from ai_novel_studio.harness.completion_check import (
    CompletionChecker,
    CompletionCheckResult,
)
from ai_novel_studio.harness.draft_stream import DraftCandidateResult
from ai_novel_studio.harness.event_repository import HarnessEventRepository
from ai_novel_studio.harness.event_store import HarnessEventStore
from ai_novel_studio.harness.projections import HarnessProjectionService
from ai_novel_studio.harness.run_queue import QueueDecision, RunQueueGate
from ai_novel_studio.harness.run_state import CLOSED_STAGES, HarnessRun, RunEvent, RunStage
from ai_novel_studio.infrastructure.llm.schemas import LLMMessage
from ai_novel_studio.infrastructure.storage.project_repository import ProjectRepository


class RunQueuedError(RuntimeError):
    """A formal run is already executing; the new run must wait (design §58)."""


class RunCancelledError(RuntimeError):
    """The engine refused an action because the run was cancelled."""


class ContextCompileStep(Protocol):
    """Pluggable compile step; the real facade adapter arrives post-merge."""

    def __call__(self, run: HarnessRun) -> object: ...


class ChapterDraftStream(Protocol):
    """Pluggable chapter draft candidate stream (design v0.3 §42, §73).

    The engine owns streaming orchestration: it resolves the run and its
    cancellation token, then delegates to the injected stream service.
    """

    def __call__(
        self,
        run: HarnessRun,
        token: CancelToken,
        messages: tuple[LLMMessage, ...],
        output_token_limit: int,
    ) -> DraftCandidateResult: ...


class HarnessRunEngine:
    """Sole long-transaction orchestrator (contract §4, design A-list).

    Skeleton scope (A12): queue-gated start, stage transitions, cancellation,
    approval request/resolve, completion gates and projections. The context
    compile step is injectable; the chapter-draft loop and tool execution
    arrive after the backend branch merges.
    """

    def __init__(
        self,
        project: ProjectRepository,
        *,
        compile_step: ContextCompileStep | None = None,
        draft_stream: ChapterDraftStream | None = None,
    ) -> None:
        self._store = HarnessEventStore(HarnessEventRepository(project))
        self._approval_repository = ApprovalRepository(project)
        self._approvals = ApprovalService(self._store, self._approval_repository)
        self._checker = CompletionChecker(self._store, self._approval_repository)
        self._queue = RunQueueGate(self._store)
        self._projections = HarnessProjectionService(
            self._store, approvals=self._approval_repository
        )
        self._compile_step = compile_step
        self._draft_stream = draft_stream
        self._tokens: dict[str, CancelToken] = {}

    @property
    def store(self) -> HarnessEventStore:
        return self._store

    @property
    def approvals(self) -> ApprovalService:
        return self._approvals

    @property
    def projections(self) -> HarnessProjectionService:
        return self._projections

    def start(
        self, goal: str, *, active_chapter_id: str | None = None
    ) -> tuple[HarnessRun, RunEvent]:
        if self._queue.evaluate().decision is QueueDecision.QUEUE:
            raise RunQueuedError("another formal run is executing")
        run, created = self._store.start_run(
            goal=goal, active_chapter_id=active_chapter_id
        )
        self._tokens[run.id] = CancelToken()
        return run, created

    def transition(
        self,
        run_id: str,
        stage: RunStage,
        *,
        failure_code: str | None = None,
        failure_message: str | None = None,
    ) -> HarnessRun:
        return self._store.transition(
            run_id,
            stage,
            failure_code=failure_code,
            failure_message=failure_message,
        )

    def run_stage(self, run_id: str) -> RunStage:
        return self._store.get_run(run_id).stage

    def compile_step(self, run_id: str) -> object:
        if self._compile_step is None:
            raise RuntimeError("no compile step is wired for this engine")
        run = self._store.get_run(run_id)
        return self._compile_step(run)

    def stream_draft(
        self,
        run_id: str,
        messages: tuple[LLMMessage, ...],
        output_token_limit: int,
    ) -> DraftCandidateResult:
        if self._draft_stream is None:
            raise RuntimeError("no draft stream is wired for this engine")
        run = self._store.get_run(run_id)
        token = self._tokens.get(run_id)
        if token is None:
            raise RunCancelledError(f"unknown or orphan run: {run_id}")
        return self._draft_stream(run, token, messages, output_token_limit)

    def cancel(self, run_id: str) -> HarnessRun:
        token = self._tokens.get(run_id)
        if token is None:
            raise RunCancelledError(f"unknown or orphan run: {run_id}")
        return cancel_run(self._store, run_id, token)

    def cancelled(self, run_id: str) -> bool:
        token = self._tokens.get(run_id)
        return token.cancelled if token is not None else False

    def recover_open_runs(self) -> tuple[HarnessRun, ...]:
        """Recovery-center reattach (design v0.3 §55, handoff B10).

        Rebuilds the in-process cancellation tokens for runs that survived a
        restart: every run outside a closed stage gets a fresh token, so
        cancel() and stream_draft() work again after reopening the project.
        Closed runs never resurrect.
        """
        runs = tuple(
            run
            for run in self._store.list_runs()
            if run.stage not in CLOSED_STAGES
        )
        for run in runs:
            self._tokens.setdefault(run.id, CancelToken())
        return runs

    def request_approval(
        self,
        run_id: str,
        kind: ApprovalKind,
        summary: str,
        *,
        payload: dict[str, object] | None = None,
        expected_revisions: tuple[tuple[str, int], ...] = (),
        idempotency_key: str,
    ) -> ApprovalRequest:
        return self._approvals.request_approval(
            run_id=run_id,
            kind=kind,
            summary=summary,
            payload=payload,
            expected_revisions=expected_revisions,
            idempotency_key=idempotency_key,
        )

    def resolve_approval(
        self, request_id: str, approved: bool, resolution_note: str | None = None
    ) -> ApprovalRequest:
        return self._approvals.resolve_approval(
            request_id=request_id,
            approved=approved,
            resolution_note=resolution_note,
        )

    def check_completion(self, run_id: str) -> CompletionCheckResult:
        return self._checker.check(run_id)

    def can_complete(self, run_id: str) -> CompletionCheckResult:
        return self._checker.can_complete(run_id)
