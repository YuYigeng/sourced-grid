from __future__ import annotations

from app.secrets import SecretVault


def test_secret_vault_round_trip_without_plaintext(tmp_path) -> None:
    vault = SecretVault(tmp_path / "master.key")
    encrypted = vault.encrypt("github_pat_super_secret")
    assert "super_secret" not in encrypted
    assert vault.decrypt(encrypted) == "github_pat_super_secret"
    assert (tmp_path / "master.key").stat().st_mode & 0o777 == 0o600
