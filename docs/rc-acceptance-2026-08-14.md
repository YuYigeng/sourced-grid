# v0.1 RC acceptance — 2026-08-14

This record captures the checks performed against merge commit `33aba103dac41e831380f5e3188c8dd84c7a325a` before tagging `v0.1.0-rc.1`.

## Passed gates

- The protected `main` workflow passed `backend`, `web`, and `containers`: [GitHub Actions run 31764850304](https://github.com/YuYigeng/sourced-grid/actions/runs/31764850304).
- Production `npm audit` reported no high or critical findings. The backend suite passed 32 tests, including migration from the legacy schema fixture.
- Repository-wide Dependabot activation surfaced alerts outside the production npm audit. The RC branch upgrades `cryptography` to 50.0.0, pytest to 9.1.1 with pytest-asyncio 1.4.0, js-yaml to 4.3.1, patched brace-expansion releases, and Babel 7.29.7+ lock entries; the full npm audit then reports zero vulnerabilities.
- A separate Compose project with a new data volume built ARM64 images and reached healthy API, Web, and Worker services in 246.67 seconds.
- Its first no-credential run completed 27 deterministic GitHub/Transform tasks in about ten seconds. Six LLM tasks failed in isolation because no hosted-provider credential was configured.
- The immediate replay reused 30 of 36 immutable executions, including all GitHub, Transform, and input snapshot executions. Run-scoped JSON export returned all three rows as an attachment.
- Synthetic GitHub and Anthropic credentials were exercised through structured provider errors. Exact sentinel values were absent from API responses, SSE replay, run results, exports, Docker logs, Artifact headers, and all seven files in the data volume.
- Artifact downloads returned `Content-Disposition: attachment` and `X-Content-Type-Options: nosniff`.
- The authenticated 100-repository acceptance, Worker restart, multi-Worker claim test, failure isolation, and full cache replay are documented in [`../benchmarks/2026-08-14-v0.1.md`](../benchmarks/2026-08-14-v0.1.md).
- `main` requires PRs and successful `backend`, `web`, and `containers` checks, enforces linear history and conversation resolution, and blocks force pushes and deletion. Dependabot alerts/security updates, secret scanning push protection, private vulnerability reporting, Discussions, and repository topics are enabled.

## Remaining before the RC tag

- Repeat the clean-volume hosted-provider acceptance with GitHub + Anthropic. GitHub + DeepSeek already passed the authenticated 100-repository benchmark, but the original release gate requires both provider families on a clean installation.
- Tag the accepted commit and verify the Release workflow publishes GHCR `linux/amd64` and `linux/arm64` images, image digests, source SBOM, provenance, and checksums.

The clean acceptance volume contained only synthetic credentials and temporary results. It was deleted after the scan; the user's existing encrypted data volume was restarted and verified intact.
