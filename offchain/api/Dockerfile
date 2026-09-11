FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0

RUN pip install --no-cache-dir --upgrade pip

COPY . .

RUN pip install --no-cache-dir -e .

# Useful for local Docker runs; Railway will inject PORT anyway.
EXPOSE 8000

# Railway sets PORT; set HOST=0.0.0.0 in service variables.
CMD ["python", "-m", "hashcredit_api.main"]
