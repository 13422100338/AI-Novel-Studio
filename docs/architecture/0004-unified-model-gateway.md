# ADR 0004: Unified model gateway and Phase 3 boundaries

## Status

Accepted and implemented on 2026-07-03.

## Decision

All model requests cross the same application and infrastructure boundary:

```text
PySide6 UI intent
    -> ModelTaskCoordinator (background QRunnable)
    -> ModelTaskService (prompt order and task contract)
    -> LLMContractRunner when structured output is required
    -> LLMGateway (route, credential, retry, usage)
    -> ProviderAdapter
    -> OpenAI-compatible API or third-party relay
```

UI classes do not construct HTTP requests. Provider adapters do not read or write project storage.
`MainWindow` only connects Qt signals and moves validated results into reviewable, non-persistent
Phase 2 surfaces.

## Configuration and secrets

Configuration has three separate layers:

1. `ProviderProfile`: connection name, Base URL, optional models URL, interface type, timeout, and a
   credential reference.
2. `ModelProfile`: model ID, observed capabilities, context/output limits, and optional price data.
3. `TaskRoutes`: independent plot and prose defaults with optional Brief-normalization and
   style-audit overrides.

Provider and route metadata is atomically written to the local application configuration directory.
API keys are stored as Windows generic credentials and never appear in JSON, logs, exceptions,
Git history, or exported projects. Removing a provider removes its retired credential. A connection
edit preserves the existing credential reference.

## Routing

Routing is deterministic. An explicit task override wins; otherwise plot discussion, Current
Chapter Requirement, Brief normalization, and memory extraction use the plot route, while prose,
style audit, and local repair use the prose route. Missing routes or credentials are visible errors.
The gateway never silently changes provider or model after a paid call fails.

Phase 3 exposes a prose route so the user can configure the two-model architecture, but it does not
enable prose generation. The formal prose pipeline, frozen-Brief requirement, checkpoints, and
recovery remain Phase 5 work. Local repair remains Phase 6.

## Provider compatibility and capability discovery

`OpenAICompatibleAdapter` supports configurable Base URLs, custom model-list URLs, ordinary chat
completions, JSON response mode, usage details, reasoning content when returned, and SSE streaming.
HTTP is implemented behind an injectable transport so tests never perform billable calls.

Capabilities are not inferred from model names. The user explicitly chooses a discovered model and
runs opt-in probes for basic chat, model listing, streaming, JSON, reasoning, usage reporting, and
future tool support. Unsupported and untested are distinct; untested is displayed as `未知`.

## Prompt order and task contracts

Stable role rules are placed first. Conversation history and current manuscript evidence follow,
and the newest user task remains last. This ordering preserves authority while allowing compatible
providers to cache stable prefixes.

Phase 3 task services provide:

- streamed plot discussion with the current editor text visible to the model;
- a formal Current Chapter Requirement candidate that cannot overwrite a locked requirement;
- JSON-contract normalization of a Chapter Brief draft;
- JSON-contract style findings that remain review-only.

Structured responses accept plain or fenced JSON. Required fields and types are validated. A failed
contract receives one correction request containing the exact validation error; a second failure
stops. The application never guesses missing structured data.

## Streaming, retry, and partial output

A request may retry only before any response content arrives. Once text has streamed, a connection
failure becomes a partial-result event; received text remains visible and the call is not restarted.
This prevents duplicate or divergent prose. No provider error includes response bodies or API keys.

## Token limits and usage

The user-selected output limit is passed unchanged through UI, task service, gateway, and adapter up
to the supported application maximum of `200000`. It is never silently reduced to `3000`, `16000`,
or another internal value. Provider-side limits may still return an explicit API error.

Usage records distinguish actual and estimated input, output, cached input, and reasoning Tokens.
They also record call count, retries, failures, duration, and cost when both price and actual usage
are available. If a relay omits cache data or price, the UI displays `未知` instead of inventing a
zero-cost cache result.

## Consequences

Phase 4 can supply retrieved memory and Context Manifests without changing provider code. Phase 5
can add the prose state machine on top of the existing prose route and stream events. Phase 7 can
add tool calls behind new adapter contracts without allowing an Agent to bypass repositories.

