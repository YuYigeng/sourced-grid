# v0.1 release checklist

- [ ] Required CI checks pass on the release commit: backend, web, containers.
- [ ] `npm audit --omit=dev --audit-level=high` reports zero high/critical findings.
- [ ] Old-schema fixture migration retains grids, cells, provenance, artifacts, and secrets.
- [ ] Docker Compose cold-start completes a deterministic result in under ten minutes.
- [ ] 100-repository benchmark records failures without blocking other rows.
- [ ] API/Worker restart resumes committed tasks and does not duplicate final executions.
- [ ] GitHub + Anthropic and GitHub + trusted OpenAI-compatible runs pass on a clean machine.
- [ ] No plaintext credential appears in API, logs, SSE, exports, errors, or artifact headers.
- [ ] GHCR `linux/amd64` and `linux/arm64` images, digests, SBOM, provenance, and checksums are attached.
- [ ] Branch protection requires backend, web, and containers; Dependabot and private vulnerability reporting are enabled.
- [ ] README screenshots and 60-second demo correspond to the release candidate.
