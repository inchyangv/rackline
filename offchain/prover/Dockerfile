FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir --upgrade pip

COPY . .

RUN pip install --no-cache-dir -e .

# Keep worker startup resilient even if the platform start command is misconfigured.
ENTRYPOINT ["sh", "./start-worker.sh"]
