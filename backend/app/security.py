"""Utilidades de seguridad: generación y verificación de tokens de dispositivo.

En M1 el modelo es deliberadamente simple:

- Un único `enrollment_token` compartido (variable de entorno) autoriza el
  endpoint `POST /v1/enroll`.
- Cada dispositivo recibe un `device_token` aleatorio y se almacena en la
  base de datos hasheado con SHA-256.

En M4 esto se sustituye por tokens de enrolamiento de un solo uso emitidos
desde el dashboard.
"""

from __future__ import annotations

import hashlib
import secrets

import asyncpg

DEVICE_TOKEN_PREFIX = "v1.dvc."
DEVICE_TOKEN_RANDOM_BYTES = 32


def generate_device_token() -> str:
    """Genera un token opaco con un prefijo identificable."""
    return DEVICE_TOKEN_PREFIX + secrets.token_urlsafe(DEVICE_TOKEN_RANDOM_BYTES)


def hash_token(token: str) -> str:
    """Hash SHA-256 hex del token (los tokens ya tienen alta entropía)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def lookup_device_by_token(
    conn: asyncpg.Connection, token: str
) -> asyncpg.Record | None:
    """Resuelve un device_token a su (device_id, org_id) o devuelve None."""
    return await conn.fetchrow(
        """
        SELECT d.id AS device_id, d.org_id AS org_id
        FROM   device_tokens t
        JOIN   devices d ON d.id = t.device_id
        WHERE  t.token_hash = $1
          AND  t.revoked_at IS NULL
        """,
        hash_token(token),
    )
