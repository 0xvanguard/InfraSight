# Imagen del agente para uso en compose y pruebas locales.
# En producción el agente se instala como servicio systemd en cada host
# monitorizado, no como contenedor.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

COPY infrasight_agent ./infrasight_agent

CMD ["python", "-m", "infrasight_agent"]
