# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] - 2026-08-14

### Added

- A bilingual English and Simplified Chinese project introduction with verified product screenshots, workflow, provider coverage, and quick-start guidance.

### Verified

- Promoted the complete `0.1.0-rc.1` feature set to the first stable release after protected-branch CI, isolated Docker startup and migration, Worker restart recovery, live GitHub + DeepSeek execution, immutable run-scoped export, cache replay, and credential-pattern scans all passed.
- Updated the release workflow actions to their Node 24-compatible major versions without changing the published image, provenance, SBOM, digest, or checksum contract.

## [0.1.0-rc.1] - 2026-08-14

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
- Cryptography, pytest, js-yaml, brace-expansion, and Babel lock entries upgraded to patched releases after enabling repository-wide Dependabot alerts.
- GitHub repository migrations now follow only same-origin API redirects, while unavailable optional GitHub resources degrade to empty evidence instead of failing an entire row.
