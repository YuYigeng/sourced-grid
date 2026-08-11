from __future__ import annotations

from datetime import timedelta

from app.db import SessionLocal
from app.engine import ResearchWorker
from app.models import Cell, ColumnDefinition, Grid, GridRow, Run, RunTask, utcnow


def test_worker_recovers_an_expired_lease() -> None:
    with SessionLocal() as session:
        grid = Grid(name="Lease test")
        session.add(grid)
        session.flush()
        column = ColumnDefinition(grid_id=grid.id, key="value", label="Value", kind="transform", position=0)
        row = GridRow(grid_id=grid.id, position=0)
        session.add_all([column, row])
        session.flush()
        cell = Cell(row_id=row.id, column_id=column.id, status="running")
        run = Run(grid_id=grid.id, status="running", total_tasks=1)
        session.add_all([cell, run])
        session.flush()
        task = RunTask(
            run_id=run.id,
            row_id=row.id,
            column_id=column.id,
            status="running",
            worker_id="dead-worker",
            lease_expires_at=utcnow() - timedelta(seconds=5),
        )
        session.add(task)
        session.commit()
        task_id = task.id

    assert ResearchWorker("recovery-test").recover_expired_leases() >= 1
    with SessionLocal() as session:
        recovered = session.get(RunTask, task_id)
        assert recovered is not None
        assert recovered.status == "queued"
        assert recovered.worker_id is None
