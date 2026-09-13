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

Ledger with IDs (R2-D01…D14 fixed, R2-O01…O09 open): `docs/gpu/decisions/attestcoin-first.md`.
Doc-vs-code inventory and conflict register: `docs/gpu/execution/ATTESTCOIN_GAP.md`. Cite decision IDs in records.

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

Done (18): GPU-000/074/075/001/002/003/011/013/015/007/012/076/014/029/030/078 + records in
`docs/gpu/execution/GPU-NNN.md`. READY next: GPU-077 (source module), GPU-031 (EvidenceBook), GPU-032, GPU-033,
GPU-016, GPU-017/018, GPU-008, GPU-060; DD tickets 004/005/006 need partner input. Toolchain: solc 0.8.28 / evm london; OpenZeppelin 5.5 is
Cancun-only (mcopy) and is NOT used by `contracts/gpu` — official Attestcoin files are vendored under
`contracts/gpu/vendor/attestcoin/` (hash-pinned). Follow each ticket's `선행`. v1 accounting defects are
pinned in `test/diagnostic/AccountingRegressions.t.sol` (`RUN_RED_DIAGNOSTICS=true` = v2 acceptance).
API profile rule: production API holds no key (`API_PROFILE=production` default); demo grants only under
`testnet_demo` with `DEMO_*` vars. Status ledger = each ticket's `상태` field in `TICKET.md`.

`contracts/gpu/` now has types, 13 interfaces, roles/registries/authorization verifier, a TEST_ONLY
`MockBlockProver` and the native adapter `AttestcoinRevenueVerifier` (GPU-078, LOCAL_MOCK-tested only); EvidenceBook
(GPU-031), source module (GPU-077), ledger/vault/manager and the proof worker (GPU-079) are still unimplemented.
No native proof has been submitted (G-ASC = GPU-080). Synthetic wire fixtures are regenerated with
`npm --prefix offchain/attestcoin run gen-wire -- --check`.

## Verification commands (existing today)

| Alias | Command | Notes |
| --- | --- | --- |
| DIFF | `git diff --check` | |
| SOL(name) | `forge test --match-contract 'name' -vvv` | 0 tests ≠ pass |
| SOL-FULL | `forge build --sizes && forge test --summary && forge fmt --check` | baseline: fmt drift in `contracts/BtcSpvVerifier.sol` |
| PY-API / PY-PROVER / PY-RELAYER | `cd offchain/<api|prover|relayer> && ../../.venv-py313/bin/python -m pytest tests/ -q` | use `.venv-py313` (3.13); `.venv` (3.14) cannot install `coincurve` |
| WEB | `npm ci --prefix apps/web && npm --prefix apps/web run lint && npm --prefix apps/web run build` | web is not in the root workspace |
| PY-GPU | `python -m pytest offchain/gpu/tests -q` | real PostgreSQL (env `HASHCREDIT_GPU_TEST_DATABASE_URL` or local initdb); fails, never skips, without PG |
| ASC-CHECK | `npm --prefix offchain/attestcoin run check` | pins/ABI/manifests; no network |
| ASC-TEST | `npm --prefix offchain/attestcoin run test -- --run` | offline, fake transport |
| ASC-PROBE | `npm --prefix offchain/attestcoin run probe -- --manifest config/attestcoin/<m>.json --out <report>` | read-only RPC/HTTP only; refuses mock manifests |

ASC-NATIVE, WEB-TEST, V2-E2E **do not exist yet** (GPU-080/052/057). Install order: `pip install -e offchain/gpu[dev]` before api/prover. Official artifact facts: `docs/gpu/attestcoin/environment.md`.
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
