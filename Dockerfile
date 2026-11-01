FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY gauge ./gauge
COPY samples ./samples
ENV PORT=8060
CMD ["sh", "-c", "uv run --no-dev uvicorn gauge.app:app --host 0.0.0.0 --port ${PORT}"]
