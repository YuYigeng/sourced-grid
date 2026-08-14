# Contributing to SourcedGrid

Thanks for helping make sourced research easier to inspect and repeat.

## Development workflow

1. Create a focused branch from `main`.
2. Follow the local setup in the README.
3. Add tests for behavior changes.
4. Run the checks below before opening a pull request.

```bash
backend/.venv/bin/ruff check backend
backend/.venv/bin/python -m pytest backend/tests
npm run lint
npm run build
npm run test:e2e
```

Keep connectors deterministic where possible. Any generated value must retain its source URLs, input hash, execution metadata, and artifact reference when raw content is available. Never log or return plaintext credentials.

For a new column type or connector, include failure classification, a stable cache fingerprint, provenance fields, and tests for unavailable or malformed upstream data.

## Pull requests

Describe the user-visible change, the evidence that validates it, and any security or compatibility implications. Small, reviewable pull requests are preferred.
