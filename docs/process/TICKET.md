# HashCredit — TICKET.md
> Rule: Process incomplete tickets in order, starting from the top.
> Each ticket must include (1) code changes, (2) testing, and (3) document/ticket updates to be Done.

---

## Status notation
- [ ] TODO
- [~] IN PROGRESS
- [x] DONE
- [!] BLOCKED (state reason)

---

## P0 — Hackathon MVP (Relayer Signature Oracle)

### T0.1 Repository Skeleton + Tooling
- Priority: P0
- Status: [x] DONE
- Purpose: Create a basic repo structure and build/test/format environment.
- work:
- Initialize Foundry, create basic CI script (local basis)
- solidity formatter / lint (optional) settings
- `/offchain/relayer` Python package skeleton
- Write `.env.example`
- Output:
- `foundry.toml`, `remappings.txt` (if necessary)
- `Makefile` or `justfile` (optional)
- Folder structure confirmed
- Completion conditions:
- `forge test` passes even if it is an empty test
- The Python package has an execution entry point (`python -m ...`)

---

### T0.2 Define Interfaces & Data Types (Core ABI Fixation)
- Priority: P0
- Status: [x] DONE
- Purpose: First fix the external interface of the Verifier Adapter and Manager/Vault (minimize future replacement).
- work:
- `IVerifierAdapter` interface definition
- Common `PayoutEvidence` struct definition (or set of return values)
- Define event list
- Error type definition (custom errors)
- Completion conditions:
- The interface is documented and the principle of minimizing changes is applied in subsequent tickets.

---

### T0.3 LendingVault (Single Stablecoin) — Minimal Viable Vault
- Priority: P0
- Status: [x] DONE
- Purpose: Receive stablecoin liquidity and process borrow/repay/interest.
- Scope:
- Single ERC20 stablecoin (started as a mock)
- Interest model: Choose between fixed APR or simple utilization-based
- Includes deposit/withdrawal (loan liquidity supply) function
- work:
- `deposit/withdraw` (LP shares model can be simplified)
- `borrow/repay` can only call `HashCreditManager` (onlyManager)
- Interest accumulation: simple method based on block.timestamp
- test:
    - deposit/withdraw
- Vault balance decreases when borrowing
- Increase upon repayment + decrease in debt
- Completion conditions:
- Provides ABI that can be linked to `HashCreditManager`
- Pass minimum unit tests

---

### T0.4 HashCreditManager — Borrower Registry + Credit Line Core
- Priority: P0
- Status: [x] DONE
- Purpose: Implement borrower registration, status management, payout reflection, and creditLimit calculation.
- work:
- Borrower registration (`registerBorrower`)
- Borrower status (Frozen, etc.)
- `submitPayout(payload)` calls the verifier and records the payout
    - replay protection(txid/vout)
- creditLimit update logic (simple version)
- borrow/repay routing (call vault)
- test:
- Registration success/duplicate prevention
- Prevent replay
- Limit increases when payout is reflected once
- Borrow revert exceeding limit
- Completion conditions:
- MVP demo flow (registration→payout→limit→borrow/repay) on-chain completion

---

### T0.5 RelayerSigVerifier — EIP-712 Signature Verification
- Priority: P0
- Status: [x] DONE
- Purpose: Verify the payout payload signed by the off-chain relayer on-chain.
- work:
- EIP-712 domain/struct definition
- Authorized relayer signer address management (setter is owner/role)
- payload: borrowerId, txid, vout, amountSats, blockHeight, nonce, deadline, chainId, etc.
- Nonce policy (optional) + parallel with txid/vout replay
- test:
- Pass correct signature
- signer mismatch revert
- deadline exceeded revert
- Resubmit same payload revert (or based on txid/vout)
- Completion conditions:
- Fully functional in `HashCreditManager.submitPayout()`

---

### T0.6 RiskConfig + Admin Controls (Minimal)
- Priority: P0
- Status: [x] DONE
- Purpose: Eliminate hard coding and make risk parameters replaceable.
- Parameters:
- confirmationsRequired (Relayer compliance in MVP, log only in on-chain)
    - advanceRateBps
    - windowSeconds(or payoutCount window)
    - newBorrowerCap
- globalCap (optional)
- work:
- owner/role based set function
- Event publication
- Completion conditions:
- Parameter changes are reflected immediately and verified through testing

---

### T0.7 PoolRegistry Hook (MVP-Ready)
- Priority: P0
- Status: [x] DONE
- Purpose: Even if “full source verification” cannot be fully implemented the first time, it will leave a hook in the code structure.
- work:
- `PoolRegistry` contract (allowlist based)
- Hook callable structure such as `isEligiblePayoutSource(...)` in `HashCreditManager`
- In MVP, only `true` is returned or administrator allowlist is applied.
- Completion conditions:
- Minimize ABI/storage changes when strengthening provenance in production

---

### T0.8 Offchain Relayer (Python) — Watch + Sign + Submit
- Priority: P0
- Status: [x] DONE
- Purpose: Detect Bitcoin payout and submit to EVM (core of hackathon demo).
- work:
- Select data source:
        - (A) Bitcoin Core RPC
- (B) mempool/esplora API (simple hackathon)
- Supervision logic:
- Monitor a list of specific payout addresses
- Obtain txid/vout/amount/blockHeight
- Check confirmations (if possible)
- Generate EIP-712 signature
- EVM tx submission (web3.py/ethers-rs, etc.)
- Dedupe to local DB (at least sqlite)
- Completion conditions:
- The demo runs with one real (or testnet) tx.

---

### T0.9 End-to-End Demo Script + README (Hackathon Submission Ready)
- Priority: P0
- Status: [x] DONE
- Purpose: To provide execution procedures that judges can understand within 5 minutes.
- work:
- Created `docs/guides/DEMO.md`
- Execution order (distribution → borrower registration → relayer execution → payout detection → borrow/repay)
- Screenshot/log example (optional)
- Completion conditions:
- Reproducible in a new environment by just looking at the documentation (at least for developers)

---

## P1 — Production Track: Bitcoin SPV (Checkpoint based)

### T1.1 SPV Design Finalization (ADR)
- Priority: P1
- Status: [x] DONE
- Purpose: Fix with ADR what safety/gas/operational assumptions Bitcoin SPV will be implemented with.
- include:
- checkpoint trust model (multisig/attestor set)
- Allowed range (retarget boundary rejection, header chain length limit)
- Support scriptPubKey type (P2WPKH priority)
- Completion conditions:
- Created and approved `docs/adr/0001-btc-spv.md`

