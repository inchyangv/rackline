# GPU pivot baseline — reproducible environment and suite results

Recorded by GPU-000 on 2026-09-13T21:51Z (UTC) at commit `fbc5549` (`main`), dirty range: three untracked
hackathon docs (`docs/hackathon/CEIP_EMAIL.md`, `FOLLOWUP_EMAIL.md`, `MAIL.md`) preserved untouched.
Nothing here is evidence of Attestcoin native verification, partner integration, or deployment; it is the
local starting line for R2 work.

## 1. Toolchain (host: macOS Darwin 24.6.0, arm64)

| Tool | Version | Source |
| --- | --- | --- |
| forge / cast / anvil | 1.4.2-stable (commit `828441d`, built 2025-10-18) | `forge --version` |
| solc (via foundry.toml) | 0.8.24, evm `london`, optimizer 200 runs | `foundry.toml` |
| forge-std | v1.14.0 (`1801b05`) | `foundry.lock`, `git submodule status` |
| node / npm | v22.22.2 / 10.9.7 | `node --version`, `npm --version` |
| Python (project env) | 3.13.7 in `.venv-py313/` (Homebrew `python@3.13`) | created by GPU-000 |
| Python (pre-existing) | 3.14.3 in `.venv/` — **cannot install `coincurve`** (no cp314 wheel; sdist build fails: "Expected exactly one LICENSE file in cffi distribution") | preserved, not modified |
| git | 2.39.5 (Apple Git-154) | |
| slither | not installed locally (CI job uses `crytic/slither-action`, `continue-on-error: true`) | |

CI (`.github/workflows/test.yml`) uses `FOUNDRY_PROFILE=ci`, but `foundry.toml` defines no `[profile.ci]`,
so the default profile applies. CI Python is 3.11; local verified env is 3.13 (both satisfy `>=3.11`).

## 2. Environment setup (reproducible)

```bash
# Solidity
git submodule update --init --recursive
forge build

# Python — one venv for all three offchain packages (relayer, prover, api) with dev extras
/opt/homebrew/bin/python3.13 -m venv .venv-py313
.venv-py313/bin/python -m pip install --upgrade pip
.venv-py313/bin/python -m pip install -e "offchain/relayer[dev]" -e "offchain/prover[dev]" -e "offchain/api[dev]"

# Web — lockfile install (apps/web is NOT in the root npm workspace; root workspaces are offchain/api, offchain/prover)
npm ci --prefix apps/web
```

- The venv self-ignores in git (Python ≥3.13 `venv` writes `.gitignore` with `*`). `.venv/` is also ignored.
- Resolved dependency snapshot: `docs/gpu/execution/baseline/pip-freeze-py313.txt` (81 packages). Key pins:
  `coincurve==21.0.0`, `web3==8.0.0`, `eth-account==0.14.0`, `fastapi==0.141.1`, `starlette==1.6.0`,
  `SQLAlchemy==2.0.52`, `pydantic==2.13.5`, `pytest==9.1.1`, `httpx==0.28.1`. `pyproject.toml` files use
  lower bounds only; the freeze file is the pinnable reference until a lock format is adopted (GPU-015).
- No root `.env` exists locally. Root `Makefile` `include`s `.env` when present — do not run `make` targets
  during diagnostics if a `.env` with RPC/keys exists. No env values or keys were read or logged.
- `offchain/api/.venv313/` pre-exists (user-created, Python 3.13.7); left untouched and not used here.

## 3. Suite results (actually executed, 2026-09-13 UTC)

