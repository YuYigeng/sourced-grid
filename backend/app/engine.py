from __future__ import annotations

import asyncio
import copy
import socket
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from .artifacts import ArtifactStore
from .config import get_settings
from .connectors import ConnectorContext, GitHubConnector, LlmConnector, SafeHttpConnector, TransformConnector
from .db import SessionLocal
from .models import Cell, ColumnDefinition, GridRow, Provenance, Run, RunTask, utcnow
from .schemas import CellResult
from .secrets import SecretVault

CONNECTORS = {
    "github": GitHubConnector(),
    "http": SafeHttpConnector(),
    "transform": TransformConnector(),
    "llm": LlmConnector(),
}


def create_run(session: Session, grid_id: str, budget_usd: float) -> Run:
    rows = session.scalars(select(GridRow).where(GridRow.grid_id == grid_id).order_by(GridRow.position)).all()
    columns = session.scalars(
        select(ColumnDefinition)
        .where(ColumnDefinition.grid_id == grid_id)
        .order_by(ColumnDefinition.position)
    ).all()
    if not rows:
        raise ValueError("Import at least one repository before starting a run")
    non_input = [column for column in columns if column.kind != "input"]
    run = Run(grid_id=grid_id, status="queued", budget_usd=budget_usd, total_tasks=len(rows) * len(non_input))
    session.add(run)
    session.flush()
    for row in rows:
        for column in non_input:
            session.add(RunTask(run_id=run.id, row_id=row.id, column_id=column.id, status="queued"))
            cell = session.scalar(select(Cell).where(Cell.row_id == row.id, Cell.column_id == column.id))
            if cell:
                cell.status = "queued"
                cell.error = None
            else:
                session.add(Cell(row_id=row.id, column_id=column.id, status="queued"))
    session.commit()
    return run


