from __future__ import annotations

import asyncio
import csv
import io
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from .db import SessionLocal, get_db, initialize_database
from .engine import create_run
from .models import (
    Artifact,
    Cell,
    ColumnDefinition,
    EncryptedSecret,
    Grid,
    GridRow,
    Provenance,
    Run,
    RunTask,
    Template,
    utcnow,
)
from .schemas import (
    ColumnIn,
    ColumnPatch,
    GridCreate,
    ImportRows,
    RunCreate,
    SecretIn,
    TemplateImport,
)
from .secrets import SecretVault
from .template import TemplateValidationError, load_template, parse_template, validate_dag

ROOT = Path(__file__).resolve().parents[2]
RADAR_TEMPLATE = ROOT / "templates" / "github-repository-radar.yaml"
STANDARD_SECRETS = ["github_token", "anthropic_api_key", "openai_api_key"]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_database()
    seed_workspace()
    yield


app = FastAPI(
    title="SourcedGrid API",
    version="0.1.0",
    description="Local-first research grids with source receipts.",
    lifespan=lifespan,
)
settings = get_settings()
DbSession = Annotated[Session, Depends(get_db)]
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Last-Event-ID"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0"}


@app.get("/v1/grids")
def list_grids(session: DbSession) -> list[dict[str, Any]]:
    grids = session.scalars(select(Grid).order_by(Grid.updated_at.desc())).all()
    return [serialize_grid(session, grid) for grid in grids]


@app.post("/v1/grids", status_code=status.HTTP_201_CREATED)
def create_grid(payload: GridCreate, session: DbSession) -> dict[str, Any]:
    grid = Grid(name=payload.name, description=payload.description)
    session.add(grid)
    session.commit()
    return serialize_grid(session, grid)


@app.get("/v1/grids/{grid_id}")
def get_grid(grid_id: str, session: DbSession) -> dict[str, Any]:
    grid = require_grid(session, grid_id)
    return serialize_grid(session, grid)


@app.post("/v1/grids/{grid_id}/import")
def import_rows(grid_id: str, payload: ImportRows, session: DbSession) -> dict[str, Any]:
    grid = require_grid(session, grid_id)
    input_column = session.scalar(
        select(ColumnDefinition)
        .where(ColumnDefinition.grid_id == grid_id, ColumnDefinition.kind == "input")
        .order_by(ColumnDefinition.position)
    )
    if not input_column:
        raise HTTPException(409, "Grid does not have an input column")
    add_rows(session, grid, input_column, payload.values)
    session.commit()
    return serialize_grid(session, grid)


@app.post("/v1/grids/{grid_id}/columns", status_code=status.HTTP_201_CREATED)
def add_column(grid_id: str, payload: ColumnIn, session: DbSession) -> dict[str, Any]:
    grid = require_grid(session, grid_id)
    position = (
        session.scalar(
            select(func.count()).select_from(ColumnDefinition).where(ColumnDefinition.grid_id == grid_id)
        )
        or 0
    )
    column = ColumnDefinition(grid_id=grid_id, position=position, **payload.model_dump())
    session.add(column)
    session.flush()
    for row in grid.rows:
        session.add(Cell(row_id=row.id, column_id=column.id, status="empty"))
    validate_grid_dag(session, grid_id)
    session.commit()
    return serialize_grid(session, grid)


