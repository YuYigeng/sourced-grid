# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Immutable `CellExecution`, execution lineage, run snapshots, run-scoped exports, and cell history.
- Lossless Alembic migration with consistent pre-upgrade SQLite backups.
- Trusted Provider Profiles, local credential assignment, and template provider slots.
- Strict `{ "value": ... }` envelopes with JSON Schema validation and one repair attempt.
- TTL-aware versioned cache, force refresh, worker heartbeat, atomic budget reservation, reset-aware GitHub limits, and persistent SSE replay.
- DNS-pinned HTTP transport, streamed response limits, artifact download hardening, and structured redacted errors.
- Visual DAG editor, grid/row APIs, mapped CSV import, Run log, Provider settings, and execution history.
- LLM presets for DeepSeek, Qwen, Zhipu GLM, MiniMax, SiliconFlow, and Ollama with configurable model, temperature, credential, and structured-output compatibility mode.
- Provider-level token pricing with cached-input accounting and immutable cost-estimate metadata.
- Technical Documentation Comparator template and release/benchmark infrastructure.

### Fixed

- JSON + receipts export now encodes provenance datetimes.
- Demo data and the flagship E2E contract now both use twelve columns.
- Compose binds the single-user services to loopback by default.
- Next.js and production dependencies upgraded to versions with no high or critical production audit findings.
- GitHub repository migrations now follow only same-origin API redirects, while unavailable optional GitHub resources degrade to empty evidence instead of failing an entire row.
