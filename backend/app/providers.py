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
        "credential_mode": "required",
        "secret_name": "openai_api_key",
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
        for key, value in definition.items():
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
