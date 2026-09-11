#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi

log() {
  printf '[demo-live-spv] %s\n' "$*"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "error: missing command '$1'" >&2
    exit 1
  fi
}

require_var() {
  local key="$1"
  if [[ -z "${!key:-}" ]]; then
    echo "error: required env var '$key' is empty" >&2
    exit 1
  fi
}

json_rpc_call() {
  local method="$1"
  local params_json="$2"
  local response

  # Some public Bitcoin RPC endpoints do not require auth.
  # Only send basic auth if both user and password are provided.
  if [[ -n "${BITCOIN_RPC_USER:-}" && -n "${BITCOIN_RPC_PASSWORD:-}" ]]; then
    response="$(curl -sS \
      --user "${BITCOIN_RPC_USER}:${BITCOIN_RPC_PASSWORD}" \
      -H 'content-type: application/json' \
      --data-binary "{\"jsonrpc\":\"1.0\",\"id\":\"hashcredit-demo\",\"method\":\"${method}\",\"params\":${params_json}}" \
      "${BITCOIN_RPC_URL}")"
  else
    response="$(curl -sS \
      -H 'content-type: application/json' \
      --data-binary "{\"jsonrpc\":\"1.0\",\"id\":\"hashcredit-demo\",\"method\":\"${method}\",\"params\":${params_json}}" \
      "${BITCOIN_RPC_URL}")"
  fi

  if [[ "$(jq -r '.error != null' <<<"$response")" == "true" ]]; then
    echo "error: bitcoin rpc ${method} failed: $(jq -c '.error' <<<"$response")" >&2
    exit 1
  fi

  jq -c '.result' <<<"$response"
}

extract_created_address() {
  local run_json="$1"
  local contract_name="$2"
  jq -r --arg n "$contract_name" '.transactions[] | select(.transactionType == "CREATE" and .contractName == $n) | .contractAddress' "$run_json" | tail -n 1
}

artifact_bytecode() {
  local contract="$1"
  jq -r '.bytecode.object // .bytecode' "out/${contract}.sol/${contract}.json" | sed 's/^0x//'
}

encode_ctor() {
  local sig="$1"; shift
  cast abi-encode "$sig" "$@" | sed 's/^0x//'
}

deploy_create() {
  local label="$1"; shift
  local create_code_hex="$1"; shift
  local tx
  local addr

  log "deploying (cast): ${label}"

  tx="$(cast send --rpc-url "$RPC_URL" --private-key "$PRIVATE_KEY" --legacy --gas-price "$GAS_PRICE" \
    --create "0x${create_code_hex}" 2>/dev/null | grep -Eo '0x[0-9a-fA-F]{64}' | tail -n 1 || true)"
  if [[ -z "$tx" ]]; then
    echo "error: could not parse tx hash for ${label}" >&2
    exit 1
  fi

  addr="$(cast receipt --rpc-url "$RPC_URL" --json "$tx" | jq -r '.contractAddress')"
  if [[ -z "$addr" || "$addr" == "null" ]]; then
    echo "error: receipt missing contractAddress for ${label} (tx=${tx})" >&2
    exit 1
  fi

  echo "$addr"
}

