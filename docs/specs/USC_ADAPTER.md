# USC Adapter Design (for HashCredit)

## Goal
- Keep `HashCreditManager` unchanged.
- Add a USC-backed verifier that still satisfies `IVerifierAdapter`.
- Allow switching with `HashCreditManager.setVerifier(...)`.

## Current vs Target
- Current MVP path:
  - Offchain relayer reads BTC payouts from mempool API.
  - Relayer signs EIP-712 payload.
  - `RelayerSigVerifier.verifyPayout()` returns `PayoutEvidence`.
- Current SPV path:
  - Offchain prover builds Bitcoin SPV proof from Bitcoin Core RPC.
  - `BtcSpvVerifier.verifyPayout()` returns `PayoutEvidence`.
- Target USC path:
  - Offchain worker builds USC query/proof payload.
  - `UscVerifierAdapter.verifyPayout()` verifies via USC v2 precompile flow.
  - Adapter converts verified result into `PayoutEvidence`.

## Adapter Contract Boundary
- Input: `bytes proof` (USC query/proof envelope, adapter-defined).
- Output: `PayoutEvidence` matching `contracts/interfaces/IVerifierAdapter.sol`.
- Replay: keep in `HashCreditManager.processedPayouts` (not verifier-local), same as current design.

## Required Mapping
- `borrower` (EVM address)
- `txid` (`bytes32`, Bitcoin internal byte order)
- `vout` (`uint32`)
- `amountSats` (`uint64`)
- `blockHeight` (`uint32`)
- `blockTimestamp` (`uint32`)

## Offchain Changes Needed
- New worker module for USC proof production.
- Encoding spec for adapter `proof` bytes.
- Deterministic txid endianness conversion (display <-> internal) aligned with existing relayer/prover.

## Compatibility Notes
- This repository currently targets Creditcoin EVM and custom verifier adapters.
- USC-native verification route is not wired yet.
- Chain ID defaults in this repo are Creditcoin testnet (`102031`), while USC quickstart examples may use different chains.

## Gaps / Open Questions
- Whether target USC environment supports Bitcoin as a first-class source chain for your query type.
- Exact USC v2 precompile method signatures and response schema to decode in adapter.
- Gas/size limits for query payloads vs current SPV proof size.

## Implementation Checklist
1. Define adapter proof ABI schema (`proof` envelope).
2. Implement `UscVerifierAdapter` that calls USC verifier precompile and decodes result.
3. Add Foundry tests:
   - valid proof -> `PayoutEvidence`
   - invalid proof -> revert
   - wrong borrower/txid/vout mapping -> revert
4. Add offchain USC worker to produce adapter-compatible `proof`.
5. Deploy adapter and switch manager verifier with `setVerifier`.
6. Run dual-mode smoke tests (SPV mode and USC mode) against same manager interface.
