FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN pip install --no-cache-dir --upgrade pip

COPY . .

RUN pip install --no-cache-dir -e .

# Railway sets PORT; set HOST=0.0.0.0 in service variables.
CMD ["python", "-m", "hashcredit_api.main"]