deploy_spv_stack_cast() {
  # NOTE: Creditcoin CC3 testnet RPC may omit block header fields required by `forge script`.
  # This path deploys by raw bytecode via `cast send --create`.
  log "deploying SPV stack via cast (no forge script)"

  forge build >/dev/null

  GAS_PRICE="${GAS_PRICE:-$(cast gas-price --rpc-url "$RPC_URL")}"
  DEPLOYER="$(cast wallet address --private-key "$PRIVATE_KEY")"

  # 1) Stablecoin
  local stablecoin_bc stablecoin_args
  stablecoin_bc="$(artifact_bytecode TestnetMintableERC20)"
  stablecoin_args="$(encode_ctor 'constructor(string,string,uint8,address)' 'HashCredit USD' 'hcUSD' 6 "$DEPLOYER")"
  STABLECOIN_ADDRESS="$(deploy_create TestnetMintableERC20 "${stablecoin_bc}${stablecoin_args}")"

  # 2) CheckpointManager
  local cp_bc cp_args
  cp_bc="$(artifact_bytecode CheckpointManager)"
  cp_args="$(encode_ctor 'constructor(address)' "$DEPLOYER")"
  CHECKPOINT_MANAGER="$(deploy_create CheckpointManager "${cp_bc}${cp_args}")"

  # 3) BtcSpvVerifier
  local spv_bc spv_args
  spv_bc="$(artifact_bytecode BtcSpvVerifier)"
  spv_args="$(encode_ctor 'constructor(address,address)' "$DEPLOYER" "$CHECKPOINT_MANAGER")"
  BTC_SPV_VERIFIER="$(deploy_create BtcSpvVerifier "${spv_bc}${spv_args}")"

  # 4) RiskConfig
  local risk_bc risk_args
  risk_bc="$(artifact_bytecode RiskConfig)"
  local FIXED_APR_BPS=1000
  local BTC_PRICE_USD=5000000000000
  local ADVANCE_RATE_BPS=5000
  local WINDOW_SECONDS=$((30*24*60*60))
  local NEW_BORROWER_CAP=10000000000
  local MIN_PAYOUT_SATS=10000
  local risk_tuple="(6,${ADVANCE_RATE_BPS},${WINDOW_SECONDS},${NEW_BORROWER_CAP},0,${MIN_PAYOUT_SATS},${BTC_PRICE_USD},3,10000000,5000,${WINDOW_SECONDS})"
  risk_args="$(encode_ctor 'constructor((uint32,uint32,uint32,uint128,uint128,uint64,uint64,uint32,uint64,uint32,uint32))' "$risk_tuple")"
  RISK_CONFIG="$(deploy_create RiskConfig "${risk_bc}${risk_args}")"

  # 5) PoolRegistry(true)
  local pool_bc pool_args
  pool_bc="$(artifact_bytecode PoolRegistry)"
  pool_args="$(encode_ctor 'constructor(bool)' true)"
  POOL_REGISTRY="$(deploy_create PoolRegistry "${pool_bc}${pool_args}")"

  # 6) LendingVault(stablecoin, FIXED_APR_BPS)
  local vault_bc vault_args
  vault_bc="$(artifact_bytecode LendingVault)"
  vault_args="$(encode_ctor 'constructor(address,uint256)' "$STABLECOIN_ADDRESS" "$FIXED_APR_BPS")"
  LENDING_VAULT="$(deploy_create LendingVault "${vault_bc}${vault_args}")"

  # 7) HashCreditManager(spv,vault,risk,pool,stablecoin)
  local manager_bc manager_args
  manager_bc="$(artifact_bytecode HashCreditManager)"
  manager_args="$(encode_ctor 'constructor(address,address,address,address,address)' "$BTC_SPV_VERIFIER" "$LENDING_VAULT" "$RISK_CONFIG" "$POOL_REGISTRY" "$STABLECOIN_ADDRESS")"
  HASH_CREDIT_MANAGER="$(deploy_create HashCreditManager "${manager_bc}${manager_args}")"

  # Configure vault + initial liquidity
  cast send --rpc-url "$RPC_URL" --private-key "$PRIVATE_KEY" --legacy --gas-price "$GAS_PRICE" \
    "$LENDING_VAULT" 'setManager(address)' "$HASH_CREDIT_MANAGER" >/dev/null

  INITIAL_LIQUIDITY="${INITIAL_LIQUIDITY:-1000000000000}"
  cast send --rpc-url "$RPC_URL" --private-key "$PRIVATE_KEY" --legacy --gas-price "$GAS_PRICE" \
    "$STABLECOIN_ADDRESS" 'mint(address,uint256)' "$DEPLOYER" "$INITIAL_LIQUIDITY" >/dev/null
  cast send --rpc-url "$RPC_URL" --private-key "$PRIVATE_KEY" --legacy --gas-price "$GAS_PRICE" \
    "$STABLECOIN_ADDRESS" 'approve(address,uint256)' "$LENDING_VAULT" "$INITIAL_LIQUIDITY" >/dev/null
  cast send --rpc-url "$RPC_URL" --private-key "$PRIVATE_KEY" --legacy --gas-price "$GAS_PRICE" \
    "$LENDING_VAULT" 'deposit(uint256)' "$INITIAL_LIQUIDITY" >/dev/null
}

require_cmd jq
require_cmd curl
require_cmd forge
require_cmd cast
require_cmd hashcredit-prover
require_cmd grep

