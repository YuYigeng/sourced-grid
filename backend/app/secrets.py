from __future__ import annotations

import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import EncryptedSecret


class SecretVault:
    def __init__(self, key_path: Path | None = None) -> None:
        self.key_path = key_path or get_settings().master_key_path
        self.key = self._load_or_create_key()

    def _load_or_create_key(self) -> bytes:
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        if self.key_path.exists():
            key = self.key_path.read_bytes()
            if len(key) != 32:
                raise RuntimeError("Invalid SourcedGrid master key")
            return key
        key = AESGCM.generate_key(bit_length=256)
        descriptor = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(key)
        return key

    def encrypt(self, value: str) -> str:
        nonce = os.urandom(12)
        encrypted = AESGCM(self.key).encrypt(nonce, value.encode(), b"sourcedgrid/v1")
        return base64.urlsafe_b64encode(nonce + encrypted).decode()

    def decrypt(self, payload: str) -> str:
        raw = base64.urlsafe_b64decode(payload.encode())
        return AESGCM(self.key).decrypt(raw[:12], raw[12:], b"sourcedgrid/v1").decode()

    def set(self, session: Session, name: str, value: str) -> EncryptedSecret:
        secret = session.scalar(select(EncryptedSecret).where(EncryptedSecret.name == name))
        if secret is None:
            secret = EncryptedSecret(name=name, ciphertext=self.encrypt(value))
            session.add(secret)
        else:
            secret.ciphertext = self.encrypt(value)
        session.flush()
        return secret

    def get(self, session: Session, name: str) -> str | None:
        secret = session.scalar(select(EncryptedSecret).where(EncryptedSecret.name == name))
        return self.decrypt(secret.ciphertext) if secret else None
