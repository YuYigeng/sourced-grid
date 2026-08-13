from __future__ import annotations

import asyncio
import csv
import io
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from .config import get_settings
from .db import SessionLocal, get_db
from .engine import create_run
from .migrations import migrate_database
from .models import (
    Artifact,
    Cell,
    CellExecution,
    ColumnDefinition,
    EncryptedSecret,
    ExecutionDependency,
    Grid,
    GridRow,
    Provenance,
    ProviderProfile,
    Run,
    RunEvent,
    RunTask,
    Template,
    utcnow,
)
from .providers import require_provider, seed_builtin_providers, validate_provider_endpoint
from .schemas import (
    BulkImportRows,
    ColumnIn,
    ColumnPatch,
    GridCreate,
    GridPatch,
    ImportRows,
    InputCellPatch,
    ProviderCreate,
    ProviderCredentialIn,
    ProviderPatch,
    RowCreate,
    RunCreate,
    SchemaDraft,
    SecretIn,
    TemplateImport,
)
from .secrets import SecretVault
from .template import TemplateValidationError, load_template, parse_template, validate_dag

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = ROOT / "templates"
STANDARD_SECRETS = ["github_token", "anthropic_api_key", "openai_api_key"]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    migrate_database()
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


@app.exception_handler(HTTPException)
async def structured_http_error(_request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict):
        payload = {
            "code": str(detail.get("code", f"http_{exc.status_code}")),
            "safe_message": str(detail.get("safe_message", "Request failed")),
            **{key: value for key, value in detail.items() if key not in {"code", "safe_message"}},
        }
    else:
        payload = {"code": f"http_{exc.status_code}", "safe_message": str(detail)}
    return JSONResponse(payload, status_code=exc.status_code, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def structured_validation_error(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        {
            "code": "request_validation_failed",
            "safe_message": "Request data did not match the API contract",
            "errors": jsonable_encoder(exc.errors()),
        },
        status_code=422,
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0"}


@app.get("/v1/grids")
def list_grids(session: DbSession) -> list[dict[str, Any]]:
    grids = session.scalars(select(Grid).order_by(Grid.updated_at.desc())).all()
    return [serialize_grid_summary(session, grid) for grid in grids]


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


@app.patch("/v1/grids/{grid_id}")
def patch_grid(grid_id: str, payload: GridPatch, session: DbSession) -> dict[str, Any]:
    grid = require_grid(session, grid_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(grid, key, value)
    session.commit()
    return serialize_grid(session, grid)


@app.delete("/v1/grids/{grid_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_grid(grid_id: str, session: DbSession) -> Response:
    grid = require_grid(session, grid_id)
    if session.scalar(
        select(func.count())
        .select_from(Run)
        .where(Run.grid_id == grid_id, Run.status.in_(["queued", "running", "paused", "cancelling"]))
    ):
        raise HTTPException(409, "Cancel the active run before deleting this grid")
    cell_ids = select(Cell.id).join(GridRow).where(GridRow.grid_id == grid_id)
    run_ids = select(Run.id).where(Run.grid_id == grid_id)
    execution_ids = list(
        session.scalars(
            select(CellExecution.id).where(
                or_(CellExecution.cell_id.in_(cell_ids), CellExecution.run_id.in_(run_ids))
            )
        )
    )
    if execution_ids:
        # Break projection/cache references before deleting immutable history. Some
        # executions can be reused across runs, so database cascade order alone is
        # insufficient for a complete grid deletion.
        session.execute(
            update(Cell)
            .where(Cell.latest_execution_id.in_(execution_ids))
            .values(latest_execution_id=None)
        )
        session.execute(
            update(RunTask)
            .where(RunTask.execution_id.in_(execution_ids))
            .values(execution_id=None)
        )
        session.execute(
            update(CellExecution)
            .where(CellExecution.reused_from_execution_id.in_(execution_ids))
            .values(reused_from_execution_id=None)
        )
        session.execute(
            delete(ExecutionDependency).where(
                or_(
                    ExecutionDependency.execution_id.in_(execution_ids),
                    ExecutionDependency.upstream_execution_id.in_(execution_ids),
                )
            )
        )
        session.execute(delete(CellExecution).where(CellExecution.id.in_(execution_ids)))
    session.delete(grid)
    session.commit()
    return Response(status_code=204)


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


@app.post("/v1/grids/{grid_id}/rows/{row_id}")
def create_row_compat(grid_id: str, row_id: str, payload: RowCreate, session: DbSession) -> dict[str, Any]:
    """Compatibility form for the published row route; row_id must be 'new'."""
    if row_id != "new":
        raise HTTPException(409, "Use row_id=new when creating a row")
    return create_row(grid_id, payload, session)


@app.post("/v1/grids/{grid_id}/rows/{row_id}/clone", status_code=status.HTTP_201_CREATED)
def clone_row(grid_id: str, row_id: str, session: DbSession) -> dict[str, Any]:
    grid = require_grid(session, grid_id)
    source = session.scalar(select(GridRow).where(GridRow.id == row_id, GridRow.grid_id == grid_id))
    if not source:
        raise HTTPException(404, "Row not found")
    if active_run_exists(session, grid_id):
        raise HTTPException(409, "Rows cannot change during an active run")
    position = session.scalar(select(func.count()).select_from(GridRow).where(GridRow.grid_id == grid_id)) or 0
    clone = GridRow(grid_id=grid_id, position=position)
    session.add(clone)
    session.flush()
    by_column = {cell.column_id: cell for cell in source.cells}
    for column in grid.columns:
        original = by_column.get(column.id)
        if column.kind == "input" and original:
            cell = Cell(row_id=clone.id, column_id=column.id, status="succeeded", value=original.value)
            session.add(cell)
            session.flush()
            set_input_value(session, cell, str(original.value), imported=True)
        else:
            session.add(Cell(row_id=clone.id, column_id=column.id, status="empty"))
    session.commit()
    return serialize_grid(session, grid)


@app.post("/v1/grids/{grid_id}/rows", status_code=status.HTTP_201_CREATED)
def create_row(grid_id: str, payload: RowCreate, session: DbSession) -> dict[str, Any]:
    grid = require_grid(session, grid_id)
    input_column = first_input_column(session, grid_id)
    before = len(grid.rows)
    add_rows(session, grid, input_column, [payload.value], normalize=False)
    session.commit()
    session.refresh(grid)
    if len(grid.rows) == before:
        raise HTTPException(409, "This input already exists")
    return serialize_grid(session, grid)


@app.delete("/v1/grids/{grid_id}/rows/{row_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_row(grid_id: str, row_id: str, session: DbSession) -> Response:
    require_grid(session, grid_id)
    row = session.scalar(select(GridRow).where(GridRow.id == row_id, GridRow.grid_id == grid_id))
    if not row:
        raise HTTPException(404, "Row not found")
    if active_run_exists(session, grid_id):
        raise HTTPException(409, "Rows cannot change during an active run")
    session.delete(row)
    session.flush()
    compact_row_positions(session, grid_id)
    session.commit()
    return Response(status_code=204)


@app.patch("/v1/grids/{grid_id}/rows/{row_id}/cells/{column_id}")
def patch_input_cell(
    grid_id: str,
    row_id: str,
    column_id: str,
    payload: InputCellPatch,
    session: DbSession,
) -> dict[str, Any]:
    if active_run_exists(session, grid_id):
        raise HTTPException(409, "Cells cannot change during an active run")
    cell = session.scalar(
        select(Cell)
        .join(GridRow)
        .join(ColumnDefinition, Cell.column_id == ColumnDefinition.id)
        .where(
            GridRow.grid_id == grid_id,
            GridRow.id == row_id,
            Cell.column_id == column_id,
            ColumnDefinition.kind == "input",
        )
    )
    if not cell:
        raise HTTPException(404, "Editable input cell not found")
    set_input_value(session, cell, payload.value, imported=False)
    downstream = session.scalars(
        select(Cell)
        .join(ColumnDefinition, Cell.column_id == ColumnDefinition.id)
        .where(Cell.row_id == row_id, ColumnDefinition.kind != "input")
    ).all()
    for item in downstream:
        item.status = "stale"
        item.error = None
    session.commit()
    return serialize_cell(cell)


@app.post("/v1/grids/{grid_id}/rows:import")
def import_mapped_rows(grid_id: str, payload: BulkImportRows, session: DbSession) -> dict[str, Any]:
    grid = require_grid(session, grid_id)
    input_column = first_input_column(session, grid_id)
    existing_cells = session.scalars(
        select(Cell)
        .join(GridRow)
        .where(GridRow.grid_id == grid_id, Cell.column_id == input_column.id)
    ).all()
    existing = {str(cell.value): cell for cell in existing_cells}
    report: list[dict[str, Any]] = []
    for index, item in enumerate(payload.rows):
        raw = item.get(input_column.key)
        if not isinstance(raw, str) or not raw.strip():
            report.append({"index": index, "status": "error", "error": f"Missing {input_column.key}"})
            continue
        value = raw.strip()
        if value in existing and payload.duplicate_strategy == "skip":
            report.append({"index": index, "status": "skipped", "reason": "duplicate"})
            continue
        if value in existing and payload.duplicate_strategy == "replace":
            set_input_value(session, existing[value], value, imported=True)
            report.append({"index": index, "status": "replaced", "row_id": existing[value].row_id})
            continue
        added = add_rows(session, grid, input_column, [value], normalize=False, allow_duplicate=True)
        report.append({"index": index, "status": "imported" if added else "skipped"})
    session.commit()
    counts = {name: sum(item["status"] == name for item in report) for name in {x["status"] for x in report}}
    return {"total": len(report), "counts": counts, "rows": report}


@app.post("/v1/grids/{grid_id}/columns", status_code=status.HTTP_201_CREATED)
def add_column(grid_id: str, payload: ColumnIn, session: DbSession) -> dict[str, Any]:
    grid = require_grid(session, grid_id)
    if active_run_exists(session, grid_id):
        raise HTTPException(409, "Schema cannot change during an active run")
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
    grid.schema_version += 1
    session.commit()
    return serialize_grid(session, grid)


@app.patch("/v1/grids/{grid_id}/columns/{column_id}")
def patch_column(grid_id: str, column_id: str, payload: ColumnPatch, session: DbSession) -> dict[str, Any]:
    grid = require_grid(session, grid_id)
    if active_run_exists(session, grid_id):
        raise HTTPException(409, "Schema cannot change during an active run")
    column = session.scalar(
        select(ColumnDefinition).where(ColumnDefinition.id == column_id, ColumnDefinition.grid_id == grid_id)
    )
    if not column:
        raise HTTPException(404, "Column not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(column, key, value)
    validate_grid_dag(session, grid_id)
    grid.schema_version += 1
    session.commit()
    return serialize_grid(session, grid)


@app.delete("/v1/grids/{grid_id}/columns/{column_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_column(grid_id: str, column_id: str, session: DbSession) -> Response:
    grid = require_grid(session, grid_id)
    if active_run_exists(session, grid_id):
        raise HTTPException(409, "Schema cannot change during an active run")
    column = session.scalar(
        select(ColumnDefinition).where(ColumnDefinition.id == column_id, ColumnDefinition.grid_id == grid_id)
    )
    if not column:
        raise HTTPException(404, "Column not found")
    dependents = session.scalars(select(ColumnDefinition).where(ColumnDefinition.grid_id == grid_id)).all()
    if any(column.key in item.depends_on for item in dependents):
        raise HTTPException(409, "Remove dependent columns first")
    session.delete(column)
    grid.schema_version += 1
    session.commit()
    return Response(status_code=204)


@app.post("/v1/grids/{grid_id}/columns/{column_id}/clone", status_code=status.HTTP_201_CREATED)
def clone_column(grid_id: str, column_id: str, session: DbSession) -> dict[str, Any]:
    grid = require_grid(session, grid_id)
    if active_run_exists(session, grid_id):
        raise HTTPException(409, "Schema cannot change during an active run")
    source = session.scalar(
        select(ColumnDefinition).where(
            ColumnDefinition.id == column_id, ColumnDefinition.grid_id == grid_id
        )
    )
    if not source:
        raise HTTPException(404, "Column not found")
    key = f"{source.key}_copy"
    existing_keys = {column.key for column in grid.columns}
    while key in existing_keys:
        key += "_copy"
    clone = ColumnDefinition(
        grid_id=grid_id,
        key=key,
        label=f"{source.label} copy",
        kind=source.kind,
        position=len(grid.columns),
        width=source.width,
        depends_on=list(source.depends_on),
        config=dict(source.config),
        prompt=source.prompt,
        output_schema=dict(source.output_schema),
    )
    session.add(clone)
    session.flush()
    for row in grid.rows:
        original = session.scalar(
            select(Cell).where(Cell.row_id == row.id, Cell.column_id == source.id)
        )
        if source.kind == "input" and original:
            cell = Cell(row_id=row.id, column_id=clone.id, status="succeeded", value=original.value)
            session.add(cell)
            session.flush()
            set_input_value(session, cell, str(original.value), imported=True)
        else:
            session.add(Cell(row_id=row.id, column_id=clone.id, status="empty"))
    grid.schema_version += 1
    session.commit()
    return serialize_grid(session, grid)


@app.post("/v1/grids/{grid_id}/schema/validate")
def validate_schema(grid_id: str, payload: SchemaDraft, session: DbSession) -> dict[str, Any]:
    require_grid(session, grid_id)
    validate_schema_columns(payload.columns)
    return {"valid": True, "schema_version": payload.schema_version}


@app.put("/v1/grids/{grid_id}/schema")
def save_schema(grid_id: str, payload: SchemaDraft, session: DbSession) -> dict[str, Any]:
    grid = require_grid(session, grid_id)
    if active_run_exists(session, grid_id):
        raise HTTPException(409, "Schema cannot change during an active run")
    if grid.schema_version != payload.schema_version:
        raise HTTPException(
            409,
            {
                "code": "schema_version_conflict",
                "safe_message": "The grid schema changed in another session. Reload before saving.",
                "current_version": grid.schema_version,
            },
        )
    validate_schema_columns(payload.columns)
    existing = {item.key: item for item in grid.columns}
    incoming_keys = {item.key for item in payload.columns}
    rows = session.scalars(select(GridRow).where(GridRow.grid_id == grid_id)).all()
    for position, definition in enumerate(payload.columns):
        values = definition.model_dump()
        column = existing.get(definition.key)
        if column is None:
            column = ColumnDefinition(grid_id=grid_id, position=position, **values)
            session.add(column)
            session.flush()
            for row in rows:
                session.add(Cell(row_id=row.id, column_id=column.id, status="empty"))
        else:
            if column.kind == "input" and definition.kind != "input":
                raise HTTPException(
                    422,
                    {
                        "code": "unsafe_kind_change",
                        "safe_message": "Changing an existing input column kind requires a new column key",
                    },
                )
            for key, value in values.items():
                setattr(column, key, value)
            column.position = position
    for key, column in existing.items():
        if key not in incoming_keys:
            session.delete(column)
    grid.canvas_layout = payload.canvas_layout
    grid.schema_version += 1
    session.commit()
    return serialize_grid(session, grid)


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
        run = create_run(session, grid_id, payload.budget_usd, force_refresh=payload.force_refresh)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    return serialize_run(run)


@app.get("/v1/runs/{run_id}")
def get_run(run_id: str, session: DbSession) -> dict[str, Any]:
    return serialize_run(require_run(session, run_id))


@app.get("/v1/grids/{grid_id}/runs")
def list_grid_runs(grid_id: str, session: DbSession) -> list[dict[str, Any]]:
    require_grid(session, grid_id)
    runs = session.scalars(select(Run).where(Run.grid_id == grid_id).order_by(Run.created_at.desc())).all()
    return [serialize_run(run) for run in runs]


@app.get("/v1/runs/{run_id}/results")
def run_results(run_id: str, session: DbSession) -> dict[str, Any]:
    run = require_run(session, run_id)
    executions = session.scalars(
        select(CellExecution)
        .options(selectinload(CellExecution.provenance))
        .where(CellExecution.run_id == run_id)
        .order_by(CellExecution.created_at)
    ).all()
    return {"run": serialize_run(run), "executions": [serialize_execution(item) for item in executions]}


@app.get("/v1/runs/{run_id}/events")
async def run_events(run_id: str, request: Request) -> StreamingResponse:
    async def stream():
        header = request.headers.get("last-event-id", "0")
        cursor = int(header) if header.isdigit() else 0
        while not await request.is_disconnected():
            with SessionLocal() as session:
                run = session.get(Run, run_id)
                if not run:
                    yield 'event: error\ndata: {"code":"run_not_found","safe_message":"Run not found"}\n\n'
                    return
                events = session.scalars(
                    select(RunEvent)
                    .where(RunEvent.run_id == run_id, RunEvent.id > cursor)
                    .order_by(RunEvent.id)
                    .limit(100)
                ).all()
                for item in events:
                    payload = json.dumps(
                        {**item.payload, "created_at": item.created_at.isoformat()}, default=str
                    )
                    yield f"id: {item.id}\nevent: {item.event_type}\ndata: {payload}\n\n"
                    cursor = item.id
                if not events:
                    yield ": keep-alive\n\n"
                if run.status in {"completed", "completed_with_errors", "failed", "cancelled"} and not events:
                    return
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.post("/v1/runs/{run_id}/pause")
def pause_run(run_id: str, session: DbSession) -> dict[str, Any]:
    run = require_run(session, run_id)
    if run.status not in {"queued", "running"}:
        raise HTTPException(409, "Only an active run can be paused")
    run.status = "paused"
    record_run_event(session, run.id, "run", serialize_run(run))
    session.commit()
    return serialize_run(run)


@app.post("/v1/runs/{run_id}/resume")
def resume_run(run_id: str, session: DbSession) -> dict[str, Any]:
    run = require_run(session, run_id)
    if run.status != "paused":
        raise HTTPException(409, "Run is not paused")
    run.status = "running" if run.started_at else "queued"
    record_run_event(session, run.id, "run", serialize_run(run))
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
        task.worker_id = None
        task.lease_expires_at = None
        execution = session.get(CellExecution, task.execution_id)
        if execution:
            execution.status = "cancelled"
            execution.error_code = "cancelled"
            execution.error_message = "Run was cancelled"
            execution.completed_at = utcnow()
        cell = session.scalar(
            select(Cell).where(Cell.row_id == task.row_id, Cell.column_id == task.column_id)
        )
        if cell:
            cell.status = "cancelled"
            cell.error = "Run was cancelled"
    if not session.scalar(
        select(func.count()).select_from(RunTask).where(RunTask.run_id == run_id, RunTask.status == "running")
    ):
        run.status = "cancelled"
        run.completed_at = utcnow()
    record_run_event(session, run.id, "run", serialize_run(run))
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
        cell = session.scalar(
            select(Cell).where(Cell.row_id == task.row_id, Cell.column_id == task.column_id)
        )
        if not cell:
            continue
        previous_execution = session.get(CellExecution, task.execution_id)
        if previous_execution:
            previous_execution.run_task_id = None
            session.flush()
        execution = CellExecution(
            cell_id=cell.id,
            row_position=cell.row.position,
            column_key=cell.column.key,
            column_label=cell.column.label,
            run_id=run.id,
            run_task_id=task.id,
            status="queued",
        )
        session.add(execution)
        session.flush()
        task.status = "queued"
        task.error = None
        task.available_at = utcnow()
        task.attempts = 0
        task.execution_id = execution.id
        cell.latest_execution_id = execution.id
        cell.status = "queued"
        cell.error = None
    run.status = "running"
    run.cancel_requested = False
    run.completed_at = None
    run.failed_tasks = 0
    run.skipped_tasks = 0
    record_run_event(session, run.id, "run", serialize_run(run))
    session.commit()
    return serialize_run(run)


@app.get("/v1/cells/{cell_id}/provenance")
def cell_provenance(
    cell_id: str, session: DbSession, execution_id: str | None = None
) -> dict[str, Any]:
    cell = session.get(Cell, cell_id)
    if not cell:
        raise HTTPException(404, "Cell not found")
    target_id = execution_id or cell.latest_execution_id
    provenance = session.scalar(select(Provenance).where(Provenance.execution_id == target_id))
    if not provenance:
        raise HTTPException(404, "Cell provenance not found")
    return serialize_provenance(provenance)


@app.get("/v1/cells/{cell_id}/history")
def cell_history(cell_id: str, session: DbSession) -> list[dict[str, Any]]:
    if not session.get(Cell, cell_id):
        raise HTTPException(404, "Cell not found")
    executions = session.scalars(
        select(CellExecution)
        .options(selectinload(CellExecution.provenance))
        .where(CellExecution.cell_id == cell_id)
        .order_by(CellExecution.created_at.desc())
    ).all()
    return [serialize_execution(item) for item in executions]


@app.get("/v1/artifacts/{artifact_hash}")
def get_artifact(artifact_hash: str, session: DbSession) -> FileResponse:
    artifact = session.get(Artifact, artifact_hash)
    if not artifact:
        raise HTTPException(404, "Artifact not found")
    path = (settings.artifacts_dir / artifact.path).resolve()
    if settings.artifacts_dir.resolve() not in path.parents or not path.exists():
        raise HTTPException(404, "Artifact file not found")
    safe_media = (
        artifact.content_type
        if artifact.content_type in {"application/json", "text/plain", "text/csv"}
        else "application/octet-stream"
    )
    return FileResponse(
        path,
        media_type=safe_media,
        filename=artifact_hash,
        content_disposition_type="attachment",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@app.get("/v1/grids/{grid_id}/export")
def export_grid(
    grid_id: str,
    session: DbSession,
    format: str = Query(pattern="^(csv|json)$"),
    run_id: str | None = None,
) -> Response:
    grid = require_grid(session, grid_id)
    serialized = serialize_grid_for_run(session, grid, run_id) if run_id else serialize_grid(session, grid)
    if format == "json":
        return JSONResponse(
            jsonable_encoder(serialized),
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


@app.get("/v1/providers")
def list_providers(session: DbSession) -> list[dict[str, Any]]:
    profiles = session.scalars(select(ProviderProfile).order_by(ProviderProfile.builtin.desc(), ProviderProfile.display_name)).all()
    vault = SecretVault()
    return [serialize_provider(item, vault.get(session, item.secret_name) is not None if item.secret_name else False) for item in profiles]


@app.post("/v1/providers", status_code=status.HTTP_201_CREATED)
async def create_provider(payload: ProviderCreate, session: DbSession) -> dict[str, Any]:
    if session.get(ProviderProfile, payload.id):
        raise HTTPException(409, "Provider profile already exists")
    try:
        base_url = await validate_provider_endpoint(payload.base_url, payload.credential_mode)
    except ValueError as exc:
        raise HTTPException(422, {"code": "unsafe_provider_url", "safe_message": str(exc)}) from exc
    profile = ProviderProfile(
        id=payload.id,
        provider_type="openai_compatible",
        display_name=payload.display_name,
        base_url=base_url,
        default_model=payload.default_model,
        structured_output_mode=payload.structured_output_mode,
        default_temperature=payload.default_temperature,
        credential_mode=payload.credential_mode,
        secret_name=f"provider:{payload.id}" if payload.credential_mode == "required" else None,
        trusted=True,
        builtin=False,
    )
    session.add(profile)
    session.commit()
    return serialize_provider(profile, False)


@app.patch("/v1/providers/{provider_id}")
async def patch_provider(
    provider_id: str, payload: ProviderPatch, session: DbSession
) -> dict[str, Any]:
    profile = require_provider(session, provider_id)
    if profile.builtin and any(key in payload.model_fields_set for key in ("base_url", "credential_mode")):
        raise HTTPException(409, "Built-in provider endpoints cannot be changed")
    values = payload.model_dump(exclude_unset=True)
    if (
        profile.provider_type == "anthropic"
        and values.get("structured_output_mode", profile.structured_output_mode) != "prompt_only"
    ):
        raise HTTPException(422, "Anthropic profiles require prompt_only structured output mode")
    credential_mode = values.get("credential_mode", profile.credential_mode)
    base_url = values.get("base_url", profile.base_url)
    try:
        values["base_url"] = await validate_provider_endpoint(base_url, credential_mode)
    except ValueError as exc:
        raise HTTPException(422, {"code": "unsafe_provider_url", "safe_message": str(exc)}) from exc
    for key, value in values.items():
        setattr(profile, key, value)
    if not profile.builtin:
        profile.secret_name = f"provider:{profile.id}" if credential_mode == "required" else None
    session.commit()
    configured = bool(profile.secret_name and SecretVault().get(session, profile.secret_name))
    return serialize_provider(profile, configured)


@app.delete("/v1/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_provider(provider_id: str, session: DbSession) -> Response:
    profile = require_provider(session, provider_id)
    if profile.builtin:
        raise HTTPException(409, "Built-in providers cannot be removed")
    references = session.scalars(select(ColumnDefinition).where(ColumnDefinition.kind == "llm")).all()
    if any(item.config.get("provider_ref") == provider_id for item in references):
        raise HTTPException(409, "Provider is referenced by a grid schema")
    if profile.secret_name:
        secret = session.scalar(select(EncryptedSecret).where(EncryptedSecret.name == profile.secret_name))
        if secret:
            session.delete(secret)
    session.delete(profile)
    session.commit()
    return Response(status_code=204)


@app.put("/v1/providers/{provider_id}/credential")
def put_provider_credential(
    provider_id: str, payload: ProviderCredentialIn, session: DbSession
) -> dict[str, Any]:
    profile = require_provider(session, provider_id)
    if profile.credential_mode != "required" or not profile.secret_name:
        raise HTTPException(409, "This provider does not use credentials")
    SecretVault().set(session, profile.secret_name, payload.value)
    session.commit()
    return {"id": profile.id, "configured": True}


def seed_workspace() -> None:
    with SessionLocal() as session:
        seed_builtin_providers(session)
        loaded: list[tuple[Any, str]] = []
        for path in sorted(TEMPLATES_DIR.glob("*.yaml")):
            template, document = load_template(path)
            loaded.append((template, document))
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
            template = next(item[0] for item in loaded if item[0].metadata.slug == "github-repository-radar")
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


def add_rows(
    session: Session,
    grid: Grid,
    input_column: ColumnDefinition,
    values: list[str],
    *,
    normalize: bool = True,
    allow_duplicate: bool = False,
) -> int:
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
        value = normalize_repo_value(raw) if normalize else raw.strip()
        if not value or (value in existing and not allow_duplicate):
            continue
        row = GridRow(grid_id=grid.id, position=position)
        session.add(row)
        session.flush()
        for column in columns:
            if column.id == input_column.id:
                cell = Cell(row_id=row.id, column_id=column.id, status="succeeded", value=value)
                session.add(cell)
                session.flush()
                set_input_value(session, cell, value, imported=True)
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


def set_input_value(session: Session, cell: Cell, value: str, *, imported: bool) -> CellExecution:
    execution = CellExecution(
        cell_id=cell.id,
        row_position=cell.row.position,
        column_key=cell.column.key,
        column_label=cell.column.label,
        status="succeeded",
        value=value,
        source_fetched_at=utcnow(),
        completed_at=utcnow(),
    )
    session.add(execution)
    session.flush()
    session.add(
        Provenance(
            execution_id=execution.id,
            legacy_cell_id=cell.id,
            connector="input",
            source_urls=[value] if value.startswith(("http://", "https://")) else [],
            duration_ms=0,
            cache_hit=False,
            metadata_json={"imported": imported},
        )
    )
    cell.value = value
    cell.status = "succeeded"
    cell.error = None
    cell.latest_execution_id = execution.id
    return execution


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


def validate_schema_columns(columns: list[ColumnIn]) -> None:
    document = {
        "apiVersion": "sourcedgrid/v1alpha1",
        "kind": "ResearchTemplate",
        "metadata": {"slug": "schema-draft", "name": "Schema draft", "version": "0"},
        "columns": [item.model_dump() for item in columns],
    }
    try:
        parsed = parse_template(json.dumps(document))
        validate_dag(parsed)
    except TemplateValidationError as exc:
        raise HTTPException(422, {"code": "invalid_schema", "safe_message": str(exc)}) from exc


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
            .options(selectinload(Cell.latest_execution).selectinload(CellExecution.provenance))
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
        "schema_version": grid.schema_version,
        "canvas_layout": grid.canvas_layout,
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
    execution = cell.latest_execution
    return {
        "id": cell.id,
        "column_id": cell.column_id,
        "status": cell.status,
        "value": cell.value,
        "error": cell.error,
        "latest_execution_id": cell.latest_execution_id,
        "provenance": (
            serialize_provenance(execution.provenance) if execution and execution.provenance else None
        ),
    }


def serialize_execution(item: CellExecution) -> dict[str, Any]:
    return {
        "id": item.id,
        "cell_id": item.cell_id,
        "row_position": item.row_position,
        "column_key": item.column_key,
        "column_label": item.column_label,
        "run_id": item.run_id,
        "run_task_id": item.run_task_id,
        "status": item.status,
        "value": item.value,
        "error": (
            {"code": item.error_code, "safe_message": item.error_message}
            if item.error_code or item.error_message
            else None
        ),
        "cache_key": item.cache_key,
        "source_fetched_at": item.source_fetched_at,
        "cache_expires_at": item.cache_expires_at,
        "reused_from_execution_id": item.reused_from_execution_id,
        "created_at": item.created_at,
        "completed_at": item.completed_at,
        "provenance": serialize_provenance(item.provenance) if item.provenance else None,
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
        "skipped_tasks": run.skipped_tasks,
        "cancelled_tasks": run.cancelled_tasks,
        "spent_usd": run.spent_usd,
        "reserved_usd": run.reserved_usd,
        "budget_usd": run.budget_usd,
        "force_refresh": run.force_refresh,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
    }


def serialize_grid_summary(session: Session, grid: Grid) -> dict[str, Any]:
    row_count = session.scalar(select(func.count()).select_from(GridRow).where(GridRow.grid_id == grid.id)) or 0
    last_run = session.scalar(select(Run).where(Run.grid_id == grid.id).order_by(Run.created_at.desc()))
    return {
        "id": grid.id,
        "name": grid.name,
        "description": grid.description,
        "template_slug": grid.template_slug,
        "schema_version": grid.schema_version,
        "row_count": row_count,
        "column_count": len(grid.columns),
        "last_run": serialize_run(last_run) if last_run else None,
        "updated_at": grid.updated_at,
    }


def serialize_provider(profile: ProviderProfile, configured: bool) -> dict[str, Any]:
    return {
        "id": profile.id,
        "provider_type": profile.provider_type,
        "display_name": profile.display_name,
        "base_url": profile.base_url,
        "default_model": profile.default_model,
        "structured_output_mode": profile.structured_output_mode,
        "default_temperature": profile.default_temperature,
        "credential_mode": profile.credential_mode,
        "trusted": profile.trusted,
        "builtin": profile.builtin,
        "configured": configured,
        "updated_at": profile.updated_at,
    }


def serialize_grid_for_run(session: Session, grid: Grid, run_id: str) -> dict[str, Any]:
    run = session.scalar(select(Run).where(Run.id == run_id, Run.grid_id == grid.id))
    if not run:
        raise HTTPException(404, "Run not found for this grid")
    executions = session.scalars(
        select(CellExecution)
        .options(selectinload(CellExecution.provenance))
        .where(CellExecution.run_id == run_id)
        .order_by(CellExecution.created_at)
    ).all()
    snapshot_columns = run.schema_snapshot.get("columns", [])
    columns = [
        {**item, "position": position}
        for position, item in enumerate(snapshot_columns)
    ]
    by_row: dict[int, list[CellExecution]] = {}
    for execution in executions:
        by_row.setdefault(execution.row_position, []).append(execution)
    order = {item["key"]: item["position"] for item in columns}
    return {
        "id": grid.id,
        "name": grid.name,
        "description": grid.description,
        "schema_version": run.schema_snapshot.get("schema_version"),
        "canvas_layout": run.schema_snapshot.get("canvas_layout", {}),
        "columns": columns,
        "rows": [
            {
                "id": f"run:{run.id}:row:{position}",
                "position": position,
                "cells": [
                    {
                        "id": item.cell_id or f"deleted:{item.id}",
                        "column_id": next(
                            (column.get("id") for column in columns if column["key"] == item.column_key),
                            item.column_key,
                        ),
                        "column_key": item.column_key,
                        "status": item.status,
                        "value": item.value,
                        "error": item.error_message,
                        "latest_execution_id": item.id,
                        "provenance": (
                            serialize_provenance(item.provenance) if item.provenance else None
                        ),
                    }
                    for item in sorted(by_row[position], key=lambda value: order.get(value.column_key, 9999))
                ],
            }
            for position in sorted(by_row)
        ],
        "run": serialize_run(run),
        "schema_snapshot": run.schema_snapshot,
    }


def active_run_exists(session: Session, grid_id: str) -> bool:
    return bool(
        session.scalar(
            select(func.count())
            .select_from(Run)
            .where(Run.grid_id == grid_id, Run.status.in_(["queued", "running", "paused", "cancelling"]))
        )
    )


def first_input_column(session: Session, grid_id: str) -> ColumnDefinition:
    column = session.scalar(
        select(ColumnDefinition)
        .where(ColumnDefinition.grid_id == grid_id, ColumnDefinition.kind == "input")
        .order_by(ColumnDefinition.position)
    )
    if not column:
        raise HTTPException(409, "Grid does not have an input column")
    return column


def compact_row_positions(session: Session, grid_id: str) -> None:
    rows = session.scalars(select(GridRow).where(GridRow.grid_id == grid_id).order_by(GridRow.position)).all()
    for position, row in enumerate(rows):
        row.position = position


def record_run_event(session: Session, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
    session.add(RunEvent(run_id=run_id, event_type=event_type, payload=jsonable_encoder(payload)))


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