| Alias | cwd · command | Exit | Result |
| --- | --- | --- | --- |
| DIFF | root · `git diff --check` | 0 | clean |
| SOL-FULL 1/3 | root · `forge build --sizes` | 0 | compiled; 40 `forge-lint` warnings (unsafe-typecast etc., non-fatal); all contracts under 24,576 B runtime (largest `HashCreditManager` 11,611 B) |
| SOL-FULL 2/3 | root · `forge test --summary` | 0 | **192 passed, 0 failed, 0 skipped** across 12 suites (see table below) |
| SOL-FULL 3/3 | root · `forge fmt --check` | **1** | **FAIL — 1 file drifts**: `contracts/BtcSpvVerifier.sol` (`claimBtcAddress` signature wrapping). Legacy contract; not reformatted in GPU-000 (no unrelated cleanup). CI `forge fmt --check` step would fail under forge 1.4.2 → owner GPU-054 (CI) / GPU-060 (legacy preservation) |
| PY-API | `offchain/api` · `../../.venv-py313/bin/python -m pytest tests/ -q` | 0 | **15 passed**, 2 deprecation warnings (starlette/httpx testclient, anyio alias) |
| PY-PROVER | `offchain/prover` · same | 0 | **61 passed** |
| PY-RELAYER | `offchain/relayer` · same | 0 | **9 passed**, 1 warning (Pydantic class-based `config` deprecated in `hashcredit_relayer/config.py:13`) |
| PY-API (old `.venv`, 3.14) | `offchain/api` · `../../.venv/bin/python -m pytest tests/ -q --co` | 2 | collection error on `tests/test_api.py` (`coincurve` missing) — reproduces the PIVOT §12.1 baseline; superseded by `.venv-py313` |
| WEB install | root · `npm ci --prefix apps/web` | 0 | 565 packages added; `npm audit`: 25 vulnerabilities (3 low, 5 moderate, 17 high) — not triaged here |
| WEB lint | root · `npm --prefix apps/web run lint` | 0 | clean |
| WEB build | root · `npm --prefix apps/web run build` | 0 | `tsc -b && vite build` OK; warning: main chunk 652 kB (>500 kB) |

Forge suites (`forge test --summary`):

| Suite | Tests |
| --- | --- |
| `test/BtcSpvVerifier.t.sol:BitcoinLibTest` | 14 |
| `test/BtcSpvVerifier.t.sol:BtcSpvVerifierTest` | 22 |
| `test/CheckpointManager.t.sol:CheckpointManagerTest` | 22 |
| `test/GasProfile.t.sol:GasProfileTest` | 23 |
| `test/HashCredit.t.sol:HashCreditTest` | 1 |
| `test/HashCreditManager.t.sol:HashCreditManagerTest` | 46 |
| `test/LendingVault.t.sol:LendingVaultTest` | 26 |
| `test/RelayerSigVerifier.t.sol:RelayerSigVerifierTest` | 15 |
| `test/SafeERC20.t.sol:SafeERC20Test` | 9 |
| `test/SpvE2E.t.sol:SpvE2ETest` | 8 |
| `test/invariant/Invariant.t.sol:ManagerInvariantTest` | 3 |
| `test/invariant/Invariant.t.sol:VaultInvariantTest` | 3 |

Invariant suites ran with foundry defaults (no `[invariant]` section in `foundry.toml`) and took ~304 s
wall-clock locally; CI caps them via `FOUNDRY_INVARIANT_RUNS=50 FOUNDRY_INVARIANT_DEPTH=50`. The
`ManagerInvariantTest` handler only submits payouts (no borrow/repay/time) — see PIVOT §12.1; test passes
are **not** accounting-correctness evidence (`test_repay_interestFirst` expects the wrong interest, PIVOT §2.2;
owner GPU-002).

Commands that **do not exist yet** and were not run: PY-GPU (GPU-015), WEB-TEST / WEB-E2E (GPU-052),
V2-E2E (GPU-057), ASC-CHECK / ASC-TEST / ASC-PROBE (GPU-075), ASC-NATIVE (GPU-080).

## 4. R2 code inventory — what the repository actually implements

