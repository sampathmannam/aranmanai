"""Encryption + auth helpers. Field-level encryption + JWT + bcrypt."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from jose import JWTError, jwt
from passlib.context import CryptContext

from aranmanai.config import get_settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _derive_fernet_key(passphrase: str, salt: bytes) -> bytes:
    """Derive a 32-byte Fernet key from a passphrase using PBKDF2."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode("utf-8")))


def _get_field_cipher() -> Fernet:
    """Get a Fernet cipher for field-level encryption. Key derived from DB key."""
    settings = get_settings()
    salt = hashlib.sha256(b"aranmanai-field-encryption-v1").digest()[:16]
    key = _derive_fernet_key(settings.db_key, salt)
    return Fernet(key)


def encrypt_field(plaintext: str) -> str:
    """Encrypt a field value (e.g. witness name, contact) at rest."""
    if plaintext is None or plaintext == "":
        return plaintext or ""
    return _get_field_cipher().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_field(ciphertext: str) -> str:
    """Decrypt a field value."""
    if not ciphertext:
        return ""
    try:
        return _get_field_cipher().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except Exception:
        # If decryption fails (e.g. data written with a different key),
        # return as-is to avoid losing data. Log it.
        from aranmanai.observability import get_logger
        get_logger(__name__).warning("crypto.decrypt_failed", ciphertext_prefix=ciphertext[:20])
        return ciphertext


def generate_token(subject: str, extra_claims: dict[str, Any] | None = None) -> str:
    """Generate a JWT for the given subject (user_id)."""
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expiry_minutes)
    claims = {
        "sub": subject,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
        "iss": "aranmanai",
    }
    if extra_claims:
        claims.update(extra_claims)
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def verify_token(token: str) -> dict[str, Any] | None:
    """Verify a JWT and return the claims, or None if invalid/expired."""
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


def hash_password(plain: str) -> str:
    """Hash a password for storage."""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password against a stored hash."""
    return _pwd_context.verify(plain, hashed)


def generate_session_secret() -> str:
    """Generate a cryptographically random session secret (use for fresh installs)."""
    return secrets.token_urlsafe(48)