@app.patch("/v1/grids/{grid_id}/columns/{column_id}")
def patch_column(grid_id: str, column_id: str, payload: ColumnPatch, session: DbSession) -> dict[str, Any]:
    grid = require_grid(session, grid_id)
    column = session.scalar(
        select(ColumnDefinition).where(ColumnDefinition.id == column_id, ColumnDefinition.grid_id == grid_id)
    )
    if not column:
        raise HTTPException(404, "Column not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(column, key, value)
    validate_grid_dag(session, grid_id)
    session.commit()
    return serialize_grid(session, grid)


@app.delete("/v1/grids/{grid_id}/columns/{column_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_column(grid_id: str, column_id: str, session: DbSession) -> Response:
    require_grid(session, grid_id)
    column = session.scalar(
        select(ColumnDefinition).where(ColumnDefinition.id == column_id, ColumnDefinition.grid_id == grid_id)
    )
    if not column:
        raise HTTPException(404, "Column not found")
    dependents = session.scalars(select(ColumnDefinition).where(ColumnDefinition.grid_id == grid_id)).all()
    if any(column.key in item.depends_on for item in dependents):
        raise HTTPException(409, "Remove dependent columns first")
    session.delete(column)
    session.commit()
    return Response(status_code=204)


@app.post("/v1/grids/{grid_id}/runs", status_code=status.HTTP_202_ACCEPTED)
def start_run(grid_id: str, payload: RunCreate, session: DbSession) -> dict[str, Any]:
    require_grid(session, grid_id)
    active = session.scalar(
        select(Run)
        .where(Run.grid_id == grid_id, Run.status.in_(["queued", "running", "paused"]))
        .order_by(Run.created_at.desc())
    )
    if active:
        raise HTTPException(409, "This grid already has an active run")
    try:
        run = create_run(session, grid_id, payload.budget_usd)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return serialize_run(run)


@app.get("/v1/runs/{run_id}")
def get_run(run_id: str, session: DbSession) -> dict[str, Any]:
    return serialize_run(require_run(session, run_id))


@app.get("/v1/runs/{run_id}/events")
async def run_events(run_id: str, request: Request) -> StreamingResponse:
    async def stream():
        previous = ""
        while not await request.is_disconnected():
            with SessionLocal() as session:
                run = session.get(Run, run_id)
                if not run:
                    yield 'event: error\ndata: {"error":"run not found"}\n\n'
                    return
                payload = json.dumps(serialize_run(run), default=str)
                if payload != previous:
                    yield f"event: run\ndata: {payload}\n\n"
                    previous = payload
                if run.status in {"completed", "completed_with_errors", "failed", "cancelled"}:
                    return
            await asyncio.sleep(0.7)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.post("/v1/runs/{run_id}/pause")
def pause_run(run_id: str, session: DbSession) -> dict[str, Any]:
    run = require_run(session, run_id)
    if run.status not in {"queued", "running"}:
        raise HTTPException(409, "Only an active run can be paused")
    run.status = "paused"
    session.commit()
    return serialize_run(run)


@app.post("/v1/runs/{run_id}/resume")
def resume_run(run_id: str, session: DbSession) -> dict[str, Any]:
    run = require_run(session, run_id)
    if run.status != "paused":
        raise HTTPException(409, "Run is not paused")
    run.status = "running" if run.started_at else "queued"
    session.commit()
    return serialize_run(run)


@app.post("/v1/runs/{run_id}/cancel")
def cancel_run(run_id: str, session: DbSession) -> dict[str, Any]:
    run = require_run(session, run_id)
    if run.status not in {"queued", "running", "paused"}:
        return serialize_run(run)
    run.cancel_requested = True
    run.status = "cancelling"
    queued = session.scalars(
        select(RunTask).where(RunTask.run_id == run_id, RunTask.status == "queued")
    ).all()
    for task in queued:
        task.status = "cancelled"
        cell = session.scalar(
            select(Cell).where(Cell.row_id == task.row_id, Cell.column_id == task.column_id)
        )
        if cell:
            cell.status = "cancelled"
    if not session.scalar(
        select(func.count()).select_from(RunTask).where(RunTask.run_id == run_id, RunTask.status == "running")
    ):
        run.status = "cancelled"
        run.completed_at = utcnow()
    session.commit()
    return serialize_run(run)


@app.post("/v1/runs/{run_id}/retry-failed")
def retry_failed(run_id: str, session: DbSession) -> dict[str, Any]:
    run = require_run(session, run_id)
    failed = session.scalars(
        select(RunTask).where(RunTask.run_id == run_id, RunTask.status.in_(["failed", "skipped"]))
    ).all()
    if not failed:
        raise HTTPException(409, "Run has no failed tasks")
    for task in failed:
        task.status = "queued"
        task.error = None
        task.available_at = utcnow()
        task.attempts = 0
        cell = session.scalar(
            select(Cell).where(Cell.row_id == task.row_id, Cell.column_id == task.column_id)
        )
        if cell:
            cell.status = "queued"
            cell.error = None
    run.status = "running"
    run.cancel_requested = False
    run.completed_at = None
    run.failed_tasks = 0
    session.commit()
    return serialize_run(run)


@app.get("/v1/cells/{cell_id}/provenance")
def cell_provenance(cell_id: str, session: DbSession) -> dict[str, Any]:
    provenance = session.scalar(select(Provenance).where(Provenance.cell_id == cell_id))
    if not provenance:
        raise HTTPException(404, "Cell provenance not found")
    return serialize_provenance(provenance)


@app.get("/v1/artifacts/{artifact_hash}")
def get_artifact(artifact_hash: str, session: DbSession) -> FileResponse:
    artifact = session.get(Artifact, artifact_hash)
    if not artifact:
        raise HTTPException(404, "Artifact not found")
    path = (settings.artifacts_dir / artifact.path).resolve()
    if settings.artifacts_dir.resolve() not in path.parents or not path.exists():
        raise HTTPException(404, "Artifact file not found")
    return FileResponse(path, media_type=artifact.content_type, filename=artifact_hash)


@app.get("/v1/grids/{grid_id}/export")
def export_grid(grid_id: str, session: DbSession, format: str = Query(pattern="^(csv|json)$")) -> Response:
    grid = require_grid(session, grid_id)
    serialized = serialize_grid(session, grid)
    if format == "json":
        return JSONResponse(
            serialized,
            headers={"Content-Disposition": f'attachment; filename="{safe_filename(grid.name)}.json"'},
        )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([column["label"] for column in serialized["columns"]])
    for row in serialized["rows"]:
        by_column = {cell["column_id"]: cell for cell in row["cells"]}
        writer.writerow(
            [
                format_export_value(by_column.get(column["id"], {}).get("value"))
                for column in serialized["columns"]
            ]
        )
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename(grid.name)}.csv"'},
    )


