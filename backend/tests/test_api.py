from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_workspace_bootstrap_import_export_and_secret_redaction() -> None:
    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ok"
        grids = client.get("/v1/grids").json()
        assert grids[0]["name"] == "GitHub Repository Radar"
        grid_id = grids[0]["id"]
        before = grids[0]["row_count"]
        response = client.post(
            f"/v1/grids/{grid_id}/import",
            json={"values": ["encode/httpx", "encode/httpx"]},
        )
        assert response.status_code == 200
        assert len(response.json()["rows"]) == before + 1

        assert (
            client.put("/v1/secrets/github_token", json={"value": "token-never-returned"}).status_code == 200
        )
        serialized = client.get("/v1/secrets").text
        assert "token-never-returned" not in serialized
        assert '"configured":true' in serialized

        csv_response = client.get(f"/v1/grids/{grid_id}/export?format=csv")
        assert csv_response.status_code == 200
        assert "Repository" in csv_response.text
        json_response = client.get(f"/v1/grids/{grid_id}/export?format=json")
        assert json_response.status_code == 200
        assert json_response.json()["rows"][0]["cells"][0]["provenance"]["created_at"]


def test_template_endpoint_and_empty_grid_run_guard() -> None:
    with TestClient(app) as client:
        template = client.get("/v1/templates/github-repository-radar")
        assert template.status_code == 200
        assert "sourcedgrid/v1alpha1" in template.text
        empty = client.post("/v1/grids", json={"name": "Empty"}).json()
        response = client.post(f"/v1/grids/{empty['id']}/runs", json={"budget_usd": 1})
        assert response.status_code == 409
