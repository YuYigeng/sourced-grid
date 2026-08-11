# SourcedGrid

**Open-source agentic spreadsheet for sourced, repeatable research.**

SourcedGrid turns a list of repositories into a structured research grid. Each generated cell keeps a receipt: source URLs, raw artifact hash, connector, model, prompt, duration, token use, and estimated cost.

The first included workflow, **GitHub Repository Radar**, compares repository health, activity, licensing, releases, README positioning, and adoption risk without turning research into an untraceable chat transcript.

## What works today

- Import GitHub URLs, `owner/repo` values, or CSV-style lists.
- Durable column DAG with `input`, `github`, `http`, `transform`, and `llm` fields.
- GitHub snapshots covering repository metadata, README, releases, languages, issues, and pull requests.
- Deterministic maintenance score and activity fields that work without an LLM key.
- Anthropic and OpenAI-compatible structured-output connectors.
- SQLite WAL queue with leases, retries, pause, resume, cancellation, and crash recovery.
- Content-addressed raw artifacts and source receipts for every successful generated cell.
- Encrypted local credential vault; plaintext keys are never returned by the API.
- Versioned YAML templates, CSV export, and full JSON export with receipts.
- Local Web UI, FastAPI, SSE run events, and Docker Compose deployment.

## Quick start with Docker

Requirements: Docker Desktop or Docker Engine with Compose.

```bash
docker compose up --build
```

Open [http://localhost:3000](http://localhost:3000). The API documentation is available at [http://localhost:8000/docs](http://localhost:8000/docs).

The app starts with three public repositories. Deterministic GitHub research works without an LLM key. Add a GitHub token and optional provider key in **Settings → Local credentials**. Credentials are encrypted into the Docker data volume.

## Local development

Requirements: Node.js 22.13+, Python 3.12+, and npm.

```bash
npm ci
python3.12 -m venv .venv
.venv/bin/pip install -e './backend[dev]'
cp .env.example .env
```

Run these in separate terminals:

```bash
npm run dev
SOURCEDGRID_DATA_DIR=./data .venv/bin/uvicorn --app-dir backend app.main:app --reload --port 8000
cd backend && SOURCEDGRID_DATA_DIR=../data ../.venv/bin/python -m app.worker
```

## Research template format

Templates use a versioned YAML contract:

```yaml
apiVersion: sourcedgrid/v1alpha1
kind: ResearchTemplate
metadata:
  slug: minimal-repository-check
  name: Minimal repository check
  version: 0.1.0
columns:
  - key: repo_url
    label: Repository
    kind: input
  - key: canonical_name
    label: Canonical name
    kind: transform
    depends_on: [repo_url]
    config:
      source: repo_url
      operation: canonical_repository
```

Templates reject missing dependencies, duplicate keys, self-dependencies, and cycles before they are saved. See [`templates/github-repository-radar.yaml`](templates/github-repository-radar.yaml) for the complete flagship template.

## API surface

- `POST /v1/grids/{grid_id}/import` — add repository rows.
- `POST /v1/grids/{grid_id}/runs` — create a durable research run.
- `GET /v1/runs/{run_id}/events` — stream run progress over SSE.
- `POST /v1/runs/{run_id}/pause|resume|cancel|retry-failed` — control a run.
- `GET /v1/cells/{cell_id}/provenance` — inspect a cell receipt.
- `GET /v1/artifacts/{hash}` — retrieve a content-addressed raw artifact.
- `GET /v1/grids/{grid_id}/export?format=csv|json` — export values or full receipts.
- `GET|POST /v1/templates` — export or import template YAML.

Interactive OpenAPI documentation is served by the local API at `/docs`.

## Security boundaries

- Research content is treated as untrusted data and is wrapped in an explicit prompt-injection boundary before LLM use.
- The HTTP connector blocks loopback, private, link-local, and credential-bearing URLs and limits response size.
- Provider and GitHub credentials are encrypted with AES-256-GCM using a locally generated `0600` master key.
- API responses, exports, and logs expose only whether a secret is configured.
- Provider costs shown in the UI are estimates; provider invoices remain authoritative.

SourcedGrid is a local single-user application in v0.1. It is not a multi-tenant authorization boundary.

## Testing

```bash
.venv/bin/pytest backend/tests
.venv/bin/ruff check backend
npm run lint
npm run build
npm run test:e2e
```

The suite covers template validation, GitHub error classification, SSRF blocking, LLM output validation, encrypted secrets, API import/export, lease recovery, the production Web build, and the primary browser workflows.

## Project layout

```text
app/         Next.js workbench
backend/     FastAPI, worker, connectors, models, tests, Alembic
templates/   Versioned research workflows
data/        Ignored local SQLite, artifacts, and master key
```

## Non-goals for v0.1

Multi-user collaboration, Excel fidelity, arbitrary browser automation, CRM features, hosted accounts, scheduled crawling, a third-party plugin marketplace, and mobile apps are intentionally out of scope.

## License

Apache License 2.0. See [`LICENSE`](LICENSE). Contributions are welcome; see [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`SECURITY.md`](SECURITY.md).
