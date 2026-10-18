from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import StrEnum

from ai_novel_studio.harness.cancel_token import CancellationError
from ai_novel_studio.harness.event_store import HarnessRunClosedError
from ai_novel_studio.infrastructure.llm.contract_runner import ContractValidationError
from ai_novel_studio.infrastructure.llm.provider_adapter import ProviderRequestError


class RetryDecision(StrEnum):
    """Orchestration decision for one failed step (design v0.3 §56)."""

    RETRY = "RETRY"
    RECOMPILE_ONCE = "RECOMPILE_ONCE"
    SAVE_PARTIAL_AND_ASK = "SAVE_PARTIAL_AND_ASK"
    STOP = "STOP"


class ContextTooLongError(ValueError):
    """The compiled context exceeds the model window (design §56)."""


class PartialStreamError(RuntimeError):
    """A long stream ended mid-content with a saved partial draft (§56)."""


@dataclass(frozen=True, slots=True)
class FailureDecision:
    decision: RetryDecision
    reason: str


def classify_failure(error: BaseException) -> FailureDecision:
    """Deterministic failure classification (design v0.3 §56).

    Transient transport failures may retry (the gateway enforces the default
    two attempts and Retry-After); context pressure triggers one recompile;
    interrupted streams keep the partial draft and ask the author; everything
    else stops. The harness never auto-switches models.
    """
    if isinstance(error, ProviderRequestError):
        if error.retryable:
            return FailureDecision(RetryDecision.RETRY, "transient provider failure")
        return FailureDecision(RetryDecision.STOP, "provider rejected the request")
    if isinstance(error, ContextTooLongError):
        return FailureDecision(
            RetryDecision.RECOMPILE_ONCE, "context exceeds the model window"
        )
    if isinstance(error, PartialStreamError):
        return FailureDecision(
            RetryDecision.SAVE_PARTIAL_AND_ASK, "stream interrupted after partial content"
        )
    if isinstance(error, ContractValidationError):
        return FailureDecision(
            RetryDecision.STOP,
            "structured output failed validation after the built-in correction",
        )
    if isinstance(error, CancellationError):
        return FailureDecision(RetryDecision.STOP, "run was cancelled")
    if isinstance(error, HarnessRunClosedError):
        return FailureDecision(RetryDecision.STOP, "run is closed")
    if isinstance(error, sqlite3.Error):
        return FailureDecision(RetryDecision.STOP, "database error")
    if isinstance(error, (LookupError, KeyError)):
        return FailureDecision(RetryDecision.STOP, "missing model, credential or record")
    return FailureDecision(RetryDecision.STOP, "unknown failure")