---

### T1.2 CheckpointManager Contract
- Priority: P1
- Status: [x] DONE
- Purpose: Register/manage checkpoint header on-chain.
- work:
- Checkpoint set with multisig/owner privileges
- checkpoint change event
- Force height monotonic increase
- test:
- set revert without permission
- height decrease revert
- Completion conditions:
- `BtcSpvVerifier` can refer to checkpoint

---

### T1.3 BtcSpvVerifier — Header PoW + Merkle Inclusion + Output Parse (MVP level)
- Priority: P1
- Status: [x] DONE
- Purpose: Verify on-chain that rawTx is included in a specific block and that vout matches the borrower payout key.
- work:
- Verify sha256d(header) <= target(bits) (use precompiled sha256)
- prevHash chain connection verification
    - txid = sha256d(rawTx)
- Verification of merkleRoot reach with merkle branch (Bitcoin rules)
- rawTx vout parsing (minimum P2WPKH)
- test:
- Verification success/failure with fixed test vector (real data)
- Completion conditions:
- `HashCreditManager` works even if the verifier is replaced.

---

### T1.4 Proof Builder/Prover (Python)
- Priority: P1
- Status: [x] DONE
- Purpose: Construct header chain + merkle branch + rawTx required for submission.
- work:
- data source: Bitcoin Core RPC recommended (txindex may be required)
- Creation of proof payload
- Generate and send submission tx
- Completion conditions:
- Proof generation with specified txid → on-chain verification successful

---

### T1.5 Provenance Enhancement (Optional): Pool Cluster Registry + Heuristic Rules
- Priority: P1
- Status: [x] DONE
- Purpose: Reduce the possibility of self-transfer manipulation.
- work:
- Pool payout cluster allowlist (start of operation)
- Payout pattern rules (simple):
- Cap is fixed before minimum payout count is met
- One-time large deposits are partially reflected
- Completion conditions:
- Testing/documentation suggests that limit increases are limited in attack scenarios (circulation of own funds)

---

### T1.6 Creditcoin Testnet SPV Deployment Script + Wiring
- Priority: P1
- Status: [x] DONE
- Purpose: **Reproducibly deploy** the SPV stack on Creditcoin testnet (chainId=102031) and connect the Manager to use the SPV verifier.
- work:
- Add deployment script including `CheckpointManager` + `BtcSpvVerifier` (e.g. `script/DeploySpv.s.sol`)
- Call `HashCreditManager.setVerifier(BtcSpvVerifier)` after deployment (or deploy Manager as SPV verifier from the beginning)
- Output address summary to console + organize list of keys to put in `.env` (document/log)
- Completion conditions:
- By executing the script once on the Creditcoin testnet, the SPV-related contract address is obtained, and the Manager verifier is set to SPV.
- Completion summary:
    - Created `script/DeploySpv.s.sol` - full SPV mode deployment script
    - Deploys: MockUSDC → CheckpointManager → BtcSpvVerifier → RiskConfig → PoolRegistry → LendingVault → HashCreditManager
    - Manager is deployed with BtcSpvVerifier as verifier (not RelayerSigVerifier)
    - Console output includes all addresses and .env configuration guide
    - Usage: `forge script script/DeploySpv.s.sol --rpc-url $CREDITCOIN_TESTNET_RPC --broadcast`

---

### T1.7 Checkpoint registration tooling (Bitcoin Core RPC → CheckpointManager)
- Priority: P1
- Status: [x] DONE
- Purpose: **Bitcoin testnet** Read block header/meta from Bitcoin Core RPC and execute `CheckpointManager.setCheckpoint()` **without mistakes**.
- work:
- Add `set-checkpoint` command to `hashcredit-prover` (or separate script)
- Input: `height` (or `--height`), EVM `RPC_URL`, `PRIVATE_KEY`, `CHECKPOINT_MANAGER` address, Bitcoin RPC connection information
- Default (recommended): `BITCOIN_RPC_URL=http://127.0.0.1:18332` (Bitcoin Core `-testnet` RPC)
- `blockHash` uses **internal endian(bytes32)** calculated by sha256d from header bytes (to prevent endian confusion)
- Securely parse `timestamp` and `chainWork` from Bitcoin Core results
- Completion conditions:
- The checkpoint registration transaction with the specified height is successful, and `latestCheckpointHeight()` is updated.
- Completion summary:
    - Created `hashcredit_prover/evm.py` with EVMClient for contract interactions
    - Added `set-checkpoint` command to CLI
    - Fetches block header from Bitcoin RPC, computes internal hash, and calls setCheckpoint()
    - Supports --dry-run mode for testing without sending transactions
    - Updated README.md with command documentation

---

### T1.8 Borrower BTC Address → pubkeyHash registration tooling (BtcSpvVerifier)
- Priority: P1
- Status: [x] DONE
- Purpose: Receive the borrower's **Bitcoin testnet** address (P2WPKH bech32 `tb1...` / P2PKH base58 `m...`/`n...`), extract the **20-byte pubkey hash**, and run `BtcSpvVerifier.setBorrowerPubkeyHash()`.
- work:
- Address decoder implementation (bech32 v0 + base58check minimal implementation; minimizes dependency on external heavy libraries)
- Add `hashcredit-prover set-borrower-pubkey-hash --borrower 0x.. --btc-address ...` command
- After success, verify with `getBorrowerPubkeyHash(borrower)`
- Completion conditions:
- The pubkey hash is correctly registered with one actual BTC address, and then the SPV proof passes only to that address.
- Completion summary:
    - Created `hashcredit_prover/address.py` with bech32 and base58check decoders
    - Supports P2WPKH (tb1q.../bc1q...) and P2PKH (m.../n.../1...) addresses
    - Added `set-borrower-pubkey-hash` CLI command
    - Calls BtcSpvVerifier.setBorrowerPubkeyHash() with extracted pubkey hash
    - Added unit tests in tests/test_address.py
    - Updated README.md with command documentation

---

