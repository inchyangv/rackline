# HashCredit Deployment Guide

This document focuses on deploying HashCredit contracts (local + testnet) and wiring the resulting addresses into your config.

HashCredit supports two deployment modes:

- **MVP (RelayerSigVerifier)**: `script/Deploy.s.sol`
- **SPV mode (BtcSpvVerifier + CheckpointManager)**: `script/DeploySpv.s.sol`

---

## Prerequisites

- Foundry (`forge`, `cast`, `anvil`)
- `make`
- Python 3.11+ (only if you plan to run the relayer/prover)

---

## Environment (.env)

- Forge scripts automatically read the repo-root `.env`.
- `make` targets also read the repo-root `.env` (Makefile includes it).

Important: keep `.env` in simple `KEY=VALUE` format (no `export ...` lines).

When running commands that reference `$RPC_URL`, `$HASH_CREDIT_MANAGER`, etc, load `.env` into your current shell:

```bash
set -a
source .env
set +a
```

Minimum `.env` for deployments:

```dotenv
# EVM
RPC_URL=http://localhost:8545
CHAIN_ID=31337

# Deployer key (also used as default tx sender in offchain tools)
PRIVATE_KEY=0x...

# MVP only (EIP-712 signer)
RELAYER_PRIVATE_KEY=0x...
# Optional: if RELAYER_PRIVATE_KEY != PRIVATE_KEY, set the signer address explicitly at deploy time
# RELAYER_SIGNER=0x...
```

After deployment, paste the printed contract addresses into `.env`:

```dotenv
HASH_CREDIT_MANAGER=0x...
VERIFIER=0x...        # MVP (RelayerSigVerifier)
LENDING_VAULT=0x...

# SPV mode
CHECKPOINT_MANAGER=0x...
BTC_SPV_VERIFIER=0x...
```

---

## MVP Deploy (RelayerSigVerifier)

### Local (Anvil)

Terminal A:
```bash
make anvil
```

Terminal B:
```bash
forge install
cp .env.example .env

# Edit .env for local:
# RPC_URL=http://localhost:8545
# CHAIN_ID=31337
# PRIVATE_KEY=<anvil private key>
# RELAYER_PRIVATE_KEY=<same key for the simplest demo>

make deploy-local
```

Then copy the printed addresses into `.env`:
- `HASH_CREDIT_MANAGER`
- `VERIFIER`
- `LENDING_VAULT`

### Creditcoin testnet

```bash
cp .env.example .env

# Edit .env:
# RPC_URL=https://rpc.cc3-testnet.creditcoin.network
# CHAIN_ID=102031
# PRIVATE_KEY=<funded testnet key>
# RELAYER_PRIVATE_KEY=<relayer signing key>
# (optional) RELAYER_SIGNER=<address of RELAYER_PRIVATE_KEY>

make deploy-testnet
```

Optional verification attempt:
```bash
make deploy-testnet-verify
```

Note: verification support depends on the target chain/explorer configuration. If this fails, deploy without `--verify`.

---

## SPV Deploy (BtcSpvVerifier)

### Local (Anvil)

Terminal A:
```bash
make anvil
```

Terminal B:
```bash
forge install
cp .env.example .env

# Edit .env for local:
# RPC_URL=http://localhost:8545
# CHAIN_ID=31337
# PRIVATE_KEY=<anvil private key>

forge script script/DeploySpv.s.sol --rpc-url "$RPC_URL" --broadcast
```

### Creditcoin testnet

```bash
cp .env.example .env

# Edit .env:
# RPC_URL=https://rpc.cc3-testnet.creditcoin.network
# CHAIN_ID=102031
# PRIVATE_KEY=<funded testnet key>

forge script script/DeploySpv.s.sol --rpc-url "$RPC_URL" --broadcast
```

Next steps for SPV mode (high level):
1. Register a Bitcoin checkpoint on `CheckpointManager`
2. Register borrower BTC pubkey-hash on `BtcSpvVerifier`
3. Register the borrower on `HashCreditManager`
4. Submit proofs via `hashcredit-prover` or `hashcredit-api`

For a full SPV walkthrough, see `LOCAL.md`.
