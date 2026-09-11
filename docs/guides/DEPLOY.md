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

---

## Frontend Deployment (Vercel)

The HashCredit frontend (`apps/web`) is a Vite + React application designed for Vercel deployment.

### Prerequisites

- Vercel account (https://vercel.com)
- Deployed contracts (addresses for environment variables)
- (Optional) Railway API deployment for proof building automation

### Step 1: Import Project

1. Go to https://vercel.com/new
2. Import your GitHub repository
3. Set root directory to `apps/web`
4. Framework Preset: Vite

### Step 2: Environment Variables

Add these in Vercel project settings (Settings → Environment Variables):

| Variable | Required | Description |
|----------|----------|-------------|
| `VITE_RPC_URL` | Yes | EVM RPC URL (public, read-only) |
| `VITE_CHAIN_ID` | Yes | EVM chain ID (e.g., `102031`) |
| `VITE_HASH_CREDIT_MANAGER` | Yes | Manager contract address |
| `VITE_CHECKPOINT_MANAGER` | Yes | Checkpoint contract address |
| `VITE_BTC_SPV_VERIFIER` | Yes | SPV verifier contract address |
| `VITE_API_URL` | Optional | HashCredit API URL for proof automation |

Example values for Creditcoin testnet:
```
VITE_RPC_URL=https://rpc.cc3-testnet.creditcoin.network
VITE_CHAIN_ID=102031
VITE_HASH_CREDIT_MANAGER=0x...
VITE_CHECKPOINT_MANAGER=0x...
VITE_BTC_SPV_VERIFIER=0x...
VITE_API_URL=https://your-api.railway.app
```

### Step 3: Build Settings

Vercel auto-detects Vite. Verify:

- **Build Command**: `npm run build`
- **Output Directory**: `dist`
- **Install Command**: `npm install`

### Step 4: Deploy

Click "Deploy" and wait for build completion.

### Connecting Frontend to Railway API

If using the HashCredit API (Railway) for proof building:

1. **Get Railway API URL** from Railway dashboard
2. **Add to Vercel** as `VITE_API_URL`
3. **Configure CORS on Railway API**:

In Railway API environment variables:
```bash
ALLOWED_ORIGINS=["https://your-app.vercel.app","https://your-custom-domain.com"]
```

4. **Add API Token** (if required):
   - The frontend can store the API token in browser localStorage
   - Or implement a backend proxy to avoid exposing tokens

### Security Notes

- **Never expose private keys** in frontend environment variables
- `VITE_*` variables are bundled into the frontend and visible to users
- Only use public RPC URLs (no authentication) for `VITE_RPC_URL`
- API tokens should be stored securely (not in Vercel env vars)
- Transaction signing happens in user's wallet (MetaMask), not on server

### Custom Domain

1. Go to Vercel project → Settings → Domains
2. Add your custom domain
3. Configure DNS as instructed
4. Update `ALLOWED_ORIGINS` on Railway API to include the new domain

---

## Full Stack Deployment Checklist

For a complete HashCredit deployment:

1. **Contracts** (Foundry)
   - [ ] Deploy to target chain (testnet/mainnet)
   - [ ] Verify contracts on explorer (optional)
   - [ ] Record all contract addresses

2. **Offchain Services** (Railway)
   - [ ] Deploy API service
   - [ ] Deploy worker service
   - [ ] Configure PostgreSQL
   - [ ] Set environment variables
   - [ ] Verify `/health` endpoint

3. **Frontend** (Vercel)
   - [ ] Deploy to Vercel
   - [ ] Configure environment variables
   - [ ] Configure CORS on API
   - [ ] Test wallet connection
   - [ ] Test contract interactions

4. **Operational**
   - [ ] Register initial checkpoint
   - [ ] Set up monitoring/alerts
   - [ ] Document runbook for incidents
   - [ ] Test pause/unpause flow

---

## Related Docs

- [RAILWAY.md](./RAILWAY.md) - Railway deployment details
- [LOCAL.md](./LOCAL.md) - Local development setup
- [../threat-model.md](../threat-model.md) - Security considerations
