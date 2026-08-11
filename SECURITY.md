# Security policy

SourcedGrid is a local, single-user application. It is not a multi-tenant security boundary.

## Reporting a vulnerability

Please use GitHub private vulnerability reporting when it is enabled for the repository. Do not include credentials, private repository data, or exploit details in a public issue.

Include the affected version, reproduction steps, impact, and any suggested mitigation. Maintainers should acknowledge a report within seven days and coordinate disclosure after a fix is available.

## Supported versions

Security fixes are applied to the latest release and the current `main` branch.

## Security expectations

- Keep the local data directory and generated master key private.
- Bind the API to localhost unless the deployment has a separate trusted access-control layer.
- Treat HTTP and GitHub content as untrusted input.
- Review imported templates before running them.
- Rotate a provider credential immediately if it may have appeared in logs, exports, screenshots, or issue reports.
