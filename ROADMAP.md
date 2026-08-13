# SourcedGrid roadmap

## v0.1 — Open-source local research workbench

- Immutable run-scoped executions, receipts, artifacts, and lineage.
- Trusted provider profiles, schema-validated LLM output, TTL cache, force refresh.
- Heartbeat workers, atomic budget ledger, cancellation/lease ownership protection.
- Visual DAG, CSV import, run/event history, two complete templates.
- Container, migration, security, benchmark, and release gates.

## v0.2 candidates

- Remove the `Cell.value/status/error/cache_key` compatibility projection after an announced migration window.
- Expand connector contract testing and deterministic document extractors.
- Add opt-in scheduling and template package discovery without weakening local trust boundaries.

## Explicit non-goals

Authentication, multi-tenancy, hosted SaaS, mobile clients, arbitrary browser automation, and a plugin marketplace are not v0.1 work.
