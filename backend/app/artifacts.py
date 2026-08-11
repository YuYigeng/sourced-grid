from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy.orm import Session

from .config import get_settings
from .models import Artifact


class ArtifactStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or get_settings().artifacts_dir
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, session: Session, content: str | bytes, content_type: str) -> str:
        payload = content.encode("utf-8") if isinstance(content, str) else content
        digest = hashlib.sha256(payload).hexdigest()
        relative = Path(digest[:2]) / digest[2:4] / digest
        destination = self.root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            destination.write_bytes(payload)
        if session.get(Artifact, digest) is None:
            session.add(
                Artifact(
                    hash=digest,
                    path=str(relative),
                    content_type=content_type,
                    byte_size=len(payload),
                )
            )
            session.flush()
        return digest
