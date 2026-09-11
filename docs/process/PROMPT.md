# HashCredit Engineering Prompt (Current)

## Objective

Implement and maintain HashCredit in SPV mode with wallet-first transaction execution.

## Source of Truth

- `docs/specs/PROJECT.md`
- `docs/process/TICKET.md`

## Execution Rules

1. pick the highest-priority open ticket
2. implement code changes with minimal scope
3. add/update tests
4. update impacted docs
5. mark ticket completion with a short note

## Constraints

- keep `HashCreditManager` credit logic independent of verifier internals
- preserve replay protection and borrower mapping integrity
- API remains read/verify-only (no server-side tx signing/submission)
- frontend and worker flows must stay compatible with current contracts

## Quality Gate

- tests for touched behavior pass
- lint/type checks pass where applicable
- docs reflect actual runtime behavior
