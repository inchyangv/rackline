/**
 * Brand constants. Display-only — contract, env, and API identifiers keep their
 * legacy names (HashCreditManager, VITE_HASH_CREDIT_MANAGER, …).
 */
export const BRAND = {
  name: 'Rackline',
  wordmark: 'RACKLINE',
  descriptor: 'Working capital for GPU operators',
  network: 'Creditcoin Testnet',
  legal:
    'Testnet deployment. Nothing here is an offer of credit or securities. Deposits are not insured. Returns to liquidity providers are not fixed and depend on borrower repayment.',
} as const

export const STORAGE_KEYS = {
  /** Rackline namespace — the legacy 'hashcredit:v2:tab' key is no longer read. */
  tab: 'rackline:tab',
} as const
