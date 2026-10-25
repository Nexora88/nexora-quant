FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000

COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir -e .

RUN mkdir -p /app/data
VOLUME ["/app/data"]

EXPOSE 8000
# Single process: FastAPI lifespan starts the trading engine
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
