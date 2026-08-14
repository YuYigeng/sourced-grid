# v0.1 RC acceptance — 2026-08-14

This record captures the checks performed against the protected `main` release candidate before tagging `v0.1.0-rc.1`.

## Passed gates

- The protected `main` workflow passed `backend`, `web`, and `containers`: [GitHub Actions run 31766322409](https://github.com/YuYigeng/sourced-grid/actions/runs/31766322409).
- Production `npm audit` reported no high or critical findings. The backend suite passed 32 tests, including migration from the legacy schema fixture.
- Repository-wide Dependabot activation surfaced alerts outside the production npm audit. The RC upgrades `cryptography` to 50.0.0, pytest to 9.1.1 with pytest-asyncio 1.4.0, js-yaml to 4.3.1, patched brace-expansion releases, and Babel 7.29.7+ lock entries; the full npm audit and the repository's open Dependabot alert list both report zero findings.
- A separate Compose project with a new data volume built ARM64 images and reached healthy API, Web, and Worker services in 246.67 seconds.
- Its first no-credential run completed 27 deterministic GitHub/Transform tasks in about ten seconds. Six LLM tasks failed in isolation because no hosted-provider credential was configured.
- The immediate replay reused 30 of 36 immutable executions, including all GitHub, Transform, and input snapshot executions. Run-scoped JSON export returned all three rows as an attachment.
- Synthetic GitHub and Anthropic credentials were exercised through structured provider errors. Exact sentinel values were absent from API responses, SSE replay, run results, exports, Docker logs, Artifact headers, and all seven files in the data volume.
- Artifact downloads returned `Content-Disposition: attachment` and `X-Content-Type-Options: nosniff`.
- The authenticated 100-repository acceptance, Worker restart, multi-Worker claim test, failure isolation, and full cache replay are documented in [`../benchmarks/2026-08-14-v0.1.md`](../benchmarks/2026-08-14-v0.1.md).
- After rebuilding the preserved encrypted workspace with the patched RC images, force-refresh Run `2910246f-0a2b-4aaf-8b77-d2d840c9bfeb` completed 33/33 tasks with no failures. Its six live DeepSeek executions used `deepseek-v4-flash`, produced six distinct raw-response Artifacts, and recorded an estimated total cost of `$0.01267796`.
- Immediate replay Run `e9dd6e7e-3d18-44f0-b0dd-4885df02d3d4` reused 36/36 immutable executions, including all six DeepSeek results, with `$0` additional estimated cost. Its run-scoped JSON export returned HTTP 200 as an attachment.
- `main` requires PRs and successful `backend`, `web`, and `containers` checks, enforces linear history and conversation resolution, and blocks force pushes and deletion. Dependabot alerts/security updates, secret scanning push protection, private vulnerability reporting, Discussions, and repository topics are enabled.

## Provider acceptance scope

- GitHub and the trusted OpenAI-compatible DeepSeek profile have passed live authenticated runs.
- Anthropic remains available as a built-in profile and is covered by connector, schema, error-redaction, and synthetic-credential tests, but it has not been exercised against a live Anthropic account because the project owner does not have an Anthropic API credential. This limitation is accepted for `v0.1.0-rc.1` and is not represented as a successful live-provider test.

## Publication verification

- [Release workflow 31777716796](https://github.com/YuYigeng/sourced-grid/actions/runs/31777716796) completed successfully and published the [`v0.1.0-rc.1` prerelease](https://github.com/YuYigeng/sourced-grid/releases/tag/v0.1.0-rc.1).
- Anonymous registry inspection verified public `linux/amd64` and `linux/arm64` manifests plus per-platform attestation manifests for both images.
- Engine digest: `sha256:1e10fe453cf3f75090071d08345705d45441bb990cc00c5b1874050cf6ff14c7`.
- Web digest: `sha256:cf95046a3a070f2515cc3406abbb0830b67f9176b73145d072847b94c2758f2b`.
- The attached `checksums.txt` validates both digest files, and `sourced-grid-source.spdx.json` is a valid SPDX JSON document.

The clean acceptance volumes contained only synthetic credentials or no credentials and temporary results. They were deleted after the scans; the user's existing encrypted data volume was rebuilt with the patched RC images, restarted, and verified intact.
