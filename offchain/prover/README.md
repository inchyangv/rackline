# HashCredit Prover/Worker (`offchain/prover`)

This is a CLI/worker that creates **SPV proof (header chain + Merkle inclusion)** for Bitcoin transactions and automates submission to on-chain if necessary.

## What I do

- `build-proof`: Generate SPV proof with txid/vout/height input
- `submit-proof`: Create proof and submit to `HashCreditManager.submitPayout`
- `set-checkpoint`: Register checkpoint (block header) in `CheckpointManager`
- `set-borrower-pubkey-hash`: Register borrower (EVM) ↔ BTC address (pubkeyHash) in `BtcSpvVerifier`
- `run-relayer`: Polls the watch address list and automatically generates/submits proof (worker)

## installation

```bash
cd offchain/prover
pip install -e .
```

For development purposes:

```bash
pip install -e ".[dev]"
```

## Environment variables

When deploying Railway, just put the same key in Railway Variables/Secrets instead of `.env`.

```bash
cp .env.example .env
```

Required (based on live proof):

- `BITCOIN_RPC_URL`
- Your node (testnet): Usually `http://127.0.0.1:18332`
- Public (testnet, unauthenticated example): `https://bitcoin-testnet-rpc.publicnode.com`
- `EVM_RPC_URL` (Creditcoin testnet RPC)
- `CHAIN_ID` (default 102031)
- `PRIVATE_KEY` (on-chain transaction signing key)
- `HASH_CREDIT_MANAGER`
- `CHECKPOINT_MANAGER`

## SPV proof constraints (practical tips)

For gas/cost reasons, we use a strategy of limiting the header chain length included in the proof.

- It is usually recommended to keep the difference between `checkpoint_height` and `target_height` in the range of **1..144**.

## How to use

### 1) Checkpoint registration

```bash
hashcredit-prover set-checkpoint <height> \
  --checkpoint-manager $CHECKPOINT_MANAGER
```

### 2) Register borrower BTC address (pubkeyHash)

```bash
hashcredit-prover set-borrower-pubkey-hash \
  <borrower_evm> <btc_address> \
  --spv-verifier $BTC_SPV_VERIFIER
```

Supported address formats:

- bech32 P2WPKH: testnet `tb1q...`, mainnet `bc1q...`
- base58 P2PKH: testnet `m.../n...`, mainnet `1...`

### 3) Proof generation (HEX)

```bash
hashcredit-prover build-proof \
  <txid> <output_index> <checkpoint_height> <target_height> <borrower_evm> \
  --hex
```

### 4) Proof creation + submission

```bash
hashcredit-prover submit-proof \
  <txid> <output_index> <borrower_evm> \
  --checkpoint <checkpoint_height> \
  --target <target_height> \
  --manager $HASH_CREDIT_MANAGER
```

Options:

- `--dry-run`: Create proof but do not submit it
- `--hex-only`: Print only proof hex without submission

### 5) Walker (run-relayer)

Prepare list of watch addresses as JSON:

```json
[
  {"btc_address": "tb1q...", "borrower": "0x1234...", "enabled": true}
]
```

Local:

```bash
hashcredit-prover run-relayer addresses.json \
  --manager $HASH_CREDIT_MANAGER \
  --checkpoint-manager $CHECKPOINT_MANAGER
```

Railway recommended (injected as an environment variable):

- `ADDRESSES_JSON_B64`: A string encoding the above JSON in base64.

```bash
base64 < addresses.json | tr -d '\n'
```

## Requirements

- Python 3.11+
- Bitcoin RPC access
- Live proof requires random txid lookup, so `txindex=1` is recommended for your node.
