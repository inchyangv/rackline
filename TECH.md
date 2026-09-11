# HashCredit Technical Note (SPV-First, USC-Ready)

## Why This Exists
USC testnet was available, but USC mainnet was not live when we built this flow, so we implemented the full proof + credit pipeline ourselves using the same architecture pattern we would use for USC.

Result:
- It works now on Creditcoin testnet.
- The BTC proof path is already production-shaped.
- USC can be plugged in later without redesigning core proof logic.

## System Architecture
### On-chain contracts
- `BtcSpvVerifier`:
  - Verifies Bitcoin payout evidence trustlessly from SPV data.
  - Checks checkpoint anchor, header chain linkage/PoW, merkle inclusion, tx output script, and borrower pubkey-hash match.
- `CheckpointManager`:
  - Stores trusted Bitcoin checkpoints (`height`, `blockHash`, `bits`, `chainWork`, `timestamp`).
- `HashCreditManager`:
  - Accepts verified payout evidence through `IVerifierAdapter`.
  - Applies replay protection (`processedPayouts`).
  - Updates trailing revenue and credit limit.
  - Routes borrow/repay to `LendingVault`.
- `LendingVault`:
  - Stablecoin liquidity + debt accounting.
- `RiskConfig`:
  - Encodes credit policy (advance rate, windows, min payout threshold, caps, etc.).

### Off-chain services
- `offchain/api`:
  - Builds SPV proofs from Bitcoin RPC and submits transactions.
  - Exposes operational endpoints for checkpointing, borrower mapping, proof build/submit.
  - Provides read-only BTC address history via external Esplora indexer.
- `offchain/prover`:
  - Watches configured BTC addresses.
  - Detects qualifying payouts.
  - Builds and submits SPV proofs automatically after required confirmations.

## End-to-End Flow
1. Register checkpoint on-chain (`CheckpointManager.setCheckpoint`).
2. Register borrower BTC pubkey-hash in verifier (`BtcSpvVerifier.setBorrowerPubkeyHash`).
3. Register borrower in manager (`HashCreditManager.registerBorrower`).
4. Build SPV proof from Bitcoin data:
   - headers (`checkpoint+1 ... tip`)
   - tx merkle branch
   - raw tx
   - tx index, output index, borrower address
5. Submit proof (`HashCreditManager.submitPayout`).
6. Manager verifies evidence via verifier adapter, updates revenue/limit, and enables borrow.
7. Borrower borrows/repays stablecoin via vault routing.

## Proof Interface (Key Point)
`HashCreditManager` does not need Bitcoin internals.
It only consumes `PayoutEvidence` from an `IVerifierAdapter`.

That separation is the portability layer:
- BTC verification details stay in verifier adapters.
- Credit logic stays in manager/risk/vault.

## Why This Is USC-Ready
The design already decouples:
- Proof verification (`IVerifierAdapter`)
- Credit accounting (`HashCreditManager`)
- Liquidity/asset (`LendingVault` + ERC20 token address)

So USC integration is mostly an adapter + wiring task, not a protocol rewrite.

## USC Integration Paths
### Path A: Reuse as-is, change asset
- Deploy `LendingVault` with USC token.
- Point a manager deployment to USC vault/token.
- Keep SPV verifier and proof format unchanged.

### Path B: USC-specific settlement adapter
- Keep current payout-proof path unchanged.
- Add adapter/module that mints/transfers USC according to approved credit events.
- Keep replay, risk, and debt checks in manager.

### Path C: Multi-verifier mode
- Keep BTC SPV verifier.
- Add additional USC-native verifier if USC requires extra attestations.
- Route both through `IVerifierAdapter`-compatible interfaces.

## Practical Claim
"USC mainnet wasn't live when we built this, so we implemented the same architecture ourselves.
It already runs now, and USC can be attached by wiring settlement/token layers rather than rebuilding the proof system."

## Current Live Capabilities
- SPV proof generation from real Bitcoin testnet data.
- On-chain payout verification and replay-safe credit updates.
- Borrow/repay lifecycle on Creditcoin testnet.
- Demo wallet to BTC history linkage via external indexer API.

## Implementation Footprint
- Verifier and manager interfaces are stable and modular.
- Core components are contractized and independently testable.
- Off-chain services are split by role (operations API vs continuous relayer/worker).

This is exactly the structure you want before introducing a new settlement asset like USC.
