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


def test_builtin_llm_providers_and_custom_capabilities() -> None:
    with TestClient(app) as client:
        providers = {item["id"]: item for item in client.get("/v1/providers").json()}
        assert {
            "anthropic",
            "openai",
            "deepseek",
            "qwen",
            "zhipu",
            "minimax",
            "siliconflow",
            "ollama",
        } <= set(providers)
        assert providers["deepseek"]["structured_output_mode"] == "json_object"
        assert providers["ollama"]["credential_mode"] == "none"

        secret = "provider-secret-never-returned"
        saved = client.put("/v1/providers/deepseek/credential", json={"value": secret})
        assert saved.status_code == 200
        assert saved.json() == {"id": "deepseek", "configured": True}
        assert secret not in client.get("/v1/providers").text

        created = client.post(
            "/v1/providers",
            json={
                "id": "custom-json",
                "display_name": "Custom JSON",
                "base_url": "http://127.0.0.1:12345/v1",
                "default_model": "local-model",
                "structured_output_mode": "prompt_only",
                "default_temperature": 0.7,
                "credential_mode": "none",
                "trusted": True,
            },
        )
        assert created.status_code == 201
        assert created.json()["structured_output_mode"] == "prompt_only"
        assert created.json()["default_temperature"] == 0.7

        patched = client.patch(
            "/v1/providers/custom-json",
            json={"structured_output_mode": "json_object", "default_temperature": 0.2},
        )
        assert patched.status_code == 200
        assert patched.json()["structured_output_mode"] == "json_object"
        assert patched.json()["default_temperature"] == 0.2

        incompatible = client.patch(
            "/v1/providers/anthropic", json={"structured_output_mode": "json_schema"}
        )
        assert incompatible.status_code == 422
