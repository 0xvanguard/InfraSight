"""Configuración del backend, leída de variables de entorno."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings de la aplicación.

    Todos los valores se cargan de variables de entorno. Para desarrollo local
    fuera de Docker, también se acepta un fichero `.env` en el directorio
    actual.
    """

    database_url: str
    enrollment_token: str
    cors_allow_origin: str = "http://localhost:3000"

    # UUID fijo de la org por defecto (sembrado en 001_init.sql).
    default_org_id: str = "00000000-0000-0000-0000-000000000001"

    # Configuración por defecto que el backend devuelve a los agentes.
    agent_collect_interval_s: int = 30
    agent_heartbeat_interval_s: int = 60
    agent_max_batch_bytes: int = 1_048_576

    # Cuántos segundos sin heartbeat consideramos "offline".
    offline_threshold_s: int = 180

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()  # type: ignore[call-arg]