### T1.9 SPV Proof creation + EVM submission command (txid single shot)
- Priority: P1
- Status: [x] DONE
- Purpose: Before complex "watcher/relayer", provide a one-shot flow that creates a proof by entering one **Bitcoin testnet txid** and completes with `HashCreditManager.submitPayout()`.
- work:
- Added `hashcredit-prover submit-proof` command
- Input:
- Bitcoin: `txid`(display), `outputIndex`, `targetHeight`, `checkpointHeight` (or auto-select)
        - EVM: `RPC_URL`(Creditcoin), `CHAIN_ID=102031`, `PRIVATE_KEY`, `HASH_CREDIT_MANAGER`
        - borrower EVM address
- interior:
- Generate `abi.encode(SpvProof)` with ProofBuilder
- Send `HashCreditManager.submitPayout(bytes)` to web3.py + confirm receipt
- Completion conditions:
- By entering “1 txid”, the on-chain payout reflection transaction is successful.
- Completion summary:
    - Added `submit-proof` CLI command to hashcredit-prover
    - Uses existing ProofBuilder to generate SPV proof
    - Calls HashCreditManager.submitPayout(bytes) via EVMClient
    - Supports --dry-run and --hex-only modes for testing
    - Updated README.md with command documentation and examples

---

### T1.10 SPV Relayer (monitoring/automatic submission) + dedupe/confirmations
- Priority: P1
- Status: [x] DONE
- Purpose: Create the minimum relayer that can be operated and automate **Bitcoin testnet address monitoring → confirmations satisfaction → proof creation → submission → dedupe**.
- work:
- Bitcoin Core RPC-based address monitoring (at least: one of the txid list/block scan strategies)
- Checkpoint selection logic:
- Automatic selection of `checkpointHeight` to satisfy header chain length constraints (≤144)
- sqlite dedupe (can reuse existing relayer DB)
- Organizing failure cases (retry/log/cause exposure)
- Completion conditions:
- If you specify one address, payout transactions are automatically found and submitted, and duplicate submissions are prevented.
- Completion summary:
    - Created `watcher.py` with AddressWatcher and PayoutStore (SQLite dedupe)
    - Created `relayer.py` with SPVRelayer class for automatic proof submission
    - Added `run-relayer` CLI command with JSON addresses file input
    - Auto checkpoint selection within max_header_chain constraint
    - Configurable confirmations, poll interval
    - Updated README.md with relayer documentation

---

### T1.11 deterministic (offline) SPV fixtures + Manager E2E tests + documentation
- Priority: P1
- Status: [x] DONE
- Purpose: Create a **regression test of Bitcoin testnet-based SPV proof verification/submission** in a form that can be verified without a network, and complete the Creditcoin testnet standard operation document.
- work:
- Store actual mainnet/testnet tx-based (or at least fixed data-based) proof components in `test/fixtures/`
- Added `BtcSpvVerifier.verifyPayout()` success/failure test (merkle/header chain/output mismatch, etc.)
- Added E2E test leading to `HashCreditManager.submitPayout()` (increase creditLimit + prevent replay)
- Added Creditcoin testnet SPV mode execution/debugging section to `docs/guides/LOCAL.md`.
- Completion conditions:
- With `forge test`, the core verification of the SPV path can be stably reproduced, and it can be executed end-to-end on the testnet just by looking at the document.
- Completion summary:
    - Created `test/SpvE2E.t.sol` with 8 E2E tests for SPV verification flow
    - Tests: deployment, borrower registration, checkpoint registration, error cases
    - Uses synthetic but structurally valid Bitcoin data for deterministic testing
    - Updated `docs/guides/LOCAL.md` with comprehensive SPV mode execution guide
    - Includes checkpoint registration, borrower setup, proof submission, relayer usage
    - All 143 tests passing

---

### T1.12 Frontend Scaffolding (Vite + React) + Contract Inquiry Dashboard
- Priority: P1
- Status: [x] DONE
- Purpose: Create a **web dashboard** where interns/judges can immediately see “what the current status is” (focus on reading for now).
- work:
- Create `apps/web` (Vite + React + TS)
- Environment variable template: `apps/web/.env.example` (`VITE_RPC_URL`, `VITE_CHAIN_ID=102031`, `VITE_HASH_CREDIT_MANAGER`, `VITE_BTC_SPV_VERIFIER`, `VITE_CHECKPOINT_MANAGER`, etc.)
- Screen:
- Connection status (wallet connected / chainId / current account)
- Manager information: `owner`, `verifier`, `stablecoin`, `getAvailableCredit(borrower)`, `getBorrowerInfo(borrower)` lookup
- Checkpoint information: `latestCheckpointHeight`, `getCheckpoint(height)` query (read)
- Documentation of deployment/execution commands (`npm/pnpm install`, `dev`, `build`)
- Completion conditions:
- You can check the Manager/Checkpoint status through RPC read-only in the browser (even without a wallet).
- Completion summary:
- Added `apps/web` Vite + React + TS scaffolding
- Supports Creditcoin testnet RPC/address setting with `apps/web/.env.example`
- Manager/Borrower/Checkpoint/SPV verifier read-only dashboard implementation
- Confirm passing `npm run lint` and `npm run build` in `apps/web`

---

### T1.13 Frontend Write Flow (Submit Payout Proof / Borrow / Repay)
- Priority: P1
- Status: [x] DONE
- Purpose: To enable “writing” required in SPV E2E to be performed through the UI (operational convenience).
- work:
- Wallet connection (MetaMask, etc.) + Creditcoin testnet network guidance (or automatic addition)
    - `submitPayout(bytes)`:
- The user pastes the proof hex (`0x...`) selected by `hashcredit-prover` and submits it.
- tx hash/receipt/error message display
    - `borrow(uint256)`:
- Enter amount (including 6 decimals guide) and send borrow tx
    - `repay(uint256)`:
- Provide `stablecoin.approve(manager, amount)` button before repayment (if necessary)
- send repay tx
- Completion conditions:
- Proof submission is successful once in the UI + borrower borrow/repay (including approve) is executed.
- Completion summary:
- Wallet connection + Add chain switch button based on `wallet_switchEthereumChain`/`wallet_addEthereumChain`
- `submitPayout(bytes)`/`borrow(uint256)`/`approve(spender,amount)`/`repay(uint256)` can be sent from the UI
- Added buttons for administrator: `registerBorrower`, `setVerifier`, `setBorrowerPubkeyHash`
- Added transaction status (pending/confirmed/error) display panel

