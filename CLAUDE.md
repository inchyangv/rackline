# Rackline — GPU lending pivot (Claude Code entry point)

Short entry guide only. The execution ledger is `TICKET.md` (R2); product basis is `PIVOT.md`.
`docs/process/TICKET.md` is the legacy BTC/SPV record and is **not** GPU progress evidence.
Repo policy (`AGENT.md`): English commit subjects; never commit `keys/`, `DEPLOY.md`, `DEMO.md`,
`DORAHACKS.md`, `docs/guides/`.

## Read order per session

1. `AGENT.md`, this file, `TICKET.md` §0 (execution contract) and §0.9 (R2 architecture).
2. The selected ticket, its PIVOT sections, and the **actual** outputs of its prerequisites
   (`docs/gpu/execution/GPU-NNN.md` + real diffs). Never infer completion from a name.
3. `git status --short`; read the current code of every file you will touch.

## R2 decisions (fixed — do not re-litigate in code)

- Loan ledger and execution chain: **Creditcoin**. External source-chain facts are verified only via
  the **official Attestcoin native path** (BlockProver precompile + official SDK/decoder, pinned versions).
- No self-signed EIP-712 oracle, admin approval, BTC SPV, or mock verifier may substitute native
  verification in production. No "lower advance rate" fallback for unsupported sources.
- Wallet auth / covenant consent / underwriting approval signatures are auxiliary paths only.
- Separate, never conflate: official proof → source event validity; GPU revenue provenance; current
  unpaid receivable; E2 payment control; actual destination cash receipt. Only actual destination
  receipt + facility allocation reduces debt (`repayFor`). Proof outage must not block permitted
  direct `repayFor` or recovery.
- Past payouts / our own hash anchors are not new receivables. Old proofs cannot refresh freshness.
- No NFT collateral, future-cash-flow product, or CTC/ATC loan currency without an explicit user decision.
- Do not invent partner endpoints/ABIs/addresses/authority; do not assume Writability is live.

## Where to start (R2)

GPU-000 is done (see `docs/gpu/execution/GPU-000.md`, `BASELINE.md`). Next: **GPU-074** (decision
ledger + gap inventory) and **GPU-075** (official SDK/ABI/manifest + read-only probe), then tickets whose
`선행` are actually satisfied. Status ledger = each ticket's `상태` field in `TICKET.md`.

Current code has **no** Attestcoin/USC implementation (`AttestcoinRevenueVerifier`, `offchain/attestcoin/`,
`config/attestcoin/` do not exist). README/TECH present-tense claims are planned/unverified.

## Verification commands (existing today)

| Alias | Command | Notes |
| --- | --- | --- |
| DIFF | `git diff --check` | |
| SOL(name) | `forge test --match-contract 'name' -vvv` | 0 tests ≠ pass |
| SOL-FULL | `forge build --sizes && forge test --summary && forge fmt --check` | baseline: fmt drift in `contracts/BtcSpvVerifier.sol` |
| PY-API / PY-PROVER / PY-RELAYER | `cd offchain/<api|prover|relayer> && ../../.venv-py313/bin/python -m pytest tests/ -q` | use `.venv-py313` (3.13); `.venv` (3.14) cannot install `coincurve` |
| WEB | `npm ci --prefix apps/web && npm --prefix apps/web run lint && npm --prefix apps/web run build` | web is not in the root workspace |

ASC-CHECK/ASC-TEST/ASC-PROBE/ASC-NATIVE, PY-GPU, WEB-TEST, V2-E2E **do not exist yet** (GPU-075/015/052/057/080).
Root `Makefile` sources `.env` — avoid `make` targets when diagnosing to prevent accidental env load/broadcast.

## Evidence & handover rules

- Evidence levels LOCAL / SANDBOX / NATIVE_TESTNET / LIVE / ACCEPTED are not promoted by local passes.
  HTTP 200, SDK success, Anvil mocks, or skipped tests are never `nativeStatus=VERIFIED`.
- Every ticket writes `docs/gpu/execution/GPU-NNN.md` in the §0.7 format (commands, cwd, exit code,
  test counts, evidence level, unexecuted items, blocking inputs, next READY ticket) and updates its
  `상태` in `TICKET.md`. No secrets/keys/env values in logs or records.
- Preserve the dirty worktree, untracked docs, `keys/`, legacy debt/LP records. One ticket = one commit.
  Never `git push/pull/fetch/rebase/merge/reset --hard/clean -fd/commit --amend/--force`.
- External deploys, testnet broadcasts, fund moves, partner contact, or DEFERRED product changes require
  explicit user approval; otherwise prepare local outputs and record `BLOCKED_EXTERNAL`.
