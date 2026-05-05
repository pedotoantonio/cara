"""AES-256-GCM token encryption at rest.

OAuth refresh tokens have ~no TTL — if they leak from a DB dump they
grant unlimited access to a user's Google account. We never store them
in clear: every write goes through `encrypt_token()`, every read
through `decrypt_token()`.

Key source: `OAUTH_ENCRYPTION_KEY` in `.env` (urlsafe-base64, 32 bytes).
The key NEVER lives in the DB or in code. Rotation procedure (admin):

  1. generate a new key
  2. add it as OAUTH_ENCRYPTION_KEY_NEW alongside the existing one
  3. run `python -m cara.bootstrap rotate-oauth-keys` (re-encrypt every
     row with the new key)
  4. promote NEW → OAUTH_ENCRYPTION_KEY, drop the old
  5. restart backend

The migration script is left for follow-up; this module ships the
encrypt/decrypt round-trip plus a one-shot self-test we run on
startup so misconfigured keys fail loud.
"""

from __future__ import annotations

import base64
import os
from functools import lru_cache

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


_NONCE_BYTES = 12   # GCM standard
_TAG_BYTES = 16     # appended automatically by AESGCM


class SecretsNotConfigured(RuntimeError):
    """Raised when an encrypt/decrypt is attempted without a key."""


@lru_cache(maxsize=1)
def _key_bytes() -> bytes:
    """Decode the env-supplied key. Cached for the process lifetime.

    Cleared automatically on key rotation (test code can call
    `_key_bytes.cache_clear()`).
    """
    from cara.config import settings

    raw = (settings.oauth_encryption_key or "").strip()
    if not raw:
        raise SecretsNotConfigured(
            "OAUTH_ENCRYPTION_KEY not set; integrations disabled"
        )
    try:
        kb = base64.urlsafe_b64decode(raw + "=" * (4 - len(raw) % 4) % 4)
    except Exception as exc:
        raise SecretsNotConfigured(
            f"OAUTH_ENCRYPTION_KEY is not valid base64: {exc}"
        ) from exc
    if len(kb) != 32:
        raise SecretsNotConfigured(
            f"OAUTH_ENCRYPTION_KEY must decode to 32 bytes, got {len(kb)}"
        )
    return kb


def is_configured() -> bool:
    """Cheap probe that doesn't raise — usable in health checks."""
    try:
        _key_bytes()
        return True
    except SecretsNotConfigured:
        return False


def encrypt_token(plaintext: str) -> bytes:
    """Encrypt a UTF-8 string. Output: 12-byte nonce || ciphertext || 16-byte tag.

    Stored as bytea in Postgres. The nonce is random per call (no IV reuse).
    """
    if not isinstance(plaintext, str):
        raise TypeError("plaintext must be str")
    aes = AESGCM(_key_bytes())
    nonce = os.urandom(_NONCE_BYTES)
    ct = aes.encrypt(nonce, plaintext.encode("utf-8"), associated_data=None)
    return nonce + ct


def decrypt_token(blob: bytes) -> str:
    """Inverse of `encrypt_token`. Raises on tamper / wrong key."""
    if blob is None or len(blob) < _NONCE_BYTES + _TAG_BYTES:
        raise ValueError("ciphertext too short")
    aes = AESGCM(_key_bytes())
    nonce, ct = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
    pt = aes.decrypt(nonce, ct, associated_data=None)
    return pt.decode("utf-8")


def selftest() -> bool:
    """Encrypt+decrypt a sentinel. Runs on startup. Returns True / raises."""
    sample = "cara.secrets.selftest"
    blob = encrypt_token(sample)
    out = decrypt_token(blob)
    if out != sample:
        raise SecretsNotConfigured("AES-GCM selftest mismatch")
    return True
