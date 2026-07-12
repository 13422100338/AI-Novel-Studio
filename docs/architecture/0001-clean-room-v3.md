# ADR 0001: Clean-room V3 repository

## Status

Accepted on 2026-07-02.

## Decision

AI Novel Studio V3 is implemented in a new repository with new source code and new Git history.
The legacy application is only a behavioral and migration reference. No legacy source file is copied.

The desktop framework is PySide6. Public identity uses the project name or
`AI Novel Studio contributors`; private identity and local paths are prohibited from commits and artifacts.

## Consequences

- Legacy projects require an explicit importer in a later phase.
- Every release must pass source, history and binary privacy checks.
- The new repository can evolve without preserving obsolete auto-pilot and one-click correction code.