@app.get("/v1/templates")
def list_templates(session: DbSession) -> list[dict[str, Any]]:
    templates = session.scalars(select(Template).order_by(Template.name)).all()
    return [{"slug": item.slug, "name": item.name, "version": item.version} for item in templates]


@app.get("/v1/templates/{slug}")
def export_template(slug: str, session: DbSession) -> Response:
    template = session.scalar(select(Template).where(Template.slug == slug))
    if not template:
        raise HTTPException(404, "Template not found")
    return Response(template.document_yaml, media_type="application/yaml")


@app.post("/v1/templates", status_code=status.HTTP_201_CREATED)
def import_template(payload: TemplateImport, session: DbSession) -> dict[str, str]:
    try:
        parsed = parse_template(payload.document)
    except TemplateValidationError as exc:
        raise HTTPException(422, str(exc)) from exc
    template = session.scalar(select(Template).where(Template.slug == parsed.metadata.slug))
    if template is None:
        template = Template(
            slug=parsed.metadata.slug,
            name=parsed.metadata.name,
            version=parsed.metadata.version,
            document_yaml=payload.document,
        )
        session.add(template)
    else:
        template.name = parsed.metadata.name
        template.version = parsed.metadata.version
        template.document_yaml = payload.document
    session.commit()
    return {"slug": template.slug, "name": template.name, "version": template.version}


@app.post("/v1/templates/{slug}/create-grid", status_code=status.HTTP_201_CREATED)
def create_from_template(slug: str, session: DbSession) -> dict[str, Any]:
    template_record = session.scalar(select(Template).where(Template.slug == slug))
    if not template_record:
        raise HTTPException(404, "Template not found")
    template = parse_template(template_record.document_yaml)
    grid = instantiate_template(session, template)
    session.commit()
    return serialize_grid(session, grid)