---

### T1.14 (Optional) Frontend ↔ Prover/Bitcoin Core Bridge API
- Priority: P2
- Status: [x] DONE
- Purpose: Since browsers cannot attach directly to Bitcoin Core RPC, we provide a thin API that **runs the probe locally/on a server** (fully automated option).
- work:
- Minimum HTTP API in `apps/api` (or `offchain/api`):
        - `POST /spv/build-proof` (txid/outputIndex/targetHeight/borrower → proof hex)
        - `POST /checkpoint/set` (height → checkpoint tx)
- Authentication/Security:
- Local only (default `127.0.0.1` binding) + simple token/allowlist
- Call API from `apps/web` to create proof/register checkpoint with one click on UI (optional)
- Completion conditions:
- (Local standard) You can create and submit proof at once by simply entering the txid in the UI (optional).
- Completion summary:
    - Created `offchain/api` with FastAPI-based HTTP server
    - Endpoints: `POST /spv/build-proof`, `POST /spv/submit`, `POST /checkpoint/set`, `POST /borrower/set-pubkey-hash`, `GET /health`
    - Local-only binding (127.0.0.1) with optional token authentication via X-API-Key header
    - CORS configured for frontend integration
    - Auto-generated OpenAPI docs at /docs and /redoc
    - 11 unit tests passing

---

## P2 — Polishing / Security / Launch Readiness

### T2.1 Gas Profiling + Limits
- Priority: P2
- Status: [x] DONE
- Purpose: Set upper limits on proof submission cost and loop length (merkle branch/hdr chain).
- work:
    - branch length max
    - header chain max
- Clarification of revert reason
- Completion conditions:
- Documentation of costs/caps
- Completion summary:
    - Limits already defined in BtcSpvVerifier: MAX_HEADER_CHAIN=144, MAX_MERKLE_DEPTH=20, MAX_TX_SIZE=4096, MIN_CONFIRMATIONS=6
    - Created `test/GasProfile.t.sol` with 23 gas profiling tests
    - Created `docs/gas-limits.md` documenting all gas costs and limits
    - Key findings: verifyMerkleProof scales ~1,640 gas/level, submitPayout ~150K gas, worst-case SPV proof ~450K gas

---

### T2.2 Audit Checklist + Threat Model Doc
- Priority: P2
- Status: [x] DONE
- Purpose: Create security documents for reviewer/VC/outsourcing handover.
- Output:
    - `docs/threat-model.md`
    - `docs/audit-checklist.md`
- Completion conditions:
- Responses to major threats (oracle compromise, replay, reorg, self-transfer, key loss) have been organized.
- Completion summary:
    - Created `docs/threat-model.md` covering 8 threat categories with mitigations
    - Created `docs/audit-checklist.md` with 15 sections for comprehensive code review
    - Documented oracle compromise, replay, reorg, self-transfer, key loss threats and defenses
    - Includes trust boundaries diagram, defense-in-depth layers, incident response guidance

---

### T2.3 (Critical) SPV Difficulty(bits) verification + Retarget Boundary blocking
- Priority: P0
- Status: [x] DONE
- Purpose: Eliminate the vulnerability of `BtcSpvVerifier` accepting **arbitrarily lowered bits (easy difficulty)**, making it impossible to increase the limit unlimitedly with fake header chain/fake payout.
- Background:
- Currently, `_verifyHeaderChain()` in `contracts/BtcSpvVerifier.sol` does not verify that `header.bits` is “the expected value for the height” (only comments).
- In this state, an attacker can easily create `bits` and “mine” the header in a short period of time to forge the SPV.
- work:
- Extends `CheckpointManager`/`ICheckpointManager` to store **difficulty anchors** (e.g. `bits` or `header` bytes) on checkpoints.
- Option A: `Checkpoint { ... uint32 bits; }`
- Option B: Store `bytes header` in `Checkpoint` + Verify `blockHash == sha256d(header)`
- Force the following in `_verifyHeaderChain()`:
- Prohibit retarget boundary crossing: `(checkpointHeight / 2016) == (targetHeight / 2016)` (based on mainnet)
- Chain-wide `header.bits == checkpointBits` (assuming the same difficulty epoch)
- (When applying for testnet/league testing) Specify whether to use the testnet special difficulty rule, and if not supported, clearly state/document the reason for revert.
- `set-checkpoint`/API of `offchain/prover` also updated to match new fields (bit/header extraction)
- ADR/Document update: Specify actual implementation constraints/supported networks in `docs/adr/0001-btc-spv.md`
- test:
- "lower bits" attack case: **must revert** if you submit a header chain with the correct prevHash link + easy bits
- retarget boundary crossing case: proof that crosses the boundary **must be reverted**
- Normal case: Header chain verification successful within the correct bits/epoch (preferably fixture-based)
- Completion conditions:
- `BtcSpvVerifier` rejects header chains with **bits** that do not match the checkpoint difficulty.
- The above test is included in `forge test` to prevent regression.
- Completion summary:
- Add `uint32 bits` field to ICheckpointManager.Checkpoint struct.
- Add and verify bits parameter to CheckpointManager.setCheckpoint()
- Added bits verification and retarget boundary crossing verification in BtcSpvVerifier._verifyHeaderChain()
- New error types: `DifficultyMismatch(expected, actual)`, `RetargetBoundaryCrossing(checkpointHeight, targetHeight)`
- Support for extracting and submitting bits from offchain prover/API
- Tests: test_verifyPayout_revertsOnDifficultyMismatch, test_verifyPayout_revertsOnRetargetBoundaryCrossing
- Updated ADR 0001 document

---

