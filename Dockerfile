FROM python:3.11-slim

# Root-level Dockerfile (Railway friendly for isolated monorepo):
# - If someone accidentally deploys from repo root, Railway/Railpack should still be able to build.
# - This image runs the offchain API by default.

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0

RUN pip install --no-cache-dir --upgrade pip

# The API depends on the shared local package `hashcredit-gpu` (offchain/gpu, GPU-015), which is not on
# PyPI. Install it from the monorepo first, then the API itself. This Dockerfile must therefore be built
# with the repository root as the build context (root `railway.toml` / `docker-compose.yml` do that).
COPY offchain/gpu/ /opt/hashcredit_gpu/
RUN pip install --no-cache-dir /opt/hashcredit_gpu

# Copy only the API package from the monorepo.
COPY offchain/api/ ./

RUN pip install --no-cache-dir -e .

EXPOSE 8000

# Use ENTRYPOINT so accidental platform-level start command overrides
# (e.g. `npm start`) are treated as extra args and do not break API startup.
ENTRYPOINT ["python", "-m", "hashcredit_api.main"]