@app.get("/v1/secrets")
def list_secrets(session: DbSession) -> list[dict[str, Any]]:
    existing = {item.name: item for item in session.scalars(select(EncryptedSecret)).all()}
    return [
        {
            "name": name,
            "configured": name in existing,
            "updated_at": existing[name].updated_at if name in existing else None,
        }
        for name in STANDARD_SECRETS
    ]


@app.put("/v1/secrets/{name}")
def put_secret(name: str, payload: SecretIn, session: DbSession) -> dict[str, Any]:
    if name not in STANDARD_SECRETS:
        raise HTTPException(400, "Unsupported secret name")
    secret = SecretVault().set(session, name, payload.value)
    session.commit()
    return {"name": name, "configured": True, "updated_at": secret.updated_at}


def seed_workspace() -> None:
    template, document = load_template(RADAR_TEMPLATE)
    with SessionLocal() as session:
        record = session.scalar(select(Template).where(Template.slug == template.metadata.slug))
        if record is None:
            session.add(
                Template(
                    slug=template.metadata.slug,
                    name=template.metadata.name,
                    version=template.metadata.version,
                    document_yaml=document,
                )
            )
        else:
            record.name = template.metadata.name
            record.version = template.metadata.version
            record.document_yaml = document
        if not session.scalar(select(func.count()).select_from(Grid)):
            grid = instantiate_template(session, template)
            input_column = next(column for column in grid.columns if column.kind == "input")
            add_rows(
                session,
                grid,
                input_column,
                ["openai/openai-python", "fastapi/fastapi", "OpenHands/OpenHands"],
            )
        session.commit()


def instantiate_template(session: Session, template) -> Grid:
    grid = Grid(
        name=template.metadata.name,
        description=template.metadata.description,
        template_slug=template.metadata.slug,
    )
    session.add(grid)
    session.flush()
    for position, definition in enumerate(template.columns):
        session.add(ColumnDefinition(grid_id=grid.id, position=position, **definition.model_dump()))
    session.flush()
    session.refresh(grid)
    return grid


def add_rows(session: Session, grid: Grid, input_column: ColumnDefinition, values: list[str]) -> int:
    existing = {
        str(value)
        for value in session.scalars(
            select(Cell.value)
            .join(GridRow)
            .where(GridRow.grid_id == grid.id, Cell.column_id == input_column.id)
        ).all()
        if value
    }
    position = (
        session.scalar(select(func.count()).select_from(GridRow).where(GridRow.grid_id == grid.id)) or 0
    )
    columns = session.scalars(
        select(ColumnDefinition)
        .where(ColumnDefinition.grid_id == grid.id)
        .order_by(ColumnDefinition.position)
    ).all()
    added = 0
    for raw in values:
        value = normalize_repo_value(raw)
        if not value or value in existing:
            continue
        row = GridRow(grid_id=grid.id, position=position)
        session.add(row)
        session.flush()
        for column in columns:
            if column.id == input_column.id:
                cell = Cell(row_id=row.id, column_id=column.id, status="succeeded", value=value)
                session.add(cell)
                session.flush()
                session.add(
                    Provenance(
                        cell_id=cell.id,
                        connector="input",
                        source_urls=[value],
                        input_hash=None,
                        duration_ms=0,
                        cache_hit=False,
                        metadata_json={"imported": True},
                    )
                )
            else:
                session.add(Cell(row_id=row.id, column_id=column.id, status="empty"))
        existing.add(value)
        position += 1
        added += 1
    session.flush()
    return added


def normalize_repo_value(value: str) -> str:
    cleaned = value.strip().strip("\"'")
    if not cleaned:
        return ""
    if cleaned.startswith(("http://", "https://")):
        return cleaned.rstrip("/")
    return f"https://github.com/{cleaned.strip('/')}"


def require_grid(session: Session, grid_id: str) -> Grid:
    grid = session.get(Grid, grid_id)
    if not grid:
        raise HTTPException(404, "Grid not found")
    return grid