### T2.4 (Critical) SPV Confirmations definition/verification method modification
- Priority: P0
- Status: [x] DONE
- Purpose: Correct the proof structure/verification so that `MIN_CONFIRMATIONS` does not mean “checkpoint↔txBlock distance” but **how many blocks deep the block containing tx is compared to the tip**.
- Background:
- Currently `contracts/BtcSpvVerifier.sol` only checks `headers.length >= MIN_CONFIRMATIONS`, which is different from the normal meaning of confirmations.
- work:
- Redefine proof format (recommended):
- Provides `headers` from `checkpoint+1 → tip`
- Added `txBlockIndex` (= block index containing tx in headers) field
- Verify confirmations: `headers.length - 1 - txBlockIndex >= MIN_CONFIRMATIONS - 1`
- Use `merkleRoot` of `headers[txBlockIndex]` when verifying merkle proof.
- Modify the existing `offchain/prover` proof builder/CLI/API to fit the new format.
- Organized so that `PayoutEvidence.blockHeight` is accurately calculated as “block height including tx”
- test:
- Case of lack of confirmations: revert if txBlockIndex is too close to tip in tip chain
- Normal case: Verification succeeds when MIN_CONFIRMATIONS is met.
- Documentation/example: Update proof input value meaning in `docs/guides/LOCAL.md` (or related guide)
- Completion conditions:
- "confirmations" act as a general definition and are guaranteed by testing.
- Completion summary:
- Add `txBlockIndex` field to SpvProof struct (uint32)
- Confirmations calculation: `headers.length - txBlockIndex >= MIN_CONFIRMATIONS`
- Merkle proof is verified with merkleRoot of `headers[txBlockIndex]`
- `PayoutEvidence.blockHeight` is calculated accurately as block height including tx
- New error type: `TxBlockIndexOutOfRange(txBlockIndex, headersLength)`
- Added `_verifyHeaderChainFull()` function to parse/return all headers
- Add `tip_height` parameter to `build_proof()` of offchain prover (default: target+5)
- Test: txBlockIndex out of range, insufficient confirmations, verify confirmations calculation
- Add SPV Proof Format document to `docs/guides/LOCAL.md`

---

### T2.5 (Critical) Prevention of Griefing/DoS due to direct Verifier call
- Priority: P0
- Status: [x] DONE
- Purpose: Eliminate DoS where a third party permanently blocks `HashCreditManager.submitPayout()` by preempting `_processedPayouts` by **directly calling** `RelayerSigVerifier.verifyPayout()`/`BtcSpvVerifier.verifyPayout()`.
- Task (select 1 or combination):
- Option A (recommended): Remove `_processedPayouts`/replay check from verifier → Unify replay into `HashCreditManager.processedPayouts` single layer
- Option B: store `manager` in verifier and limit `verifyPayout()` to `onlyManager` (+ manager changes/events)
- Option C: The verifier does not consider the replay as a “verification failure” and returns evidence (however, the manager prevents the final replay)
- `contracts/interfaces/IVerifierAdapter.sol` design cleanup (reconsider whether verify should be stateful)
- test:
- Reproducing the attack scenario: Even if the attacker calls the verifier first, is `HashCreditManager.submitPayout()` processed normally?
- Is replay only blocked by the manager (submit the same txid/vout twice and revert)?
- Completion conditions:
- Payout processing is not blocked by calling the verifier directly.
- Replay prevention works consistently only on a single layer (or intended layer).
- Completion summary:
- Implement Option A: Remove `_processedPayouts` from verifier, unify replay into a single layer of Manager.
- BtcSpvVerifier: Remove `_processedPayouts` mapping/checking/marking, `isPayoutProcessed()` always returns false
- RelayerSigVerifier: Same as modified to stateless
- MockVerifier: Test mocks are also modified to be stateless.
- Added tests: `test_griefingPrevention_verifierDirectCall()`, `test_replayProtectionOnlyInManager()`
- Modification of existing test: update verifier replay test to stateless behavior

---

### T2.6 (High) LendingVault interest accumulation (totalAssets) bug fix + Share Dilution prevention
- Priority: P1
- Status: [x] DONE
- Purpose: Solve the problem that the `accumulatedInterest` accumulated with `_accrueInterest()` in `LendingVault` is not reflected in `totalAssets()`, and the **share price is distorted/diluted** during intermediate calls (e.g. deposit/withdraw/borrow/repay).
- work:
    - `contracts/LendingVault.sol`:
- Include `accumulatedInterest` in `totalAssets()` (or remove accumulated variables and refactor them to a structure that is always calculated correctly)
- Cleaning up unused constants/variables such as `PRECISION`
- (Optional) Clarify naming/comment of `actualRepay` in `repayFunds` as “principal vs interest”
- test:
- Added test to prevent new depositor from taking interest for free (preventing share dilution) when making “additional deposit after interest accrual”
- Reinforced testing to see if it matches the expected value when “withdrawing after accruing interest”
- Completion conditions:
- Interest accumulation is consistently reflected in `totalAssets()/convertToShares/convertToAssets` in any calling order.
- Completion summary:
- Modify `totalAssets()`: `balanceOf + totalBorrowed + accumulatedInterest + _pendingInterest()`
- `repayFunds()` modification: `accumulatedInterest` is deducted when the interest portion comes in (prevent double calculation)
- Add Share dilution prevention test: `test_shareDilutionPrevention_depositAfterInterestAccrual()`
- `accumulatedInterest` reflection test: `test_accumulatedInterestIncludedInTotalAssets()`
- Interest deduction tests: `test_interestDeductionOnRepay()`, `test_partialInterestRepay()`

---

### T2.7 (High) Manager/Vault interest model consistency (debt interest reflection) implementation
- Priority: P1
- Status: [x] DONE
- Purpose: Currently, `HashCreditManager.currentDebt` does not reflect interest, so the borrower cannot repay the interest, and it is inconsistent with the interest model of `LendingVault`. Interest is reflected in the borrower debt so that the interest income actually accrues to the vault.
- work:
- Design selection:
- (A) In the Manager, `currentDebt` is increased over time as an interest index (borrowIndex), and repayment is made in the order of interest → principal.
- (B) Vault tracks “debt including interest” and manager tracks only principal (however, borrower repayment UX/accurate debt calculation is required)
- Modified `HashCreditManager.repay()` to support “principal + interest” repayment (reexamine current cap logic)
- UI/off-chain: Add endpoint/view so borrowers can view/repay current debt (including interest)
- test:
- Borrow → Time passes → When repaying, debt increases including interest, and after repaying, vault balance/totalBorrowed (or accounting) changes as expected.
- Edge cases such as repayment amount less than interest/interest+principal/excess
- Completion conditions:
- The borrower can actually repay the interest, and LP profits match both accounting and actual token flows.
- Completion summary:
- Add `lastDebtUpdateTimestamp` field to `IHashCreditManager.BorrowerInfo`
- Added `getCurrentDebt(address)` and `getAccruedInterest(address)` functions to `IHashCreditManager`
- Implementation of `HashCreditManager._calculateAccruedInterest()`: Calculate time-based interest by querying Vault's borrowAPR()
- `borrow()` modification: add existing accrued interest to principal and add new borrow
- Modify `repay()`: Repay interest first, repay principal with remaining amount, transfer entire amount to Vault
- Modification of `getAvailableCredit()`: Calculate available credit based on total debt including interest.
- Added 7 tests: interest accrual, repay interest first, repay capped, compound interest, available credit with interest, vault receives interest

