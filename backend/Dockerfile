FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY backend/pyproject.toml /app/backend/pyproject.toml
COPY backend/app /app/backend/app
RUN python -m pip install --upgrade pip && python -m pip install /app/backend

COPY scripts /app/scripts
COPY data/raw/tau2/da0835f6c67baef58bdda18f2a3b037dfb3a1754/policy.md /app/data/raw/tau2/da0835f6c67baef58bdda18f2a3b037dfb3a1754/policy.md
COPY data/raw/tau2/da0835f6c67baef58bdda18f2a3b037dfb3a1754/manifest.json /app/data/raw/tau2/da0835f6c67baef58bdda18f2a3b037dfb3a1754/manifest.json
COPY data/knowledge /app/data/knowledge

RUN addgroup --system serviceflow && adduser --system --ingroup serviceflow serviceflow \
    && chown -R serviceflow:serviceflow /app

USER serviceflow

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--app-dir", "/app/backend", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS seed

USER root
COPY data/raw /app/data/raw
RUN chown -R serviceflow:serviceflow /app/data/raw
USER serviceflow
