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

For a full SPV walkthrough, see `docs/guides/LOCAL.md`.

---

## Production Security Considerations

### Pause Functionality

HashCreditManager includes pause/unpause capability for emergency situations:

```solidity
// Pause: blocks submitPayout, borrow, repay
function pause() external onlyOwner;

// Unpause: resumes normal operation
function unpause() external onlyOwner;
```

When to pause:
- Oracle/verifier compromise suspected
- Critical bug discovered
- Unusual activity patterns
- Coordinated attack in progress

### Multisig Setup (Recommended for Production)

Deploy with a multisig wallet as owner to prevent single-key compromise:

**Using Gnosis Safe:**

1. Create a Gnosis Safe on your target chain
2. Add trusted signers (e.g., 3-of-5 threshold)
3. Deploy contracts with Safe as owner:

```bash
# Option A: Deploy normally, then transfer ownership
forge script script/Deploy.s.sol --rpc-url "$RPC_URL" --broadcast
# Then call transferOwnership(safeAddress) on each contract

# Option B: Modify deploy script to use Safe address directly
# Edit script/Deploy.s.sol to set owner = SAFE_ADDRESS
```

4. All admin operations require Safe confirmation:
   - `setVerifier`
   - `setRiskConfig`
   - `pause/unpause`
   - `freezeBorrower`
   - `transferOwnership`

**Timelock (Optional):**

For additional security, route multisig through a timelock:

1. Deploy OpenZeppelin TimelockController
2. Set timelock as owner of HashCreditManager
3. Grant PROPOSER_ROLE to multisig
4. Grant EXECUTOR_ROLE to multisig (or open execution)

This adds a delay (e.g., 24-48 hours) to sensitive operations, allowing time to respond to malicious governance proposals.

### Key Management Checklist

**Before Mainnet:**

- [ ] Owner key is a multisig (not EOA)
- [ ] Relayer key is separate from owner key
- [ ] Private keys stored in secure vault (not plaintext `.env`)
- [ ] Offchain API_TOKEN is strong and rotated periodically
- [ ] BITCOIN_RPC credentials are not exposed publicly

**Incident Response:**

1. **Pause immediately** if oracle compromise suspected
2. **Freeze affected borrowers** to prevent further borrows
3. **Do NOT unpause** until root cause identified and fixed
4. Consider coordinated verifier replacement if needed

### Contract Upgrade Path

HashCreditManager is NOT upgradeable by design (simpler security model).

To "upgrade":
1. Deploy new HashCreditManager
2. Pause old manager
3. Migrate vault manager pointer: `vault.setManager(newManager)`
4. Register borrowers on new manager
5. Borrowers repay on old manager, borrow on new

This preserves debt/LP relationships while allowing contract fixes.