---

### T2.8 ERC20 safety (SafeERC20) + Approval compatibility + Reentrancy defense
- Priority: P2
- Status: [x] DONE
- Purpose: Add defense against non-standard ERC20 (return value false, approve=0 prerequisite, etc.) and token callback-based reentrancy.
- work:
- OpenZeppelin `SafeERC20`/`ReentrancyGuard` introduced
    - `contracts/HashCreditManager.sol`/`contracts/LendingVault.sol`:
- Replace `transfer/transferFrom/approve` with `safeTransfer/safeTransferFrom/safeIncreaseAllowance` (or safeApprove pattern)
- Apply `nonReentrant` to external token call paths such as `deposit/withdraw/repay` and reexamine the status update order (especially deposit)
- test:
- Added regression test with mock “Return false ERC20”, “Requires approve 0 ERC20”
- Verify that share/debt invariants are not broken in reentrancy scenarios (ERC777 style mocks if possible)
- Completion conditions:
- Token compatibility/re-entrancy attack surface is reduced and guaranteed through testing.
- Completion summary:
- OpenZeppelin `SafeERC20` and `ReentrancyGuard` introduced (lib/openzeppelin-contracts)
    - `LendingVault.sol`: `transfer` → `safeTransfer`, `transferFrom` → `safeTransferFrom`
- `LendingVault.sol`: Apply `nonReentrant` to `deposit`, `withdraw`, `borrowFunds`, `repayFunds`
    - `HashCreditManager.sol`: `transferFrom` → `safeTransferFrom`, `approve` → `forceApprove`
- `HashCreditManager.sol`: Apply `nonReentrant` to `borrow`, `repay`
- Add Mock tokens: `MockUSDT` (requires approve 0), `MockNoReturnERC20` (no return value), `ReentrantToken` (based on callback)
- Added 9 tests: USDT-style compatibility, no-return token compatibility, reentrancy defense

---

### T2.9 Trailing Revenue Window actual application + Min Payout filtering
- Priority: P1
- Status: [x] DONE
- Purpose: Actually apply the trailing revenue window that matches `RiskConfig.windowSeconds` and prevent spam/fine payouts below `minPayoutSats` from accumulating to the limit.
- work:
    - `contracts/HashCreditManager.sol`:
