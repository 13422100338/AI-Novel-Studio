from __future__ import annotations

import sqlite3

from ai_novel_studio.harness.cancel_token import CancellationError
from ai_novel_studio.harness.event_store import HarnessRunClosedError
from ai_novel_studio.harness.failure_policy import (
    ContextTooLongError,
    PartialStreamError,
    RetryDecision,
    classify_failure,
)
from ai_novel_studio.infrastructure.llm.contract_runner import ContractValidationError
from ai_novel_studio.infrastructure.llm.provider_adapter import ProviderRequestError


def test_transient_provider_failure_retries() -> None:
    decision = classify_failure(ProviderRequestError("HTTP 429", retryable=True))
    assert decision.decision is RetryDecision.RETRY


def test_non_retryable_provider_failure_stops() -> None:
    decision = classify_failure(ProviderRequestError("401", retryable=False))
    assert decision.decision is RetryDecision.STOP


def test_context_pressure_recompiles_once() -> None:
    decision = classify_failure(ContextTooLongError("over budget"))
    assert decision.decision is RetryDecision.RECOMPILE_ONCE


def test_partial_stream_saves_and_asks() -> None:
    decision = classify_failure(PartialStreamError("interrupted"))
    assert decision.decision is RetryDecision.SAVE_PARTIAL_AND_ASK


def test_contract_validation_stops_after_builtin_correction() -> None:
    decision = classify_failure(ContractValidationError("bad json"))
    assert decision.decision is RetryDecision.STOP


def test_cancel_close_db_and_lookup_failures_stop() -> None:
    assert classify_failure(CancellationError("cancelled")).decision is RetryDecision.STOP
    assert (
        classify_failure(HarnessRunClosedError("closed")).decision is RetryDecision.STOP
    )
    assert classify_failure(sqlite3.OperationalError("locked")).decision is RetryDecision.STOP
    assert classify_failure(KeyError("missing")).decision is RetryDecision.STOP
    assert (
        classify_failure(LookupError("missing credential")).decision is RetryDecision.STOP
    )


def test_unknown_failures_stop_closed() -> None:
    decision = classify_failure(RuntimeError("surprise"))
    assert decision.decision is RetryDecision.STOP
    assert "unknown" in decision.reason
