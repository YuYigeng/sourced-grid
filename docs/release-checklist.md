# v0.1 release checklist

- [x] Required CI checks pass on the release commit: backend, web, containers.
- [x] `npm audit --omit=dev --audit-level=high` reports zero high/critical findings.
- [x] Old-schema fixture migration retains grids, cells, provenance, artifacts, and secrets.
- [x] Docker Compose cold-start completes a deterministic result in under ten minutes.
- [x] 100-repository benchmark records failures without blocking other rows.
- [x] API/Worker restart resumes committed tasks and does not duplicate final executions.
- [ ] GitHub + Anthropic and GitHub + trusted OpenAI-compatible runs pass on a clean machine.
- [x] No plaintext credential appears in API, logs, SSE, exports, errors, or artifact headers.
- [ ] GHCR `linux/amd64` and `linux/arm64` images, digests, SBOM, provenance, and checksums are attached.
- [x] Branch protection requires backend, web, and containers; Dependabot and private vulnerability reporting are enabled.
- [x] README screenshots and sub-60-second demo correspond to the release candidate.

Evidence and remaining gates are recorded in [`rc-acceptance-2026-08-14.md`](rc-acceptance-2026-08-14.md).