export RPC_URL="${RPC_URL:-${EVM_RPC_URL:-}}"
export EVM_RPC_URL="${EVM_RPC_URL:-${RPC_URL:-}}"
export CHAIN_ID="${CHAIN_ID:-102031}"
export BTC_VOUT="${BTC_VOUT:-0}"
export INITIAL_LIQUIDITY="${INITIAL_LIQUIDITY:-1000000000000}"
export SKIP_DEPLOY="${SKIP_DEPLOY:-0}"
export SKIP_REGISTER="${SKIP_REGISTER:-0}"

require_var RPC_URL
require_var EVM_RPC_URL
require_var CHAIN_ID
require_var PRIVATE_KEY
require_var BITCOIN_RPC_URL
require_var BORROWER_EVM
require_var BORROWER_BTC_ADDRESS
require_var BTC_TXID
require_var BTC_VOUT

log "using EVM RPC: ${RPC_URL}"
log "using Bitcoin RPC: ${BITCOIN_RPC_URL}"
log "chain id: ${CHAIN_ID}"

if [[ "$SKIP_DEPLOY" != "1" ]]; then
  deploy_spv_stack_cast
else
  log "SKIP_DEPLOY=1, skipping deployment"
fi

require_var STABLECOIN_ADDRESS
require_var CHECKPOINT_MANAGER
require_var BTC_SPV_VERIFIER
require_var LENDING_VAULT
require_var HASH_CREDIT_MANAGER

log "stablecoin: ${STABLECOIN_ADDRESS}"
log "checkpoint manager: ${CHECKPOINT_MANAGER}"
log "spv verifier: ${BTC_SPV_VERIFIER}"
log "lending vault: ${LENDING_VAULT}"
log "hash credit manager: ${HASH_CREDIT_MANAGER}"

if [[ -z "${TARGET_HEIGHT:-}" ]]; then
  tx_verbose="$(json_rpc_call "getrawtransaction" "[\"${BTC_TXID}\", true]")"
  tx_block_hash="$(jq -r '.blockhash // empty' <<<"$tx_verbose")"
  if [[ -z "$tx_block_hash" ]]; then
    echo "error: BTC_TXID appears unconfirmed (blockhash missing): ${BTC_TXID}" >&2
    exit 1
  fi
  header_verbose="$(json_rpc_call "getblockheader" "[\"${tx_block_hash}\", true]")"
  TARGET_HEIGHT="$(jq -r '.height' <<<"$header_verbose")"
fi
require_var TARGET_HEIGHT
log "target height: ${TARGET_HEIGHT}"

tip_height_for_proof=$((TARGET_HEIGHT + 5))
if [[ -z "${CHECKPOINT_HEIGHT:-}" ]]; then
  CHECKPOINT_HEIGHT=$((TARGET_HEIGHT - 10))
fi

if (( CHECKPOINT_HEIGHT <= 0 )); then
  echo "error: invalid CHECKPOINT_HEIGHT=${CHECKPOINT_HEIGHT}" >&2
  exit 1
fi

retarget_period=2016
if (( (CHECKPOINT_HEIGHT / retarget_period) != (tip_height_for_proof / retarget_period) )); then
  period_start=$(((tip_height_for_proof / retarget_period) * retarget_period))
  adjusted_checkpoint=$((TARGET_HEIGHT - 10))
  if (( adjusted_checkpoint <= period_start )); then
    adjusted_checkpoint=$((period_start + 1))
  fi
  if (( adjusted_checkpoint >= TARGET_HEIGHT )); then
    echo "error: tx near retarget boundary; choose a different BTC_TXID" >&2
    exit 1
  fi
  CHECKPOINT_HEIGHT="$adjusted_checkpoint"
  log "checkpoint adjusted for retarget safety: ${CHECKPOINT_HEIGHT}"
fi

header_chain_len=$((tip_height_for_proof - CHECKPOINT_HEIGHT))
if (( header_chain_len <= 0 || header_chain_len > 144 )); then
  echo "error: invalid header chain length ${header_chain_len} (must be 1..144)" >&2
  exit 1
fi

log "checkpoint height: ${CHECKPOINT_HEIGHT} (proof chain length=${header_chain_len})"

log "setting checkpoint on-chain"
hashcredit-prover set-checkpoint "${CHECKPOINT_HEIGHT}" \
  --checkpoint-manager "${CHECKPOINT_MANAGER}" \
  --rpc-url "${BITCOIN_RPC_URL}" \
  --rpc-user "${BITCOIN_RPC_USER}" \
  --rpc-password "${BITCOIN_RPC_PASSWORD}" \
  --evm-rpc-url "${EVM_RPC_URL}" \
  --chain-id "${CHAIN_ID}" \
  --private-key "${PRIVATE_KEY}"