Searched `*.sol *.py *.ts *.tsx *.json *.toml *.sh *.yml` (excluding `node_modules`, `lib/`, `out/`,
`cache/`, venvs, `dist/`) for `attestcoin|usc-sdk|BlockProver|0x…0fd2|gluwa`: **0 code files**. Matches
exist only in docs (`README.md`, `TECH.md`, `docs/specs/USC_ADAPTER.md`, `docs/hackathon/*`, `docs/adr/0001-btc-spv.md`).

| Area | Actual code (exists, tested) | Official Attestcoin native path | Status |
| --- | --- | --- | --- |
| Proof builder | `offchain/prover/hashcredit_prover/proof_builder.py` — Bitcoin SPV Merkle proofs for `BtcSpvVerifier` | `offchain/attestcoin/` (official `@gluwa/usc-sdk` client) | **NOT IMPLEMENTED** — GPU-075/079 |
| On-chain verifier | `contracts/BtcSpvVerifier.sol` + `CheckpointManager.sol` (BTC SPV); `contracts/RelayerSigVerifier.sol` (EIP-712 relayer attestation); `contracts/mocks/MockVerifier.sol` | `contracts/gpu/AttestcoinRevenueVerifier.sol` over BlockProver precompile | **NOT IMPLEMENTED** — GPU-078 |
| Source event contracts | none (BTC payouts are read from Bitcoin RPC) | `contracts/gpu/source/` | **NOT IMPLEMENTED** — GPU-077 |
| Environment manifest / fixtures | none (`config/`, `test/fixtures/gpu/` absent) | `config/attestcoin/`, `test/fixtures/gpu/attestcoin/` | **NOT IMPLEMENTED** — GPU-075/082 |
| Credit ledger | `contracts/HashCreditManager.sol`, `LendingVault.sol`, `RiskConfig.sol`, `PoolRegistry.sol` (BTC-denominated v1, known accounting defects PIVOT §2.2) | v2 GPU contracts under `contracts/gpu/` | **NOT IMPLEMENTED** — GPU-029~043 |
| Offchain API/worker | `offchain/api/hashcredit_api/` (FastAPI, BTC claim/proof, public `/claim/register-and-grant` with owner key — PIVOT P0), `offchain/relayer/`, `offchain/prover/` (BTC watcher) | GPU worker/API packages | **NOT IMPLEMENTED** — GPU-015~028, GPU-079 |
| Web | `apps/web` (React/Vite; rebranded Rackline UI, v1 BTC flows) | GPU borrower/LP/ops UI | **NOT IMPLEMENTED** — GPU-047~052 |

README.md / TECH.md present-tense statements such as "`AttestcoinRevenueVerifier` verifies it via the
BlockProver precompile", "run as real contracts on Creditcoin CC3 testnet", and TECH §3's "chains not yet
supported fall back to the attested adapter with a lower advance rate" are **planned/unverified** and, in the
fallback case, **contradict R2** (§0.9). They are not completion evidence. Reconciliation is GPU-074's job;
this file only records the discrepancy. External deployments listed in `docs/hackathon/*` or `broadcast/`
(gitignored, v1 `Deploy.s.sol`/`DeploySpv.s.sol` artifacts present locally) were not verified against any
chain in GPU-000 — their absence is not asserted either.

## 5. Known baseline failures / differences (not fixed in GPU-000)

1. `forge fmt --check` fails on `contracts/BtcSpvVerifier.sol` under forge 1.4.2 (formatter drift).
2. `.venv` (Python 3.14) cannot host the API test suite (`coincurve` wheel missing) — use `.venv-py313`.
3. `test/HashCreditManager.t.sol` `test_repay_interestFirst` encodes the interest-loss defect as expected
   behaviour (PIVOT §2.2). Passing ≠ correct; GPU-002 will pin correct expectations separately.
4. Web bundle >500 kB and 25 npm audit findings — informational, untriaged.
5. Invariant suite wall time ~5 min with defaults; use CI's run/depth caps for quick local iteration.