def require_run(session: Session, run_id: str) -> Run:
    run = session.get(Run, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return run


def validate_grid_dag(session: Session, grid_id: str) -> None:
    columns = session.scalars(
        select(ColumnDefinition)
        .where(ColumnDefinition.grid_id == grid_id)
        .order_by(ColumnDefinition.position)
    ).all()
    document = {
        "apiVersion": "sourcedgrid/v1alpha1",
        "kind": "ResearchTemplate",
        "metadata": {"slug": "validation", "name": "Validation", "version": "0"},
        "columns": [
            {
                "key": item.key,
                "label": item.label,
                "kind": item.kind,
                "width": item.width,
                "depends_on": item.depends_on,
                "config": item.config,
                "prompt": item.prompt,
                "output_schema": item.output_schema,
            }
            for item in columns
        ],
    }
    try:
        validate_dag(parse_template(json.dumps(document)))
    except TemplateValidationError as exc:
        raise HTTPException(422, str(exc)) from exc


def serialize_grid(session: Session, grid: Grid) -> dict[str, Any]:
    columns = session.scalars(
        select(ColumnDefinition)
        .where(ColumnDefinition.grid_id == grid.id)
        .order_by(ColumnDefinition.position)
    ).all()
    rows = session.scalars(select(GridRow).where(GridRow.grid_id == grid.id).order_by(GridRow.position)).all()
    cells = (
        session.scalars(
            select(Cell)
            .options(selectinload(Cell.provenance))
            .where(Cell.row_id.in_([row.id for row in rows]))
        ).all()
        if rows
        else []
    )
    by_row: dict[str, list[Cell]] = {row.id: [] for row in rows}
    for cell in cells:
        by_row[cell.row_id].append(cell)
    order = {column.id: column.position for column in columns}
    return {
        "id": grid.id,
        "name": grid.name,
        "description": grid.description,
        "columns": [
            {
                "id": item.id,
                "key": item.key,
                "label": item.label,
                "kind": item.kind,
                "width": item.width,
                "position": item.position,
                "depends_on": item.depends_on,
                "config": item.config,
                "prompt": item.prompt,
                "output_schema": item.output_schema,
            }
            for item in columns
        ],
        "rows": [
            {
                "id": row.id,
                "position": row.position,
                "cells": [
                    serialize_cell(cell)
                    for cell in sorted(by_row[row.id], key=lambda value: order.get(value.column_id, 9999))
                ],
            }
            for row in rows
        ],
    }


def serialize_cell(cell: Cell) -> dict[str, Any]:
    return {
        "id": cell.id,
        "column_id": cell.column_id,
        "status": cell.status,
        "value": cell.value,
        "error": cell.error,
        "provenance": serialize_provenance(cell.provenance) if cell.provenance else None,
    }


def serialize_provenance(item: Provenance) -> dict[str, Any]:
    return {
        "id": item.id,
        "connector": item.connector,
        "source_urls": item.source_urls,
        "artifact_hash": item.artifact_hash,
        "input_hash": item.input_hash,
        "model": item.model,
        "prompt": item.prompt,
        "input_tokens": item.input_tokens,
        "output_tokens": item.output_tokens,
        "cost_usd": item.cost_usd,
        "duration_ms": item.duration_ms,
        "cache_hit": item.cache_hit,
        "created_at": item.created_at,
        "metadata": item.metadata_json,
    }


def serialize_run(run: Run) -> dict[str, Any]:
    return {
        "id": run.id,
        "status": run.status,
        "total_tasks": run.total_tasks,
        "completed_tasks": run.completed_tasks,
        "failed_tasks": run.failed_tasks,
        "spent_usd": run.spent_usd,
        "budget_usd": run.budget_usd,
    }


def safe_filename(value: str) -> str:
    return (
        "".join(character if character.isalnum() or character in {"-", "_"} else "-" for character in value)
        .strip("-")
        .lower()
        or "sourcedgrid-export"
    )


def format_export_value(value: Any) -> str:
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
