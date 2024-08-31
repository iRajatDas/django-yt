# Build stage
FROM python:3.10-slim-buster as builder

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libpq-dev gcc build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /app/wheels -r requirements.txt

# Final stage
FROM python:3.10-slim-buster

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libpq-dev ffmpeg --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/wheels /wheels
COPY --from=builder /app/requirements.txt .

RUN pip install --no-cache --no-compile /wheels/* && rm -rf /wheels

COPY . .

EXPOSE 8000

CMD ["uvicorn", "youtube_downloader.asgi:application", "--host", "0.0.0.0", "--port", "8000"]