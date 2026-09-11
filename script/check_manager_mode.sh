#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   script/check_manager_mode.sh <HASH_CREDIT_MANAGER> <RPC_URL>
# Or with env:
#   HASH_CREDIT_MANAGER=0x... EVM_RPC_URL=https://... script/check_manager_mode.sh

if ! command -v cast >/dev/null 2>&1; then
  echo "error: 'cast' not found. Install Foundry first." >&2
  exit 1
fi

MANAGER_ADDR="${1:-${HASH_CREDIT_MANAGER:-}}"
RPC_URL="${2:-${EVM_RPC_URL:-${RPC_URL:-}}}"

if [[ -z "${MANAGER_ADDR}" ]]; then
  echo "error: manager address is required (arg1 or HASH_CREDIT_MANAGER)." >&2
  exit 1
fi

if [[ -z "${RPC_URL}" ]]; then
  echo "error: rpc url is required (arg2 or EVM_RPC_URL/RPC_URL)." >&2
  exit 1
fi

echo "manager: ${MANAGER_ADDR}"
echo "rpc: ${RPC_URL}"

VERIFIER_ADDR="$(cast call "${MANAGER_ADDR}" "verifier()(address)" --rpc-url "${RPC_URL}")"
echo "verifier: ${VERIFIER_ADDR}"

if [[ "${VERIFIER_ADDR,,}" == "0x0000000000000000000000000000000000000000" ]]; then
  echo "mode: invalid (zero verifier address)"
  exit 2
fi

if RELAYER_SIGNER="$(cast call "${VERIFIER_ADDR}" "relayerSigner()(address)" --rpc-url "${RPC_URL}" 2>/dev/null)"; then
  echo "mode: MVP (RelayerSigVerifier)"
  echo "relayer_signer: ${RELAYER_SIGNER}"
  exit 0
fi

if CHECKPOINT_MANAGER="$(cast call "${VERIFIER_ADDR}" "checkpointManager()(address)" --rpc-url "${RPC_URL}" 2>/dev/null)"; then
  echo "mode: SPV (BtcSpvVerifier)"
  echo "checkpoint_manager: ${CHECKPOINT_MANAGER}"
  exit 0
fi

echo "mode: unknown/custom verifier (not RelayerSigVerifier or BtcSpvVerifier ABI)"
