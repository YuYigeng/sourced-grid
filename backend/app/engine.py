from __future__ import annotations

import asyncio
import copy
import re
import socket
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, selectinload

from .artifacts import ArtifactStore
from .config import get_settings
from .connectors import GitHubConnector, LlmConnector, SafeHttpConnector, TransformConnector
from .connectors.base import ColumnSnapshot, ConnectorContext, ProviderSnapshot, stable_hash
from .connectors.github import GitHubNotModified, GitHubRateLimitError
from .db import SessionLocal
from .models import (
    Cell,
    CellExecution,
    ColumnDefinition,
    ExecutionDependency,
    Grid,
    GridRow,
    Provenance,
    ProviderProfile,
    Run,
    RunEvent,
    RunTask,
    utcnow,
)
from .schemas import CellResult
from .secrets import SecretVault

CONNECTORS = {
    "github": GitHubConnector(),
    "http": SafeHttpConnector(),
    "transform": TransformConnector(),
    "llm": LlmConnector(),
}
CACHE_TTL = {
    "github": timedelta(minutes=15),
    "http": timedelta(minutes=15),
    "llm": timedelta(hours=24),
    "transform": None,
}


@dataclass(frozen=True, slots=True)
class SafeFailure:
    code: str
    safe_message: str


def create_run(
    session: Session, grid_id: str, budget_usd: float, *, force_refresh: bool = False
) -> Run:
    grid = session.get(Grid, grid_id)
    rows = session.scalars(
        select(GridRow).where(GridRow.grid_id == grid_id).order_by(GridRow.position)
    ).all()
    columns = session.scalars(
        select(ColumnDefinition)
        .where(ColumnDefinition.grid_id == grid_id)
        .order_by(ColumnDefinition.position)
    ).all()
    if not grid or not rows:
        raise ValueError("Import at least one row before starting a run")
    non_input = [column for column in columns if column.kind != "input"]
    if not non_input:
        raise ValueError("Add at least one executable column before starting a run")
    schema_snapshot = {
        "schema_version": grid.schema_version,
        "canvas_layout": grid.canvas_layout,
        "columns": [
            {
                "id": item.id,
                "key": item.key,
                "label": item.label,
                "kind": item.kind,
                "position": item.position,
                "width": item.width,
                "depends_on": item.depends_on,
                "config": item.config,
                "prompt": item.prompt,
                "output_schema": item.output_schema,
            }
            for item in columns
        ],
    }
    run = Run(
        grid_id=grid_id,
        status="queued",
        budget_usd=budget_usd,
        force_refresh=force_refresh,
        schema_snapshot=schema_snapshot,
        total_tasks=len(rows) * len(non_input),
    )
    session.add(run)
    session.flush()
    for row in rows:
        cells = {
            cell.column_id: cell
            for cell in session.scalars(select(Cell).where(Cell.row_id == row.id)).all()
        }
        for column in columns:
            cell = cells.get(column.id)
            if cell is None:
                cell = Cell(row_id=row.id, column_id=column.id, status="empty")
                session.add(cell)
                session.flush()
            if column.kind == "input":
                clone_input_execution(session, run.id, cell)
                continue
            task = RunTask(run_id=run.id, row_id=row.id, column_id=column.id, status="queued")
            session.add(task)
            session.flush()
            execution = CellExecution(
                cell_id=cell.id,
                row_position=row.position,
                column_key=column.key,
                column_label=column.label,
                run_id=run.id,
                run_task_id=task.id,
                status="queued",
            )
            session.add(execution)
            session.flush()
            task.execution_id = execution.id
            cell.latest_execution_id = execution.id
            cell.status = "queued"
            cell.error = None
    record_event(session, run.id, "run", run_payload(run))
    session.commit()
    return run


