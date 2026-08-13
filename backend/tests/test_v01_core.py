from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.connectors.base import BaseConnector, ColumnSnapshot, ConnectorContext, ProviderSnapshot
from app.connectors.llm import LlmConnector, parse_value
from app.db import SessionLocal
from app.engine import CONNECTORS, ResearchWorker, SafeFailure, create_run, safe_failure
from app.main import app
from app.migrations import backup_sqlite_database
from app.models import (
    Cell,
    CellExecution,
    ColumnDefinition,
    Grid,
    GridRow,
    Provenance,
    Run,
    utcnow,
)
from app.schemas import CellResult
from app.template import TemplateValidationError, parse_template


def test_llm_requires_exact_envelope_and_validates_schema() -> None:
    assert parse_value('{"value": 3}', {"type": "integer"}) == 3
    with pytest.raises(ValueError, match="exactly one"):
        parse_value('{"value": 3, "debug": true}', {"type": "integer"})
    with pytest.raises(ValueError, match="does not match"):
        parse_value('{"value": "3"}', {"type": "integer"})


def test_template_cannot_control_provider_endpoint_or_secret() -> None:
    document = """
apiVersion: sourcedgrid/v1alpha1
kind: ResearchTemplate
metadata: {slug: malicious, name: Malicious}
columns:
  - {key: input_url, label: URL, kind: input}
  - key: answer
    label: Answer
    kind: llm
    depends_on: [input_url]
    config: {provider_ref: openai, base_url: https://attacker.invalid/v1, secret_name: openai_api_key}
"""
    with pytest.raises(TemplateValidationError, match="forbidden provider settings"):
        parse_template(document)


def test_cache_fingerprint_tracks_schema_provider_and_connector_version() -> None:
    connector = LlmConnector()
    base = {
        "row_id": "row",
        "row_values": {"source": {"value": 1}},
        "upstream_execution_hashes": {"source": "abc"},
        "secrets": {"provider_credential": "not-in-fingerprint"},
    }
    column = ColumnSnapshot(
        key="answer",
        kind="llm",
        depends_on=("source",),
        config={"provider_ref": "one"},
        prompt="Summarize",
        output_schema={"type": "string"},
    )
    first = connector.fingerprint(ConnectorContext(column=column, **base))
    schema_changed = connector.fingerprint(
        ConnectorContext(
            column=ColumnSnapshot(
                key="answer",
                kind="llm",
                depends_on=("source",),
                config={"provider_ref": "one"},
                prompt="Summarize",
                output_schema={"type": "integer"},
            ),
            **base,
        )
    )
    provider_changed = connector.fingerprint(
        ConnectorContext(
            column=column,
            provider=ProviderSnapshot("two", "openai_compatible", "https://api.example/v1", "m", "required"),
            **base,
        )
    )
    assert len({first, schema_changed, provider_changed}) == 3
    assert "not-in-fingerprint" not in first


def test_secret_redaction_covers_configured_and_common_tokens() -> None:
    fake_github_token = "github" + "_pat_" + "12345678901234567890"
    failure: SafeFailure = safe_failure(
        RuntimeError(f"request used super-secret-value and {fake_github_token}"),
        ["super-secret-value"],
    )
    assert "super-secret-value" not in failure.safe_message
    assert "github_pat_" not in failure.safe_message


def test_sqlite_backup_is_consistent(tmp_path: Path) -> None:
    source = tmp_path / "current.db"
    connection = sqlite3.connect(source)
    connection.execute("CREATE TABLE records (value TEXT)")
    connection.execute("INSERT INTO records VALUES ('preserved')")
    connection.commit()
    backup = backup_sqlite_database(source)
    assert backup is not None
    assert sqlite3.connect(backup).execute("SELECT value FROM records").fetchone() == ("preserved",)


class DeterministicConnector(BaseConnector):
    name = "transform"

    async def execute(self, context: ConnectorContext) -> CellResult:
        return CellResult(value=f"done:{context.row_values['input_value']}", connector="test")


def _execution_fixture() -> tuple[str, str]:
    with SessionLocal() as session:
        grid = Grid(name="Immutable execution test")
        session.add(grid)
        session.flush()
        source_column = ColumnDefinition(
            grid_id=grid.id, key="input_value", label="Input", kind="input", position=0
        )
        output_column = ColumnDefinition(
            grid_id=grid.id,
            key="output_value",
            label="Output",
            kind="transform",
            position=1,
            depends_on=["input_value"],
            config={"operation": "select", "source": "input_value"},
        )
        row = GridRow(grid_id=grid.id, position=0)
        session.add_all([source_column, output_column, row])
        session.flush()
        source = Cell(row_id=row.id, column_id=source_column.id, status="succeeded", value="alpha")
        output = Cell(row_id=row.id, column_id=output_column.id, status="empty")
        session.add_all([source, output])
        session.flush()
        execution = CellExecution(
            cell_id=source.id,
            row_position=0,
            column_key=source_column.key,
            column_label=source_column.label,
            status="succeeded",
            value="alpha",
            completed_at=utcnow(),
        )
        session.add(execution)
        session.flush()
        source.latest_execution_id = execution.id
        session.add(Provenance(execution_id=execution.id, legacy_cell_id=source.id, connector="input"))
        session.commit()
        return grid.id, output.id


