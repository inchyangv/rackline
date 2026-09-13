/**
 * Brand constants. Display-only — contract, env, and API identifiers keep their
 * legacy names (HashCreditManager, VITE_HASH_CREDIT_MANAGER, …).
 */
export const BRAND = {
  name: 'HashCredit',
  wordmark: 'HASHCREDIT',
  descriptor: 'Working capital for GPU operators',
  network: 'Creditcoin Testnet',
  legal:
    'Testnet deployment. Nothing here is an offer of credit or securities. Deposits are not insured. Returns to liquidity providers are not fixed and depend on borrower repayment.',
} as const

export const STORAGE_KEYS = {
  /** v2 namespace — the legacy 'hashcredit_tab' key held 'dashboard' | 'pool'. */
  tab: 'hashcredit:v2:tab',
} as const
