"""Pool de conexiones asyncpg compartido por toda la aplicación."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

import asyncpg

from .config import settings

_pool: asyncpg.Pool | None = None


async def init_pool(retries: int = 30, delay_s: float = 1.0) -> asyncpg.Pool:
    """Inicializa el pool, reintentando mientras la base de datos arranca.

    El backend puede ganar la carrera al servicio `db` en compose; por eso
    aceptamos un puñado de reintentos antes de rendirnos.
    """
    global _pool
    if _pool is not None:
        return _pool

    last_error: Exception | None = None
    for _ in range(retries):
        try:
            _pool = await asyncpg.create_pool(
                dsn=settings.database_url,
                min_size=1,
                max_size=10,
                command_timeout=30,
            )
            return _pool
        except (OSError, asyncpg.PostgresError) as exc:
            last_error = exc
            await asyncio.sleep(delay_s)

    raise RuntimeError(
        f"No se pudo conectar a la base de datos tras {retries} intentos"
    ) from last_error


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("El pool de la base de datos no está inicializado")
    return _pool


async def acquire() -> AsyncIterator[asyncpg.Connection]:
    """Helper como dependencia FastAPI para obtener una conexión del pool."""
    async with get_pool().acquire() as conn:
        yield conn