class ResearchWorker:
    def __init__(self, worker_id: str | None = None) -> None:
        self.settings = get_settings()
        self.worker_id = worker_id or f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
        self.vault = SecretVault()
        self.artifacts = ArtifactStore()
        self._stopping = False

    async def run_forever(self) -> None:
        semaphore = asyncio.Semaphore(self.settings.worker_concurrency)
        active: set[asyncio.Task[None]] = set()
        while not self._stopping:
            self.recover_expired_leases()
            claimed = self.claim_ready_tasks(max(0, self.settings.worker_concurrency - len(active)))
            for task_id in claimed:
                task = asyncio.create_task(self._bounded_process(task_id, semaphore))
                active.add(task)
                task.add_done_callback(active.discard)
            if not claimed:
                await asyncio.sleep(self.settings.worker_poll_seconds)
        if active:
            await asyncio.gather(*active, return_exceptions=True)

    async def _bounded_process(self, task_id: str, semaphore: asyncio.Semaphore) -> None:
        async with semaphore:
            await self.process_task(task_id)

    def stop(self) -> None:
        self._stopping = True

    def recover_expired_leases(self) -> int:
        now = utcnow()
        with SessionLocal.begin() as session:
            result = session.execute(
                update(RunTask)
                .where(RunTask.status == "running", RunTask.lease_expires_at < now)
                .values(status="queued", worker_id=None, lease_expires_at=None, available_at=now)
            )
            return int(result.rowcount or 0)

    def claim_ready_tasks(self, limit: int) -> list[str]:
        if limit <= 0:
            return []
        now = utcnow()
        claimed: list[str] = []
        with SessionLocal() as session:
            candidates = session.scalars(
                select(RunTask)
                .join(Run)
                .where(
                    RunTask.status == "queued",
                    RunTask.available_at <= now,
                    Run.status.in_(["queued", "running"]),
                    Run.cancel_requested.is_(False),
                )
                .order_by(RunTask.created_at)
                .limit(max(limit * 8, 20))
            ).all()
            for task in candidates:
                if len(claimed) >= limit:
                    break
                readiness = self._dependencies_ready(session, task)
                if readiness == "waiting":
                    continue
                if readiness == "failed":
                    self._fail_dependency(session, task)
                    continue
                result = session.execute(
                    update(RunTask)
                    .where(RunTask.id == task.id, RunTask.status == "queued")
                    .values(
                        status="running",
                        attempts=RunTask.attempts + 1,
                        worker_id=self.worker_id,
                        lease_expires_at=now + timedelta(seconds=self.settings.worker_lease_seconds),
                    )
                )
                if result.rowcount:
                    run = session.get(Run, task.run_id)
                    if run and run.status == "queued":
                        run.status = "running"
                        run.started_at = now
                    cell = session.scalar(
                        select(Cell).where(Cell.row_id == task.row_id, Cell.column_id == task.column_id)
                    )
                    if cell:
                        cell.status = "running"
                    claimed.append(task.id)
            session.commit()
        return claimed

    def _dependencies_ready(self, session: Session, task: RunTask) -> str:
        column = session.get(ColumnDefinition, task.column_id)
        if not column or not column.depends_on:
            return "ready"
        dependencies = session.scalars(
            select(Cell)
            .join(ColumnDefinition, Cell.column_id == ColumnDefinition.id)
            .where(Cell.row_id == task.row_id, ColumnDefinition.key.in_(column.depends_on))
        ).all()
        statuses = {cell.column.key: cell.status for cell in dependencies}
        if any(statuses.get(key) in {"failed", "cancelled", "skipped"} for key in column.depends_on):
            return "failed"
        if all(statuses.get(key) == "succeeded" for key in column.depends_on):
            return "ready"
        return "waiting"

    def _fail_dependency(self, session: Session, task: RunTask) -> None:
        task.status = "failed"
        task.error = "A dependency failed or was skipped"
        cell = session.scalar(
            select(Cell).where(Cell.row_id == task.row_id, Cell.column_id == task.column_id)
        )
        if cell:
            cell.status = "failed"
            cell.error = task.error
        self._refresh_run(session, task.run_id)

    async def process_task(self, task_id: str) -> None:
        with SessionLocal() as session:
            task = session.scalar(
                select(RunTask)
                .options(selectinload(RunTask.run))
                .where(
                    RunTask.id == task_id, RunTask.status == "running", RunTask.worker_id == self.worker_id
                )
            )
            if not task:
                return
            run = task.run
            column = session.get(ColumnDefinition, task.column_id)
            row = session.get(GridRow, task.row_id)
            cell = session.scalar(
                select(Cell).where(Cell.row_id == task.row_id, Cell.column_id == task.column_id)
            )
            if not column or not row or not cell:
                self._mark_failed(session, task, cell, "Task references missing data", retry=False)
                return
            if run.cancel_requested:
                self._mark_cancelled(session, task, cell)
                return
            if column.kind == "llm" and run.spent_usd >= run.budget_usd:
                task.status = "skipped"
                task.error = "Run budget exhausted"
                cell.status = "skipped"
                cell.error = task.error
                self._refresh_run(session, run.id)
                session.commit()
                return
            row_values = self._row_values(session, row.id)
            connector = CONNECTORS.get(column.kind)
            if connector is None:
                self._mark_failed(
                    session, task, cell, f"No connector registered for {column.kind}", retry=False
                )
                return
            context = ConnectorContext(
                session=session, row=row, column=column, row_values=row_values, vault=self.vault
            )
            cache_key = connector.fingerprint(context)
            task.cache_key = cache_key
            cached = session.scalar(
                select(Cell)
                .options(selectinload(Cell.provenance))
                .where(Cell.cache_key == cache_key, Cell.status == "succeeded", Cell.id != cell.id)
                .order_by(Cell.updated_at.desc())
            )
            if cell.status == "succeeded" and cell.cache_key == cache_key:
                task.status = "succeeded"
                self._refresh_run(session, run.id)
                session.commit()
                return
            if cached and cached.provenance:
                result = CellResult(
                    value=copy.deepcopy(cached.value),
                    connector=cached.provenance.connector,
                    source_urls=list(cached.provenance.source_urls),
                    input_hash=cached.provenance.input_hash,
                    model=cached.provenance.model,
                    prompt=cached.provenance.prompt,
                    input_tokens=cached.provenance.input_tokens,
                    output_tokens=cached.provenance.output_tokens,
                    cost_usd=0,
                    duration_ms=0,
                    cache_hit=True,
                    metadata={**cached.provenance.metadata_json, "cached_from_cell": cached.id},
                )
                self._apply_result(
                    session, run, task, cell, result, cache_key, cached.provenance.artifact_hash
                )
                session.commit()
                return
            try:
                result = await connector.execute(context)
                self._apply_result(session, run, task, cell, result, cache_key)
                session.commit()
            except Exception as exc:  # noqa: BLE001 - task failures must be isolated from the worker loop
                session.rollback()
                refreshed_task = session.get(RunTask, task_id)
                refreshed_cell = session.scalar(
                    select(Cell).where(Cell.row_id == task.row_id, Cell.column_id == task.column_id)
                )
                if refreshed_task:
                    retry = refreshed_task.attempts < refreshed_task.max_attempts and not isinstance(
                        exc, (ValueError, PermissionError, FileNotFoundError)
                    )
                    self._mark_failed(session, refreshed_task, refreshed_cell, safe_error(exc), retry=retry)

    def _apply_result(
        self,
        session: Session,
        run: Run,
        task: RunTask,
        cell: Cell,
        result: CellResult,
        cache_key: str,
        artifact_hash: str | None = None,
    ) -> None:
        if result.artifact_content is not None:
            artifact_hash = self.artifacts.put(session, result.artifact_content, result.artifact_content_type)
        if cell.provenance:
            session.delete(cell.provenance)
            session.flush()
        cell.value = result.value
        cell.status = "succeeded"
        cell.error = None
        cell.cache_key = cache_key
        task.status = "succeeded"
        task.error = None
        task.lease_expires_at = None
        session.add(
            Provenance(
                cell_id=cell.id,
                connector=result.connector,
                source_urls=result.source_urls,
                artifact_hash=artifact_hash,
                input_hash=result.input_hash,
                model=result.model,
                prompt=result.prompt,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cost_usd=result.cost_usd,
                duration_ms=result.duration_ms,
                cache_hit=result.cache_hit,
                metadata_json=result.metadata,
            )
        )
        run.spent_usd = round(run.spent_usd + result.cost_usd, 8)
        self._refresh_run(session, run.id)

    def _mark_failed(
        self, session: Session, task: RunTask, cell: Cell | None, error: str, retry: bool
    ) -> None:
        task.error = error
        task.lease_expires_at = None
        task.worker_id = None
        if retry:
            task.status = "queued"
            task.available_at = utcnow() + timedelta(seconds=min(30, 2**task.attempts))
            if cell:
                cell.status = "queued"
                cell.error = error
        else:
            task.status = "failed"
            if cell:
                cell.status = "failed"
                cell.error = error
        self._refresh_run(session, task.run_id)
        session.commit()

    def _mark_cancelled(self, session: Session, task: RunTask, cell: Cell) -> None:
        task.status = "cancelled"
        task.lease_expires_at = None
        cell.status = "cancelled"
        self._refresh_run(session, task.run_id)
        session.commit()

    def _refresh_run(self, session: Session, run_id: str) -> None:
        run = session.get(Run, run_id)
        if not run:
            return
        session.flush()
        counts = dict(
            session.execute(
                select(RunTask.status, func.count()).where(RunTask.run_id == run_id).group_by(RunTask.status)
            ).all()
        )
        run.completed_tasks = int(counts.get("succeeded", 0) + counts.get("skipped", 0))
        run.failed_tasks = int(counts.get("failed", 0))
        terminal = run.completed_tasks + run.failed_tasks + int(counts.get("cancelled", 0))
        if terminal >= run.total_tasks:
            run.completed_at = utcnow()
            if run.cancel_requested or counts.get("cancelled", 0):
                run.status = "cancelled"
            elif run.failed_tasks:
                run.status = "completed_with_errors"
            else:
                run.status = "completed"

    @staticmethod
    def _row_values(session: Session, row_id: str) -> dict[str, Any]:
        values = session.execute(
            select(ColumnDefinition.key, Cell.value)
            .join(Cell, Cell.column_id == ColumnDefinition.id)
            .where(Cell.row_id == row_id, Cell.status == "succeeded")
        ).all()
        return dict(values)


def safe_error(exc: Exception) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    # Avoid accidentally persisting provider keys embedded in upstream errors.
    return text[:1000].replace("sk-ant-", "[redacted]-").replace("sk-proj-", "[redacted]-")