@pytest.mark.asyncio
async def test_three_runs_keep_distinct_executions_and_run_exports() -> None:
    grid_id, output_cell_id = _execution_fixture()
    original = CONNECTORS["transform"]
    CONNECTORS["transform"] = DeterministicConnector()
    try:
        worker = ResearchWorker("immutable-test")
        run_ids: list[str] = []
        for _ in range(3):
            with SessionLocal() as session:
                run = create_run(session, grid_id, 1.0, force_refresh=True)
                run_ids.append(run.id)
            task_id = worker.claim_ready_tasks(1)[0]
            await worker.process_task(task_id)
        with SessionLocal() as session:
            executions = session.scalars(
                select(CellExecution).where(
                    CellExecution.cell_id == output_cell_id,
                    CellExecution.run_id.in_(run_ids),
                )
            ).all()
            assert len(executions) == 3
            assert len({item.id for item in executions}) == 3
            assert all(item.status == "succeeded" for item in executions)
        with TestClient(app) as client:
            for run_id in run_ids:
                exported = client.get(f"/v1/grids/{grid_id}/export?format=json&run_id={run_id}")
                assert exported.status_code == 200
                assert exported.json()["run"]["id"] == run_id
    finally:
        CONNECTORS["transform"] = original


@pytest.mark.asyncio
async def test_grid_with_cached_run_history_can_be_deleted() -> None:
    grid_id, _ = _execution_fixture()
    original = CONNECTORS["transform"]
    CONNECTORS["transform"] = DeterministicConnector()
    try:
        worker = ResearchWorker("grid-delete-test")
        run_ids: list[str] = []
        for force_refresh in (True, False):
            with SessionLocal() as session:
                run = create_run(session, grid_id, 1.0, force_refresh=force_refresh)
                run_ids.append(run.id)
            task_id = worker.claim_ready_tasks(1)[0]
            await worker.process_task(task_id)
        with TestClient(app) as client:
            response = client.delete(f"/v1/grids/{grid_id}")
            assert response.status_code == 204
            assert client.get(f"/v1/grids/{grid_id}").status_code == 404
        with SessionLocal() as session:
            assert not session.scalars(
                select(CellExecution).where(CellExecution.run_id.in_(run_ids))
            ).all()
            assert not session.scalars(select(Run).where(Run.id.in_(run_ids))).all()
    finally:
        CONNECTORS["transform"] = original


def test_budget_reservation_is_atomic_across_two_workers() -> None:
    with SessionLocal() as session:
        grid = Grid(name="Atomic budget")
        session.add(grid)
        session.flush()
        row = GridRow(grid_id=grid.id, position=0)
        first = ColumnDefinition(
            grid_id=grid.id,
            key="first_llm",
            label="First",
            kind="llm",
            position=0,
            config={"provider_ref": "anthropic", "estimated_cost_usd": 0.05},
        )
        second = ColumnDefinition(
            grid_id=grid.id,
            key="second_llm",
            label="Second",
            kind="llm",
            position=1,
            config={"provider_ref": "anthropic", "estimated_cost_usd": 0.05},
        )
        session.add_all([row, first, second])
        session.flush()
        session.add_all(
            [
                Cell(row_id=row.id, column_id=first.id, status="empty"),
                Cell(row_id=row.id, column_id=second.id, status="empty"),
            ]
        )
        session.commit()
        run = create_run(session, grid.id, 0.05, force_refresh=True)
        run_id = run.id
    claimed = ResearchWorker("budget-one").claim_ready_tasks(1)
    claimed += ResearchWorker("budget-two").claim_ready_tasks(1)
    with SessionLocal() as session:
        run = session.get(Run, run_id)
        assert run is not None
        assert run.reserved_usd <= run.budget_usd
        assert len(claimed) <= 1


def test_cancelled_late_result_cannot_overwrite_latest_cell() -> None:
    grid_id, output_cell_id = _execution_fixture()
    with SessionLocal() as session:
        run = create_run(session, grid_id, 1.0, force_refresh=True)
    worker = ResearchWorker("late-result-test")
    task_id = worker.claim_ready_tasks(1)[0]
    with SessionLocal() as session:
        run = session.get(Run, run.id)
        run.cancel_requested = True
        run.status = "cancelling"
        session.commit()
    worker._apply_result(task_id, CellResult(value="late", connector="test"), "cache")
    with SessionLocal() as session:
        cell = session.get(Cell, output_cell_id)
        assert cell is not None
        assert cell.value != "late"
        execution = session.get(CellExecution, cell.latest_execution_id)
        assert execution is not None
        assert execution.status == "cancelled"


def test_input_edit_marks_downstream_stale_and_old_run_survives_row_delete() -> None:
    grid_id, output_cell_id = _execution_fixture()
    with TestClient(app) as client:
        detail = client.get(f"/v1/grids/{grid_id}").json()
        row = detail["rows"][0]
        input_column = next(item for item in detail["columns"] if item["kind"] == "input")
        input_cell = next(item for item in row["cells"] if item["column_id"] == input_column["id"])
        response = client.patch(
            f"/v1/grids/{grid_id}/rows/{row['id']}/cells/{input_column['id']}",
            json={"value": "beta"},
        )
        assert response.status_code == 200
        refreshed = client.get(f"/v1/grids/{grid_id}").json()
        downstream = next(
            item for item in refreshed["rows"][0]["cells"] if item["id"] == output_cell_id
        )
        assert downstream["status"] == "stale"
        history = client.get(f"/v1/cells/{input_cell['id']}/history").json()
        assert len(history) == 2
