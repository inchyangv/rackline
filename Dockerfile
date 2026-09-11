FROM python:3.11-slim

# Root-level Dockerfile (Railway friendly for isolated monorepo):
# - If someone accidentally deploys from repo root, Railway/Railpack should still be able to build.
# - This image runs the offchain API by default.

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0

RUN pip install --no-cache-dir --upgrade pip

# Copy only the API package from the monorepo.
COPY offchain/api/ ./

RUN pip install --no-cache-dir -e .

EXPOSE 8000

CMD ["python", "-m", "hashcredit_api.main"]