def clone_input_execution(session: Session, run_id: str, cell: Cell) -> CellExecution:
    latest = session.get(CellExecution, cell.latest_execution_id) if cell.latest_execution_id else None
    execution = CellExecution(
        cell_id=cell.id,
        row_position=cell.row.position,
        column_key=cell.column.key,
        column_label=cell.column.label,
        run_id=run_id,
        status="succeeded",
        value=copy.deepcopy(cell.value),
        source_fetched_at=latest.source_fetched_at if latest else cell.updated_at,
        reused_from_execution_id=latest.id if latest else None,
        created_at=utcnow(),
        completed_at=utcnow(),
    )
    session.add(execution)
    session.flush()
    provenance = latest.provenance if latest else None
    session.add(
        Provenance(
            execution_id=execution.id,
            legacy_cell_id=cell.id,
            connector=provenance.connector if provenance else "input",
            source_urls=list(provenance.source_urls) if provenance else [],
            artifact_hash=provenance.artifact_hash if provenance else None,
            input_hash=provenance.input_hash if provenance else None,
            duration_ms=0,
            cache_hit=True,
            metadata_json={"run_input_snapshot": True},
        )
    )
    return execution


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
        recovered = 0
        with SessionLocal() as session:
            tasks = session.scalars(
                select(RunTask).where(
                    RunTask.status == "running", RunTask.lease_expires_at < now
                )
            ).all()
            for task in tasks:
                self._release_reservation(session, task)
                task.status = "queued"
                task.worker_id = None
                task.lease_expires_at = None
                task.available_at = now
                execution = session.get(CellExecution, task.execution_id) if task.execution_id else None
                if execution:
                    execution.status = "queued"
                cell = self._task_cell(session, task)
                if cell and cell.latest_execution_id == task.execution_id:
                    cell.status = "queued"
                record_event(session, task.run_id, "task", task_payload(task))
                recovered += 1
            session.commit()
        return recovered

    def reconcile_incomplete_runs(self) -> int:
        """Repair run summaries after a worker/process restart."""
        with SessionLocal() as session:
            run_ids = session.scalars(
                select(Run.id).where(Run.status.in_(["queued", "running", "cancelling"]))
            ).all()
            for run_id in run_ids:
                self._refresh_run(session, run_id)
            session.commit()
            return len(run_ids)

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
                    self._finish_without_result(
                        session,
                        task,
                        "dependency_failed",
                        "A dependency failed or was skipped",
                        "failed",
                    )
                    continue
                result = session.execute(
                    update(RunTask)
                    .where(RunTask.id == task.id, RunTask.status == "queued")
                    .values(
                        status="running",
                        attempts=RunTask.attempts + 1,
                        worker_id=self.worker_id,
                        lease_expires_at=now
                        + timedelta(seconds=self.settings.worker_lease_seconds),
                    )
                )
                if not result.rowcount:
                    continue
                session.flush()
                session.refresh(task)
                column = session.get(ColumnDefinition, task.column_id)
                if column and column.kind == "llm" and not self._reserve_budget(session, task, column):
                    self._finish_without_result(
                        session,
                        task,
                        "budget_exhausted",
                        "Estimated run budget is exhausted",
                        "skipped",
                    )
                    continue
                run = session.get(Run, task.run_id)
                if run and run.status == "queued":
                    run.status = "running"
                    run.started_at = now
                execution = session.get(CellExecution, task.execution_id)
                if execution:
                    execution.status = "running"
                cell = self._task_cell(session, task)
                if cell and cell.latest_execution_id == task.execution_id:
                    cell.status = "running"
                record_event(session, task.run_id, "task", task_payload(task))
                claimed.append(task.id)
            session.commit()
        return claimed

    def _dependencies_ready(self, session: Session, task: RunTask) -> str:
        column = session.get(ColumnDefinition, task.column_id)
        if not column or not column.depends_on:
            return "ready"
        rows = session.execute(
            select(ColumnDefinition.key, CellExecution.status)
            .join(Cell, Cell.column_id == ColumnDefinition.id)
            .join(CellExecution, CellExecution.cell_id == Cell.id)
            .where(
                Cell.row_id == task.row_id,
                CellExecution.run_id == task.run_id,
                ColumnDefinition.key.in_(column.depends_on),
            )
        ).all()
        statuses = dict(rows)
        if any(statuses.get(key) in {"failed", "cancelled", "skipped"} for key in column.depends_on):
            return "failed"
        if all(statuses.get(key) == "succeeded" for key in column.depends_on):
            return "ready"
        return "waiting"

    def retry_paused_budget_tasks(self, run_id: str) -> int:
        """Allow skipped budget tasks to run after the user raises the budget."""
        with SessionLocal() as session:
            tasks = session.scalars(
                select(RunTask).where(
                    RunTask.run_id == run_id,
                    RunTask.status == "skipped",
                    RunTask.error == "Estimated run budget is exhausted",
                )
            ).all()
            for task in tasks:
                task.status = "queued"
                task.error = None
                task.available_at = utcnow()
                execution = session.get(CellExecution, task.execution_id)
                if execution:
                    execution.status = "queued"
                    execution.error_code = None
                    execution.error_message = None
                    execution.completed_at = None
            if tasks:
                run = session.get(Run, run_id)
                if run:
                    run.status = "running"
                    run.completed_at = None
                session.commit()
            return len(tasks)

    def _reserve_budget(
        self, session: Session, task: RunTask, column: ColumnDefinition
    ) -> bool:
        estimate = max(0.0001, float(column.config.get("estimated_cost_usd", 0.05)))
        result = session.execute(
            update(Run)
            .where(
                Run.id == task.run_id,
                Run.spent_usd + Run.reserved_usd + estimate <= Run.budget_usd,
            )
            .values(reserved_usd=Run.reserved_usd + estimate)
        )
        if not result.rowcount:
            return False
        task.reserved_usd = estimate
        return True

    async def process_task(self, task_id: str) -> None:
        prepared = self._prepare_task(task_id)
        if prepared is None:
            return
        context, cache_key, cached_execution_id = prepared
        if cached_execution_id:
            self._reuse_cached(task_id, cache_key, cached_execution_id)
            return
        connector = CONNECTORS.get(context.column.kind)
        if connector is None:
            self._mark_failed(
                task_id,
                SafeFailure("connector_missing", f"No connector registered for {context.column.kind}"),
                retry=False,
            )
            return
        stop_heartbeat = asyncio.Event()
        heartbeat = asyncio.create_task(self._heartbeat(task_id, stop_heartbeat))
        try:
            result = await connector.execute(context)
            self._apply_result(task_id, result, cache_key)
        except GitHubRateLimitError as exc:
            self._reschedule_rate_limit(task_id, exc.retry_at)
        except GitHubNotModified:
            if context.prior_execution_id:
                self._reuse_not_modified(task_id, cache_key, context.prior_execution_id)
            else:
                self._mark_failed(
                    task_id,
                    SafeFailure("not_modified_without_cache", "Source returned 304 without cached evidence"),
                    retry=False,
                )
        except Exception as exc:  # noqa: BLE001 - isolate every task from the worker loop
            failure = safe_failure(exc, context.secrets.values())
            retry = not isinstance(exc, (ValueError, TypeError, PermissionError, FileNotFoundError))
            self._mark_failed(task_id, failure, retry=retry)
        finally:
            stop_heartbeat.set()
            await heartbeat

    def _prepare_task(self, task_id: str) -> tuple[ConnectorContext, str, str | None] | None:
        with SessionLocal() as session:
            task = session.scalar(
                select(RunTask)
                .options(selectinload(RunTask.run))
                .where(
                    RunTask.id == task_id,
                    RunTask.status == "running",
                    RunTask.worker_id == self.worker_id,
                )
            )
            if not task:
                return None
            run = task.run
            column = session.get(ColumnDefinition, task.column_id)
            cell = self._task_cell(session, task)
            execution = session.get(CellExecution, task.execution_id)
            if not column or not cell or not execution:
                session.rollback()
                self._mark_failed(
                    task_id,
                    SafeFailure("missing_task_data", "Task references missing data"),
                    retry=False,
                )
                return None
            if run.cancel_requested:
                self._finish_without_result(
                    session, task, "cancelled", "Run was cancelled", "cancelled"
                )
                session.commit()
                return None
            values, upstream = self._run_row_values(session, task.run_id, task.row_id)
            secrets: dict[str, str] = {}
            provider_snapshot: ProviderSnapshot | None = None
            if column.kind == "github":
                token = self.vault.get(session, "github_token")
                if token:
                    secrets["github_token"] = token
            elif column.kind == "llm":
                provider_ref = str(column.config.get("provider_ref", "anthropic"))
                provider = session.get(ProviderProfile, provider_ref)
                if not provider or not provider.trusted:
                    session.rollback()
                    self._mark_failed(
                        task_id,
                        SafeFailure(
                            "provider_untrusted",
                            f"Provider profile {provider_ref!r} is not locally trusted",
                        ),
                        retry=False,
                    )
                    return None
                provider_snapshot = ProviderSnapshot(
                    id=provider.id,
                    provider_type=provider.provider_type,
                    base_url=provider.base_url,
                    default_model=provider.default_model,
                    credential_mode=provider.credential_mode,
                )
                if provider.secret_name:
                    credential = self.vault.get(session, provider.secret_name)
                    if credential:
                        secrets["provider_credential"] = credential
            context = ConnectorContext(
                row_id=task.row_id,
                column=ColumnSnapshot(
                    key=column.key,
                    kind=column.kind,
                    depends_on=tuple(column.depends_on),
                    config=copy.deepcopy(column.config),
                    prompt=column.prompt,
                    output_schema=copy.deepcopy(column.output_schema),
                ),
                row_values=copy.deepcopy(values),
                upstream_execution_hashes=upstream,
                secrets=secrets,
                provider=provider_snapshot,
            )
            if column.kind == "github":
                prior = session.scalar(
                    select(CellExecution)
                    .options(selectinload(CellExecution.provenance))
                    .where(
                        CellExecution.cell_id == cell.id,
                        CellExecution.status == "succeeded",
                        CellExecution.id != execution.id,
                    )
                    .order_by(CellExecution.completed_at.desc())
                )
                if prior and prior.provenance:
                    context.prior_execution_id = prior.id
                    context.prior_etag = prior.provenance.metadata_json.get("repository_etag")
            connector = CONNECTORS.get(column.kind)
            if connector is None:
                return context, "", None
            cache_key = connector.fingerprint(context)
            task.cache_key = cache_key
            execution.cache_key = cache_key
            cached_id: str | None = None
            if not run.force_refresh:
                cached = session.scalar(
                    select(CellExecution)
                    .where(
                        CellExecution.cache_key == cache_key,
                        CellExecution.status == "succeeded",
                        CellExecution.id != execution.id,
                        or_(
                            CellExecution.cache_expires_at.is_(None),
                            CellExecution.cache_expires_at > utcnow(),
                        ),
                    )
                    .order_by(CellExecution.completed_at.desc())
                )
                cached_id = cached.id if cached else None
            session.commit()
            return context, cache_key, cached_id

    async def _heartbeat(self, task_id: str, stop: asyncio.Event) -> None:
        interval = max(1.0, min(30.0, self.settings.worker_lease_seconds / 3))
        while True:
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
                return
            except TimeoutError:
                with SessionLocal.begin() as session:
                    session.execute(
                        update(RunTask)
                        .where(
                            RunTask.id == task_id,
                            RunTask.status == "running",
                            RunTask.worker_id == self.worker_id,
                        )
                        .values(
                            lease_expires_at=utcnow()
                            + timedelta(seconds=self.settings.worker_lease_seconds)
                        )
                    )

    def _reuse_cached(self, task_id: str, cache_key: str, cached_id: str) -> None:
        with SessionLocal() as session:
            cached = session.scalar(
                select(CellExecution)
                .options(selectinload(CellExecution.provenance))
                .where(CellExecution.id == cached_id)
            )
            if not cached or not cached.provenance:
                return
            provenance = cached.provenance
            result = CellResult(
                value=copy.deepcopy(cached.value),
                connector=provenance.connector,
                source_urls=list(provenance.source_urls),
                input_hash=provenance.input_hash,
                model=provenance.model,
                prompt=provenance.prompt,
                input_tokens=provenance.input_tokens,
                output_tokens=provenance.output_tokens,
                cost_usd=0,
                duration_ms=0,
                cache_hit=True,
                metadata={**provenance.metadata_json, "cached_from_execution": cached.id},
            )
            artifact_hash = provenance.artifact_hash
        self._apply_result(
            task_id,
            result,
            cache_key,
            artifact_hash=artifact_hash,
            reused_from_execution_id=cached_id,
        )

    def _reuse_not_modified(self, task_id: str, cache_key: str, cached_id: str) -> None:
        with SessionLocal() as session:
            cached = session.scalar(
                select(CellExecution)
                .options(selectinload(CellExecution.provenance))
                .where(CellExecution.id == cached_id)
            )
            if not cached or not cached.provenance:
                return
            provenance = cached.provenance
            result = CellResult(
                value=copy.deepcopy(cached.value),
                connector=provenance.connector,
                source_urls=list(provenance.source_urls),
                input_hash=provenance.input_hash,
                model=provenance.model,
                prompt=provenance.prompt,
                input_tokens=provenance.input_tokens,
                output_tokens=provenance.output_tokens,
                cost_usd=0,
                duration_ms=0,
                cache_hit=True,
                metadata={**provenance.metadata_json, "conditional_request": "304"},
            )
            artifact_hash = provenance.artifact_hash
        self._apply_result(
            task_id,
            result,
            cache_key,
            artifact_hash=artifact_hash,
            reused_from_execution_id=cached_id,
            refresh_source_time=True,
        )

    def _apply_result(
        self,
        task_id: str,
        result: CellResult,
        cache_key: str,
        artifact_hash: str | None = None,
        reused_from_execution_id: str | None = None,
        refresh_source_time: bool = False,
    ) -> None:
        with SessionLocal() as session:
            task = session.scalar(
                select(RunTask).where(
                    RunTask.id == task_id,
                    RunTask.status == "running",
                    RunTask.worker_id == self.worker_id,
                )
            )
            if not task:
                return
            run = session.get(Run, task.run_id)
            cell = self._task_cell(session, task)
            execution = session.get(CellExecution, task.execution_id)
            column = session.get(ColumnDefinition, task.column_id)
            if not run or not cell or not execution or not column:
                return
            if run.cancel_requested or (
                task.lease_expires_at and normalize_datetime(task.lease_expires_at) < utcnow()
            ):
                self._finish_without_result(
                    session, task, "cancelled", "Late result discarded after cancellation or lease loss", "cancelled"
                )
                session.commit()
                return
            if result.artifact_content is not None:
                artifact_hash = self.artifacts.put(
                    session, result.artifact_content, result.artifact_content_type
                )
            now = utcnow()
            execution.status = "succeeded"
            execution.value = result.value
            execution.error_code = None
            execution.error_message = None
            execution.cache_key = cache_key
            if refresh_source_time or not reused_from_execution_id:
                execution.source_fetched_at = now
            else:
                reused = session.get(CellExecution, reused_from_execution_id)
                execution.source_fetched_at = reused.source_fetched_at if reused else None
            ttl = CACHE_TTL[column.kind]
            execution.cache_expires_at = now + ttl if ttl else None
            execution.reused_from_execution_id = reused_from_execution_id
            execution.completed_at = now
            session.add(
                Provenance(
                    execution_id=execution.id,
                    legacy_cell_id=cell.id,
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
            self._write_dependencies(session, task, execution)
            if cell.latest_execution_id == execution.id:
                cell.value = result.value
                cell.status = "succeeded"
                cell.error = None
                cell.cache_key = cache_key
            task.status = "succeeded"
            task.error = None
            task.lease_expires_at = None
            task.worker_id = None
            self._settle_reservation(session, task, result.cost_usd)
            self._refresh_run(session, run.id)
            record_event(session, run.id, "task", task_payload(task))
            session.commit()

    def _write_dependencies(
        self, session: Session, task: RunTask, execution: CellExecution
    ) -> None:
        column = session.get(ColumnDefinition, task.column_id)
        if not column:
            return
        upstream = session.execute(
            select(ColumnDefinition.key, CellExecution.id)
            .join(Cell, Cell.column_id == ColumnDefinition.id)
            .join(CellExecution, CellExecution.cell_id == Cell.id)
            .where(
                Cell.row_id == task.row_id,
                CellExecution.run_id == task.run_id,
                ColumnDefinition.key.in_(column.depends_on),
                CellExecution.status == "succeeded",
            )
        ).all()
        for key, upstream_id in upstream:
            session.add(
                ExecutionDependency(
                    execution_id=execution.id,
                    upstream_execution_id=upstream_id,
                    column_key=key,
                )
            )

    def _mark_failed(self, task_id: str, failure: SafeFailure, *, retry: bool) -> None:
        with SessionLocal() as session:
            task = session.scalar(
                select(RunTask).where(
                    RunTask.id == task_id,
                    RunTask.status == "running",
                    RunTask.worker_id == self.worker_id,
                )
            )
            if not task:
                return
            run = session.get(Run, task.run_id)
            if run and run.cancel_requested:
                retry = False
                failure = SafeFailure("cancelled", "Run was cancelled")
            task.error = failure.safe_message
            task.lease_expires_at = None
            task.worker_id = None
            execution = session.get(CellExecution, task.execution_id)
            cell = self._task_cell(session, task)
            self._release_reservation(session, task)
            if retry and task.attempts < task.max_attempts:
                task.status = "queued"
                task.available_at = utcnow() + timedelta(seconds=min(30, 2**task.attempts))
                if execution:
                    execution.status = "queued"
                    execution.error_code = failure.code
                    execution.error_message = failure.safe_message
                if cell and cell.latest_execution_id == task.execution_id:
                    cell.status = "queued"
                    cell.error = failure.safe_message
            else:
                final_status = "cancelled" if failure.code == "cancelled" else "failed"
                task.status = final_status
                if execution:
                    execution.status = final_status
                    execution.error_code = failure.code
                    execution.error_message = failure.safe_message
                    execution.completed_at = utcnow()
                if cell and cell.latest_execution_id == task.execution_id:
                    cell.status = final_status
                    cell.error = failure.safe_message
            self._refresh_run(session, task.run_id)
            record_event(session, task.run_id, "task", task_payload(task))
            session.commit()

    def _reschedule_rate_limit(self, task_id: str, retry_at: datetime) -> None:
        with SessionLocal() as session:
            task = session.scalar(
                select(RunTask).where(
                    RunTask.id == task_id,
                    RunTask.status == "running",
                    RunTask.worker_id == self.worker_id,
                )
            )
            if not task:
                return
            task.status = "queued"
            task.attempts = max(0, task.attempts - 1)
            task.available_at = retry_at
            task.lease_expires_at = None
            task.worker_id = None
            task.error = "GitHub rate limit reached; waiting for reset"
            execution = session.get(CellExecution, task.execution_id)
            if execution:
                execution.status = "queued"
                execution.error_code = "github_rate_limited"
                execution.error_message = task.error
            record_event(
                session,
                task.run_id,
                "rate_limit",
                {"task_id": task.id, "retry_at": retry_at.isoformat()},
            )
            session.commit()

    def _finish_without_result(
        self,
        session: Session,
        task: RunTask,
        code: str,
        message: str,
        final_status: str,
    ) -> None:
        task.status = final_status
        task.error = message
        task.worker_id = None
        task.lease_expires_at = None
        execution = session.get(CellExecution, task.execution_id)
        if execution:
            execution.status = final_status
            execution.error_code = code
            execution.error_message = message
            execution.completed_at = utcnow()
        cell = self._task_cell(session, task)
        if cell and cell.latest_execution_id == task.execution_id:
            cell.status = final_status
            cell.error = message
        self._release_reservation(session, task)
        self._refresh_run(session, task.run_id)
        record_event(session, task.run_id, "task", task_payload(task))

    def _settle_reservation(self, session: Session, task: RunTask, actual_cost: float) -> None:
        run = session.get(Run, task.run_id)
        if not run:
            return
        run.reserved_usd = max(0.0, round(run.reserved_usd - task.reserved_usd, 8))
        run.spent_usd = round(run.spent_usd + actual_cost, 8)
        task.reserved_usd = 0

    def _release_reservation(self, session: Session, task: RunTask) -> None:
        if not task.reserved_usd:
            return
        run = session.get(Run, task.run_id)
        if run:
            run.reserved_usd = max(0.0, round(run.reserved_usd - task.reserved_usd, 8))
        task.reserved_usd = 0

    def _refresh_run(self, session: Session, run_id: str) -> None:
        run = session.get(Run, run_id)
        if not run:
            return
        session.flush()
        counts = dict(
            session.execute(
                select(RunTask.status, func.count())
                .where(RunTask.run_id == run_id)
                .group_by(RunTask.status)
            ).all()
        )
        run.completed_tasks = int(counts.get("succeeded", 0))
        run.failed_tasks = int(counts.get("failed", 0))
        run.skipped_tasks = int(counts.get("skipped", 0))
        run.cancelled_tasks = int(counts.get("cancelled", 0))
        terminal = (
            run.completed_tasks + run.failed_tasks + run.skipped_tasks + run.cancelled_tasks
        )
        if terminal >= run.total_tasks:
            run.completed_at = utcnow()
            if run.cancel_requested or run.cancelled_tasks:
                run.status = "cancelled"
            elif run.failed_tasks or run.skipped_tasks:
                run.status = "completed_with_errors"
            else:
                run.status = "completed"
            record_event(session, run.id, "run", run_payload(run))

    @staticmethod
    def _task_cell(session: Session, task: RunTask) -> Cell | None:
        return session.scalar(
            select(Cell).where(Cell.row_id == task.row_id, Cell.column_id == task.column_id)
        )

    @staticmethod
    def _run_row_values(
        session: Session, run_id: str, row_id: str
    ) -> tuple[dict[str, Any], dict[str, str]]:
        rows = session.execute(
            select(ColumnDefinition.key, CellExecution.id, CellExecution.value)
            .join(Cell, Cell.column_id == ColumnDefinition.id)
            .join(CellExecution, CellExecution.cell_id == Cell.id)
            .where(
                Cell.row_id == row_id,
                CellExecution.run_id == run_id,
                CellExecution.status == "succeeded",
            )
        ).all()
        values = {key: value for key, _execution_id, value in rows}
        hashes = {key: stable_hash(value) for key, _execution_id, value in rows}
        return values, hashes


def record_event(session: Session, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
    session.add(RunEvent(run_id=run_id, event_type=event_type, payload=payload))


def task_payload(task: RunTask) -> dict[str, Any]:
    return {
        "task_id": task.id,
        "execution_id": task.execution_id,
        "row_id": task.row_id,
        "column_id": task.column_id,
        "status": task.status,
        "attempts": task.attempts,
        "error": task.error,
    }


def run_payload(run: Run) -> dict[str, Any]:
    return {
        "run_id": run.id,
        "status": run.status,
        "total_tasks": run.total_tasks,
        "completed_tasks": run.completed_tasks,
        "failed_tasks": run.failed_tasks,
        "skipped_tasks": run.skipped_tasks,
        "cancelled_tasks": run.cancelled_tasks,
        "spent_usd": run.spent_usd,
        "reserved_usd": run.reserved_usd,
    }


def normalize_datetime(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def safe_failure(exc: Exception, secret_values: Any = ()) -> SafeFailure:
    text = str(exc).strip() or exc.__class__.__name__
    for value in secret_values:
        if value:
            text = text.replace(str(value), "[redacted]")
    text = re.sub(
        r"(?i)(?:sk|gh[opsu]|github_pat|xox[baprs])[-_][A-Za-z0-9_-]{8,}",
        "[redacted]",
        text,
    )
    code = {
        ValueError: "invalid_result",
        TypeError: "invalid_input",
        PermissionError: "credential_rejected",
        FileNotFoundError: "source_not_found",
    }.get(type(exc), "connector_error")
    return SafeFailure(code, text[:1000])


def safe_error(exc: Exception) -> str:
    """Backward-compatible helper retained for external callers."""
    return safe_failure(exc).safe_message
