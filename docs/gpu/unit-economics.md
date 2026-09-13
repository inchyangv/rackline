# Unit economics and stress scenarios — first product (GPU-007, DRAFT v0.1)

Status: DRAFT. All figures are `TEST_ONLY` placeholders produced by `script/gpu/unit_economics.py` from
`test/fixtures/gpu/scenarios/unit-economics-testonly.json` (integer base units, basis points, floor for
income / ceil for costs). They exist to show the shape of the economics and the fail-closed behaviour of
the borrowing base under stress — not to propose commercial terms. Approved inputs are TS-O04…O08 in
`docs/gpu/decisions/REGISTER.md`.

Regenerate: `python script/gpu/unit_economics.py --markdown`.

## 1. Definitions

- **Borrower APR** (`borrowerAprBps`): what the facility charges. **LP funding rate** (`lpCostBps`): what the
  vault owes its depositors *as realized* (no fixed yield; it depends on utilization, losses, cash drag).
  They are different numbers; the spread minus losses and costs is the lender's contribution.
- **Revenue** = interest (actual/365 on drawn principal) + origination fee + servicing fee — only fees
  actually receivable count (PIVOT §11).
- **Costs** = LP funding cost, expected loss (probability × loss-given-default, expressed per annum),
  conversion/bridge cost, fixed underwriting + collection cost per draw, and extra funding days when
  cash arrives after the tenor (`lateFunding`).
- **Contribution** = revenue − costs. **Minimum economic draw** = smallest principal with contribution ≥ 0.
- **DSCR** = expected cash available within the tenor ÷ (principal + interest).
- **Coverage** = eligible receivables ÷ base draw (after haircuts and deductions).

Facility separation is not LP loss isolation: losses in one facility hit the whole vault's NAV unless the
pilot uses a separate vault or a loss-attributed structure (term sheet §8, TS-O11).

## 2. Model output (TEST_ONLY)

### Borrowing base (TEST_ONLY)

| net | eligible | receivable limit | facility limit | room | available draw |
| --- | --- | --- | --- | --- | --- |
| 18,500.00 | 14,800.00 | 7,400.00 | 7,400.00 | 7,400.00 | 6,000.00 |

### Base draw 5,000.00 for 60 days (TEST_ONLY)

| item | amount |
| --- | --- |
| interest | 147.94 |
| origination | 50.00 |
| servicing | 16.43 |
| revenue | 214.38 |
| lpCost | 73.97 |
| expectedLoss | 24.65 |
| conversion | 15.00 |
| fixed | 50.00 |
| lateFunding | 0.00 |
| contribution | 50.75 |
| DSCR | 135.97% |
| implied LP funding rate | 9.00% (≠ borrower APR 18.00%) |

Minimum economic draw size (contribution ≥ 0): **2,481.30**

### Sensitivity by draw size (TEST_ONLY)

| principal | revenue | LP cost | expected loss | fixed | contribution |
| --- | --- | --- | --- | --- | --- |
| 1,000.00 | 42.87 | 14.79 | 4.93 | 50.00 | -29.84 |
| 2,500.00 | 107.19 | 36.98 | 12.32 | 50.00 | 0.37 |
| 5,000.00 | 214.38 | 73.97 | 24.65 | 50.00 | 50.75 |
| 10,000.00 | 428.76 | 147.94 | 49.31 | 50.00 | 151.50 |
| 25,000.00 | 1,071.91 | 369.86 | 123.28 | 50.00 | 453.76 |

### Stress matrix (TEST_ONLY)

| scenario | eligible coverage of base draw | available draw now | blocks new draw | contribution | DSCR |
| --- | --- | --- | --- | --- | --- |
| settlement delayed +45 days | 296.0% | 6,000.00 | no | -4.72 | 135.97% |
| reward token -50% (FX haircut 50%) | 111.0% | 2,775.00 | yes | 50.75 | 135.97% |
| utilization/price -40% (receivables -40%) | 168.0% | 4,200.00 | yes | 50.75 | 81.58% |
| platform deductions doubled | 272.0% | 6,000.00 | no | 50.75 | 135.97% |
| combined: delay + token -50% + receivables -40% + deductions x2 | 54.0% | 1,350.00 | yes | -4.72 | 81.58% |

## 3. Reading the tables

- With these placeholders a draw below ~2,500 units cannot cover the fixed underwriting/collection cost:
  the pilot needs either larger draws or lower fixed cost per draw (automation) — record the approved
  minimum as TS-O04/O06.
- The **combined stress** (settlement delay + token −50% + receivables −40% + deductions ×2) drops eligible
  coverage of the existing draw to ~54% and blocks any new draw; the existing draw is *not* called — it is
  collected from the E2 path, and delinquency/default follow the term sheet timeline. This is the intended
  fail-closed behaviour: stress shrinks new lending first.
- Settlement delay alone keeps coverage but pushes contribution negative through extra funding days;
  late-interest recoverability is deliberately not assumed.
- A 40% utilization/price drop lowers DSCR below the TEST_ONLY 1.25 threshold: the facility would be
  `DRAW_FROZEN` at the next decision refresh even though coverage is still > 100%.

## 4. Cost items that must be measured before approval (not modelled with placeholders)

| Item | Why it matters | Where it lands |
| --- | --- | --- |
| Actual LP funding terms and cash drag | LP yield ≠ borrower APR; idle cash lowers realized yield | TS-O11, GPU-037 |
| Conversion / bridge rail fees and slippage | source token → loan currency | GPU-008, GPU-040 |
| Expected loss from real settlement history | disputes, refunds, platform deductions | GPU-004/005 data |
| Underwriting and collection hours per facility | fixed cost dominates small draws | operations |
| Gas on Creditcoin and source chain for proofs/relays | per event; batch proofs amortize | GPU-079/080 |

## 5. Stress definitions

| Scenario | Mechanism in the model |
| --- | --- |
| Settlement delayed +45 days | `expectedCashDays` +45 → extra LP funding days |
| Reward token −50% | FX haircut 50% on token-denominated receivables |
| Utilization / price −40% | unpaid receivables and expected cash × 0.6 |
| Platform deductions doubled | disputes and platform fees × 2 |
| Combined | all of the above |

Marketing utilization is never an input; the "receivables" input is provider-confirmed unpaid amounts only.
