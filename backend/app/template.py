from __future__ import annotations

from collections import deque
from pathlib import Path

import yaml

from .schemas import ResearchTemplate


class TemplateValidationError(ValueError):
    pass


def parse_template(document: str) -> ResearchTemplate:
    try:
        raw = yaml.safe_load(document)
        migrate_legacy_provider_refs(raw)
        template = ResearchTemplate.model_validate(raw)
    except Exception as exc:
        raise TemplateValidationError(str(exc)) from exc
    validate_dag(template)
    return template


def migrate_legacy_provider_refs(raw: object) -> None:
    if not isinstance(raw, dict) or not isinstance(raw.get("columns"), list):
        return
    for column in raw["columns"]:
        if not isinstance(column, dict) or column.get("kind") != "llm":
            continue
        config = column.setdefault("config", {})
        if not isinstance(config, dict) or "provider" not in config:
            continue
        provider = config.pop("provider")
        if provider not in {"anthropic", "openai"}:
            raise TemplateValidationError(
                "Legacy provider values must be anthropic or openai; create a trusted local profile for custom providers"
            )
        config.setdefault("provider_ref", provider)


def load_template(path: Path) -> tuple[ResearchTemplate, str]:
    document = path.read_text(encoding="utf-8")
    return parse_template(document), document


def validate_dag(template: ResearchTemplate) -> list[str]:
    keys = [column.key for column in template.columns]
    if len(keys) != len(set(keys)):
        raise TemplateValidationError("Template contains duplicate column keys")
    known = set(keys)
    for column in template.columns:
        if column.kind == "llm":
            forbidden = {"base_url", "secret_name", "api_key"} & set(column.config)
            if forbidden:
                raise TemplateValidationError(
                    f"LLM column {column.key} contains forbidden provider settings: {sorted(forbidden)}"
                )
            if "provider_ref" not in column.config:
                raise TemplateValidationError(f"LLM column {column.key} must reference a trusted provider_ref")
        missing = set(column.depends_on) - known
        if missing:
            raise TemplateValidationError(
                f"Column {column.key} depends on missing columns: {sorted(missing)}"
            )
        if column.key in column.depends_on:
            raise TemplateValidationError(f"Dependency cycle detected: column {column.key} depends on itself")

    indegree = {key: 0 for key in keys}
    outgoing: dict[str, list[str]] = {key: [] for key in keys}
    for column in template.columns:
        for dependency in column.depends_on:
            outgoing[dependency].append(column.key)
            indegree[column.key] += 1
    queue = deque(key for key in keys if indegree[key] == 0)
    ordered: list[str] = []
    while queue:
        key = queue.popleft()
        ordered.append(key)
        for next_key in outgoing[key]:
            indegree[next_key] -= 1
            if indegree[next_key] == 0:
                queue.append(next_key)
    if len(ordered) != len(keys):
        cycle = sorted(key for key, degree in indegree.items() if degree > 0)
        raise TemplateValidationError(f"Template dependency cycle detected: {cycle}")
    return ordered
