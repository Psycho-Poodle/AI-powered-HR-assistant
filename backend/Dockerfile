FROM python:3.12.10-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENV EMBEDDING_MODEL_PATH=/opt/embeddings HF_HUB_DISABLE_TELEMETRY=1 HF_HUB_DISABLE_XET=1
WORKDIR /app
RUN pip install --no-cache-dir torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu
COPY pyproject.toml ./
COPY app ./app
COPY alembic.ini ./
COPY logging.json ./
COPY migrations ./migrations
RUN pip install --no-cache-dir . && useradd --create-home appuser
RUN python -m app.rag.embeddings --download
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
USER appuser
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-config", "logging.json"]
