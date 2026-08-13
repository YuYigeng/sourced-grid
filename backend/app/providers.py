from __future__ import annotations

from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from .connectors.http import validate_public_url
from .models import ProviderProfile

BUILTIN_PROVIDERS = (
    {
        "id": "anthropic",
        "provider_type": "anthropic",
        "display_name": "Anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "default_model": "claude-sonnet-4-5",
        "structured_output_mode": "prompt_only",
        "default_temperature": 0.0,
        "credential_mode": "required",
        "secret_name": "anthropic_api_key",
        "trusted": True,
        "builtin": True,
    },
    {
        "id": "openai",
        "provider_type": "openai_compatible",
        "display_name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-5-mini",
        "structured_output_mode": "json_schema",
        "default_temperature": 0.0,
        "credential_mode": "required",
        "secret_name": "openai_api_key",
        "trusted": True,
        "builtin": True,
    },
    {
        "id": "deepseek",
        "provider_type": "openai_compatible",
        "display_name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-v4-flash",
        "structured_output_mode": "json_object",
        "default_temperature": 0.0,
        "credential_mode": "required",
        "secret_name": "provider:deepseek",
        "trusted": True,
        "builtin": True,
    },
    {
        "id": "qwen",
        "provider_type": "openai_compatible",
        "display_name": "Alibaba Cloud Qwen",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
        "structured_output_mode": "json_object",
        "default_temperature": 0.0,
        "credential_mode": "required",
        "secret_name": "provider:qwen",
        "trusted": True,
        "builtin": True,
    },
    {
        "id": "zhipu",
        "provider_type": "openai_compatible",
        "display_name": "Zhipu GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-5.2",
        "structured_output_mode": "prompt_only",
        "default_temperature": 0.6,
        "credential_mode": "required",
        "secret_name": "provider:zhipu",
        "trusted": True,
        "builtin": True,
    },
    {
        "id": "minimax",
        "provider_type": "openai_compatible",
        "display_name": "MiniMax",
        "base_url": "https://api.minimaxi.com/v1",
        "default_model": "MiniMax-M2.7",
        "structured_output_mode": "prompt_only",
        "default_temperature": 1.0,
        "credential_mode": "required",
        "secret_name": "provider:minimax",
        "trusted": True,
        "builtin": True,
    },
    {
        "id": "siliconflow",
        "provider_type": "openai_compatible",
        "display_name": "SiliconFlow",
        "base_url": "https://api.siliconflow.cn/v1",
        "default_model": "Pro/zai-org/GLM-4.7",
        "structured_output_mode": "json_object",
        "default_temperature": 0.0,
        "credential_mode": "required",
        "secret_name": "provider:siliconflow",
        "trusted": True,
        "builtin": True,
    },
    {
        "id": "ollama",
        "provider_type": "openai_compatible",
        "display_name": "Ollama (local)",
        "base_url": "http://host.docker.internal:11434/v1",
        "default_model": "qwen3.5",
        "structured_output_mode": "json_schema",
        "default_temperature": 0.0,
        "credential_mode": "none",
        "secret_name": None,
        "trusted": True,
        "builtin": True,
    },
)


def seed_builtin_providers(session: Session) -> None:
    for definition in BUILTIN_PROVIDERS:
        profile = session.get(ProviderProfile, definition["id"])
        if profile is None:
            session.add(ProviderProfile(**definition))
            continue
        for key in (
            "provider_type",
            "display_name",
            "base_url",
            "credential_mode",
            "secret_name",
            "trusted",
            "builtin",
        ):
            value = definition[key]
            setattr(profile, key, value)


async def validate_provider_endpoint(base_url: str, credential_mode: str) -> str:
    normalized = base_url.rstrip("/")
    parsed = urlparse(normalized)
    if parsed.username or parsed.password:
        raise ValueError("Provider URLs containing credentials are not allowed")
    if credential_mode == "required":
        if parsed.scheme != "https":
            raise ValueError("Credentialed providers must use HTTPS")
        await validate_public_url(normalized)
    else:
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Provider URL must be absolute HTTP(S)")
    return normalized


def require_provider(session: Session, provider_ref: str) -> ProviderProfile:
    provider = session.scalar(select(ProviderProfile).where(ProviderProfile.id == provider_ref))
    if provider is None or not provider.trusted:
        raise ValueError(f"Provider profile {provider_ref!r} is not trusted")
    return provider
