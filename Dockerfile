FROM node:24-bookworm-slim AS attestcoin
WORKDIR /opt/attestcoin
COPY offchain/attestcoin/package*.json ./
RUN npm ci
COPY offchain/attestcoin/ ./
RUN npm run build

FROM python:3.11-slim-bookworm
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    GPU_ABI_DIRECTORY=/opt/hashcredit_gpu/hashcredit_gpu/projections/abi \
    GPU_ATTESTCOIN_MANIFEST=/app/config/attestcoin/cc3-testnet.sepolia.json \
    ATTESTCOIN_REPO_ROOT=/app ATTESTCOIN_CONFIG_DIR=/app/config/attestcoin \
    ATTESTCOIN_CLI=/opt/attestcoin/dist/src/cli.js

COPY --from=attestcoin /usr/local/bin/node /usr/local/bin/node
COPY --from=attestcoin /opt/attestcoin /opt/attestcoin
COPY offchain/gpu/ /opt/hashcredit_gpu/
RUN pip install --no-cache-dir -e /opt/hashcredit_gpu \
    'fastapi>=0.109' 'uvicorn[standard]>=0.27' 'pydantic-settings>=2' \
    'web3>=6' 'httpx>=0.25' 'python-dotenv>=1'
COPY offchain/api/ /app/
COPY offchain/prover/ /opt/prover/
RUN pip install --no-cache-dir --no-deps -e /app -e /opt/prover
COPY config/ /app/config/
RUN python -c "import sys; from hashcredit_api.gpu.app import create_app; create_app(); assert not any(m.startswith(('coincurve','hashcredit_api.bitcoin','hashcredit_api.btc_signmessage')) for m in sys.modules)"
EXPOSE 8000
ENTRYPOINT ["python", "-m", "hashcredit_api.gpu.server"]