log "setting borrower pubkey hash on SPV verifier"
hashcredit-prover set-borrower-pubkey-hash \
  "${BORROWER_EVM}" \
  "${BORROWER_BTC_ADDRESS}" \
  --spv-verifier "${BTC_SPV_VERIFIER}" \
  --evm-rpc-url "${EVM_RPC_URL}" \
  --chain-id "${CHAIN_ID}" \
  --private-key "${PRIVATE_KEY}"

BTC_KEY_HASH="$(cast keccak "${BORROWER_BTC_ADDRESS}")"
log "btc payout key hash: ${BTC_KEY_HASH}"

if [[ "$SKIP_REGISTER" != "1" ]]; then
  log "registering borrower on manager"
  if ! cast send "${HASH_CREDIT_MANAGER}" "registerBorrower(address,bytes32)" \
      "${BORROWER_EVM}" \
      "${BTC_KEY_HASH}" \
      --rpc-url "${RPC_URL}" \
      --private-key "${PRIVATE_KEY}"; then
    log "registerBorrower failed; probing borrowerInfo (may already be registered)"
    if ! cast call "${HASH_CREDIT_MANAGER}" \
      "getBorrowerInfo(address)((uint8,bytes32,uint128,uint128,uint128,uint128,uint64,uint64,uint32))" \
      "${BORROWER_EVM}" \
      --rpc-url "${RPC_URL}" >/dev/null 2>&1; then
      echo "error: registerBorrower failed and borrowerInfo read failed" >&2
      exit 1
    fi
    log "borrower appears to exist already, continuing"
  fi
else
  log "SKIP_REGISTER=1, skipping registerBorrower"
fi

log "available credit before submit"
cast call "${HASH_CREDIT_MANAGER}" "getAvailableCredit(address)(uint256)" "${BORROWER_EVM}" --rpc-url "${RPC_URL}" || true

log "submitting real SPV proof"
hashcredit-prover submit-proof \
  "${BTC_TXID}" \
  "${BTC_VOUT}" \
  "${BORROWER_EVM}" \
  --checkpoint "${CHECKPOINT_HEIGHT}" \
  --target "${TARGET_HEIGHT}" \
  --manager "${HASH_CREDIT_MANAGER}" \
  --rpc-url "${BITCOIN_RPC_URL}" \
  --rpc-user "${BITCOIN_RPC_USER}" \
  --rpc-password "${BITCOIN_RPC_PASSWORD}" \
  --evm-rpc-url "${EVM_RPC_URL}" \
  --chain-id "${CHAIN_ID}" \
  --private-key "${PRIVATE_KEY}"

log "available credit after submit"
cast call "${HASH_CREDIT_MANAGER}" "getAvailableCredit(address)(uint256)" "${BORROWER_EVM}" --rpc-url "${RPC_URL}" || true

cat > .env.demo.live.generated <<EOF
RPC_URL=${RPC_URL}
EVM_RPC_URL=${EVM_RPC_URL}
CHAIN_ID=${CHAIN_ID}
STABLECOIN_ADDRESS=${STABLECOIN_ADDRESS}
CHECKPOINT_MANAGER=${CHECKPOINT_MANAGER}
BTC_SPV_VERIFIER=${BTC_SPV_VERIFIER}
LENDING_VAULT=${LENDING_VAULT}
HASH_CREDIT_MANAGER=${HASH_CREDIT_MANAGER}
BORROWER_EVM=${BORROWER_EVM}
BORROWER_BTC_ADDRESS=${BORROWER_BTC_ADDRESS}
BTC_TXID=${BTC_TXID}
BTC_VOUT=${BTC_VOUT}
CHECKPOINT_HEIGHT=${CHECKPOINT_HEIGHT}
TARGET_HEIGHT=${TARGET_HEIGHT}
EOF

cat > apps/web/.env.live.generated <<EOF
VITE_RPC_URL=${RPC_URL}
VITE_CHAIN_ID=${CHAIN_ID}
VITE_HASH_CREDIT_MANAGER=${HASH_CREDIT_MANAGER}
VITE_BTC_SPV_VERIFIER=${BTC_SPV_VERIFIER}
VITE_CHECKPOINT_MANAGER=${CHECKPOINT_MANAGER}
EOF

log "done"
log "generated: .env.demo.live.generated"
log "generated: apps/web/.env.live.generated"