- Add logic to exclude (pruning) payout events from the window based on time (select data structure considering gas/storage)
- Specifies validation policy for validity (future/past tolerance range) of `evidence.blockTimestamp`
- If less than `minPayoutSats`, effectiveAmount=0 is processed or revert/ignore policy is determined.
- `contracts/RiskConfig.sol`/Document:
- Clearing up current semantic confusion where trailing window and new borrower period share the same `windowSeconds` (separate parameters if necessary)
- test:
- Is creditLimit reduced/recalculated when payout expires at the window boundary?
- Does less than min payout affect creditLimit?
- Completion conditions:
- The trailing window actually works, and limit accumulation is not possible with spam payout.
- Completion summary:
    - Add payout history storage with MAX_PAYOUT_RECORDS=100 DoS protection
    - Implement lazy pruning of expired payouts in trailing window
    - Add minPayoutSats filtering (below-minimum payouts marked processed but don't count toward credit)
    - Separate newBorrowerPeriodSeconds from windowSeconds in RiskParams
    - Add PayoutRecord struct, PayoutBelowMinimum and PayoutWindowPruned events
    - Add getPayoutHistoryCount() and getPayoutRecord() view functions
    - 8 new tests for trailing window, min payout filtering, and DoS protection

---

### T2.10 txid Endianness/Standardization (on-chain↔off-chain consistency)
- Priority: P2
- Status: [x] DONE
- Purpose: Since the txid expression (display big-endian vs. internal little-endian) is different for each component, which may cause confusion when replacing/operating the verifier, set the "protocol standard txid byte order" and apply it to all sections.
- work:
- Standard definition: `bytes32 txid` is unified as “Bitcoin internal bytes (as is sha256d result)” (recommended)
- `txid_to_bytes32` operation/comment correction and reverse processing of `offchain/relayer` applied
- `offchain/prover` proof builder also organizes txid calculation/verification logic to meet standards
- Update documentation/examples (input txid format, hex reverse or not)
- test:
- Verify through unit tests that txid is treated the same in relayer/prober/on-chain for the same tx
- Completion conditions:
- txid-related bugs/operational confusion (duplicate processing, verification failure) are eliminated through standardization.
- Completion summary:
    - Fix relayer's txid_to_bytes32() to reverse bytes (display -> internal format)
    - Add bytes32_to_txid_display() for reverse conversion (debugging)
    - Add explicit txid_display_to_internal() and txid_internal_to_display() to prover
    - Update docstrings with clear byte order documentation
    - Add unit tests for txid conversion in both relayer and prover
    - Add consistency test verifying same display txid produces identical bytes
    - Document txid format standard in LOCAL.md appendix
    - Protocol standard: bytes32 txid = internal byte order (sha256d result without reversal)

---

### T2.11 Offchain API authentication/deployment hardening (token/CSRF/proxy safety)
- Priority: P2
- Status: [x] DONE
- Purpose: `request.client.host` based local bypass can create authentication bypass when exposing local API as 0.0.0.0 or behind a reverse proxy, so harden it to a safe default/policy.
- work:
    - `offchain/api/hashcredit_api/auth.py`:
- **Token is always required** if `API_TOKEN` is set (removes local bypass)
- Remove support for query param token (`?api_key=`) (risk of log/referrer leakage)
- (Optional) Minimal CSRF defense based on `Origin`/`Host` (only for write endpoints)
- Document: Warning and recommended deployment (firewall/proxy) specified when using `HOST=0.0.0.0`
- test:
- Unit test that the token policy works as intended for each local/non-local request.
- Completion conditions:
- Even if the API is exposed incorrectly, key use/transaction transfer is not possible with “tokenless”.
- Completion summary:
    - Remove local bypass in auth.py: when API_TOKEN is set, ALL requests require token
    - Remove query param token support (?api_key=) to prevent log/referrer leakage
    - Add security documentation warnings for HOST=0.0.0.0 usage
    - Add WWW-Authenticate header to 401 responses
    - 6 new authentication tests: token required, valid/invalid token, no local bypass, no query param
    - Update README.md with security notes and deployment guidelines

---

### T2.12 Offchain Watcher: Remove float from BTC value → satoshis conversion
- Priority: P2
- Status: [x] DONE
- Purpose: If Bitcoin Core RPC's `vout.value` is processed as a float (`* 1e8`), amount errors may occur due to rounding/precision issues, so satoshis are **accurately** calculated based on Decimal.
- work:
    - `offchain/prover/hashcredit_prover/watcher.py`:
- Convert to `Decimal(str(value)) * Decimal("1e8")` and integerize (accuracy guaranteed)
- Handling cases where value comes as a string/integer/float, etc.
- test:
- Added unit test to ensure satoshis conversion is accurate for representative values ​​(0.1, 0.00000001, etc.)
- Completion conditions:
- amount_sats calculation does not depend on float precision.
- Completion summary:
    - Add btc_to_sats() function using Decimal arithmetic for exact conversion
    - Handle int, float, str, Decimal inputs with proper type handling
    - Raise ValueError for fractional satoshis (more than 8 decimal places)
    - Replace `int(value * 1e8)` with btc_to_sats() in AddressWatcher.scan_block()
    - 17 unit tests covering precision edge cases (0.1, 0.2, 0.3 BTC), type handling, and float vs Decimal comparison

---

### T2.13 Security CI/verification automation (slither/fuzz/invariant)
- Priority: P2
- Status: [x] DONE
- Purpose: Include static analysis/fuzzing/invariant testing in CI to prevent regression.
- work:
- (Optional) Introduction of `slither`/`solhint` and addition of CI workflow
- Added Foundry fuzz/invariant tests:
- Vault share invariant (share pricing compared to totalAssets)
- manager replay invariant (same txid/vout cannot be duplicated)
- borrow/repay invariants (totalGlobalDebt consistency)
- Completion conditions:
- Minimum security checks run automatically in PR/local, and in case of failure, the cause can be identified.
- Completion summary:
    - Add `test/invariant/Invariant.t.sol` with 6 invariant tests:
      - VaultInvariantTest: totalAssetsGeShares, roundingFavorsVault, ghostAccounting
      - ManagerInvariantTest: noReplayPossible, debtAccountingConsistent, borrowNeverExceedsLimit
    - Update `.github/workflows/test.yml`:
      - Add invariant test step with FOUNDRY_INVARIANT_RUNS=50
      - Add slither static analysis job with artifact upload
      - Add Python tests job for offchain components
    - Add `slither.config.json` for Slither configuration
    - All 6 invariant tests passing

---

### T2.14 (Ops) Addition of operational safety devices such as Multisig/Timelock/Pause
- Priority: P2
- Status: [x] DONE
- Purpose: Reduce single admin key risk (multisig/time lock) and enable incident response (pause).
- work:
- Document/Script:
- Guide/script summary for setting owner to multisig when deploying to production
- Summary of time lock application method for sensitive parameter change (Verifier/Vault/RiskConfig)
- (Optional) On-chain:
- Added `pause()/unpause()` to `HashCreditManager`/`LendingVault` (write function guard)
- Review of introduction of 2-step ownership (Ownable2Step) pattern
- Completion conditions:
- A “procedure + technical hook” is provided for operators to respond to key accidents/anomalies.
- Completion summary:
    - Add OpenZeppelin Pausable to HashCreditManager
    - Implement pause()/unpause() functions (onlyOwner)
    - Apply whenNotPaused modifier to submitPayout(), borrow(), repay()
    - Update docs/guides/DEPLOY.md with:
      - Pause functionality documentation
      - Gnosis Safe multisig setup guide
      - Timelock integration guidance
      - Key management checklist
      - Incident response procedures
      - Contract upgrade path documentation
    - All 186 tests passing

---

### T2.15 Offchain DB: SQLite → Postgres porting (common schema/migration)
- Priority: P1
- Status: [x] DONE
- Purpose: Remove file-based SQLite (`relayer.db`) dependency from Railway deployments and port all off-chain components to use **Postgres(DATABASE_URL)**.
- work:
- Target range:
        - `offchain/relayer`(MVP relayer) dedupe DB
        - `offchain/prover`(SPV relayer/watcher) dedupe DB
- Common schema design (minimum):
- Migrate current tables to Postgres, such as `processed_payouts`(txid,vout unique) or `submitted_payouts`/`pending_payouts`
- Guaranteed idempotence: `UNIQUE(txid, vout)` + upsert pattern
- Add DB access layer:
- Create engine/connection based on `DATABASE_URL` (Postgres URL first, sqlite is allowed for local)
- (Recommended) Unify with SQLAlchemy 2.x + `psycopg`(sync) / `asyncpg`(async)
- Migration:
- Introduce Alembic or provide a "schema init command" (must be reproducible in operation)
- Define migration execution flow when deploying Railway (Release Command, etc.)
- Documentation updates:
- Updated `DATABASE_URL=sqlite...` section in `docs/guides/LOCAL.md` to include Postgres options.
- test:
- On local Postgres (e.g. docker compose):
- When processing duplicates (txid, vout), is it saved/submitted only once?
- Is dedupe maintained even after process restart?
- Completion conditions:
- When Railway Postgres is attached, relayer/prover operates normally without local files.
- Completion summary:
    - Migrate relayer PayoutDatabase to SQLAlchemy with SQLite/PostgreSQL support
    - Migrate prover PayoutStore to SQLAlchemy with SQLite/PostgreSQL support
    - Add psycopg2-binary to both relayer and prover dependencies
    - Support postgres:// URL format (Railway) with automatic conversion to postgresql://
    - Use ON CONFLICT DO UPDATE/DO NOTHING for PostgreSQL idempotent upserts
    - Use INSERT OR REPLACE/IGNORE for SQLite backwards compatibility
    - Auto-detect backend from DATABASE_URL and use appropriate SQL dialect

---

### T2.16 hashcredit-relayer (Postgres) applied + DATABASE_URL standardized
- Priority: P2
- Status: [x] DONE
- Purpose: Allows `offchain/relayer` to receive `DATABASE_URL=postgresql://...` and operate as Postgres (currently only parses sqlite path).
- work:
    - `offchain/relayer/hashcredit_relayer/config.py`:
- Standardize `DATABASE_URL` to be compatible with Railway Postgres URL (`postgresql://` / `postgres://` supported)
    - `offchain/relayer/hashcredit_relayer/db.py`:
- Remove direct use of sqlite3 or implement Postgres support
- Idempotent processing (upsert) on UNIQUE conflicts in transaction/isolation level/concurrency
    - `offchain/relayer/hashcredit_relayer/relayer.py`:
- Remove sqlite URL parsing logic (or leave only fallback)
- test:
- Does `is_processed/mark_processed/update_status` work when connecting to Postgres with pytest?
- Completion conditions:
- You can switch SQLite ↔ Postgres with only `DATABASE_URL` (operation is Postgres).
- Completion summary:
    - (Completed as part of T2.15)
    - Replaced sqlite3 with SQLAlchemy in db.py
    - Added parse_database_url() to handle postgres:// → postgresql:// conversion
    - Updated relayer.py to pass database_url directly to PayoutDatabase
    - All 6 relayer tests passing

---

### T2.17 hashcredit-prover(SPV relayer) Postgres porting + Watcher DB URL conversion
- Priority: P2
- Status: [x] DONE
- Purpose: Make `PayoutStore`/`run-relayer --db` of `offchain/prover` work with **DB URL** rather than file path, so that it can be operated on Railway.
- work:
    - `offchain/prover/hashcredit_prover/watcher.py`:
- Remove direct use of sqlite3 or implement Postgres support
- Define idempotent upsert and index for `pending_payouts/submitted_payouts`.
    - `offchain/prover/hashcredit_prover/cli.py`:
- Extend/change `--db` to `--database-url` (or `DATABASE_URL` envvar) (decide whether to maintain existing compatibility)
    - `offchain/prover/hashcredit_prover/relayer.py`:
- Organize life cycle such as store creation/close (prevent connection leak)
- test:
- Even if the same payout is observed multiple times, pending/submitted are not duplicated.
- Completion conditions:
- Even if you run `hashcredit-prover run-relayer` as a railway worker, the DB is maintained permanently.
- Completion summary:
    - (Completed as part of T2.15)
    - Replaced sqlite3 with SQLAlchemy in watcher.py PayoutStore
    - Added parse_database_url() for URL normalization (supports file paths for backwards compat)
    - Use ON CONFLICT DO NOTHING for PostgreSQL idempotent inserts
    - Added close() method for proper connection lifecycle
    - sqlalchemy and psycopg2-binary added to prover dependencies
    - All 17 prover watcher tests passing

---

### T2.18 Railway deployment preparation (service separation, environment variables, migration, health check)
- Priority: P1
- Status: [x] DONE
- Purpose: Configure railway to distribute off-chain components as **API service + Worker (relayer/prover)**.
- work:
- Service design (recommended):
- Service A: `offchain/api` (FastAPI) — called by FE
- Service B: `offchain/prover` or `offchain/relayer` worker — periodically watch/submit
- Railway Postgres add-on connection
- Execute command/port:
- Set `offchain/api` to be bound to `0.0.0.0:$PORT` (`PORT` env supported)
- worker defines a persistent execution command (e.g. `hashcredit-prover run-relayer ...`)
- Run migration:
- Script/documentation to run DB migrate once during deploy/release phase
- Settings/Secret:
- `PRIVATE_KEY`, `BITCOIN_RPC_PASSWORD`, `API_TOKEN`, etc. are injected only as Railway secrets.
- Contract addresses (`HASH_CREDIT_MANAGER`, `CHECKPOINT_MANAGER`, `BTC_SPV_VERIFIER`) are injected as environment variables.
- document:
- Add Railway section to `docs/guides/DEPLOY.md` (or create new `docs/guides/RAILWAY.md`)
- test:
- In Railway staging (or local docker):
- Check API `/health`
- Check the log to see if the worker actually records/prevents duplication and submits to the DB.
- Completion conditions:
- A reproducible deployment procedure is documented with the combination of "API + Worker + Postgres" in Railway.
- Completion summary:
    - Add PORT env var support to API config (Railway standard via pydantic validation_alias)
    - Add HOST alias for external binding configuration (0.0.0.0)
    - Change prover CLI --db to --database-url with DATABASE_URL env var support
    - Update RelayerConfig.db_path to database_url for consistency with PostgreSQL support
    - Add Procfile for API service (`python -m hashcredit_api.main`)
    - Add Procfile for prover worker service (`hashcredit-prover run-relayer`)
    - Create comprehensive docs/guides/RAILWAY.md with architecture, deployment steps, env vars reference, security checklist
    - All 186 Solidity tests passing, 61 prover tests passing, 17 API tests passing

---

### T2.19 Vercel FE deployment preparation (API URL/CORS/environment variables)
- Priority: P2
- Status: [x] DONE
- Purpose: Upload FE to Vercel and organize environment variables/CORS to communicate safely with Railway API.
- work:
    - `apps/web`:
- Added `VITE_API_URL` (Railway API base URL) and updated `.env.example`
- (Optional) If there is an API-linked flow such as proof build/submit, organize it according to Vercel environment variables.
    - `offchain/api`:
- Added guide to inserting Vercel domain into `ALLOWED_ORIGINS`
- (in conjunction with security ticket T2.11) harden token/authentication policy to deployment defaults
- document:
- Vercel environment variable list/setting method added to `docs/guides/DEPLOY.md`
- Completion conditions:
- The Vercel FE ↔ Railway API call operates without CORS errors, and the operating secret is not exposed to FE.
- Completion summary:
    - Add VITE_API_URL env var to apps/web/.env.example for optional API integration
    - Add comprehensive Vercel deployment section to docs/guides/DEPLOY.md
    - Document CORS configuration for Railway API ↔ Vercel FE integration
    - Add security notes: no private keys in VITE_* vars, token handling guidance
    - Add Full Stack Deployment Checklist covering contracts, Railway, and Vercel
    - Frontend build verified successfully (vite build → dist/)
