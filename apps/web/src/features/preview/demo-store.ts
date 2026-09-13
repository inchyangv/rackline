import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'

/** Isolated, browser-only product preview. These balances are never on-chain funds. */
export const DEMO_STORAGE_KEY = 'rackline:gpu:preview:v1'
export type DemoTransactionKind = 'supply' | 'withdraw' | 'borrow' | 'repay'
export type DemoScenario = 'healthy' | 'proof-pending' | 'control-expired'
export interface DemoActivity {
  id: string
  kind: DemoTransactionKind | 'wallet' | 'scenario' | 'withdrawal'
  title: string
  detail: string
  amount?: number
  createdAt: string
}
export interface DemoWithdrawal {
  id: string
  amount: number
  status: 'pending' | 'claimable'
}
export interface DemoBalances {
  walletBalance: number
  supplied: number
  debt: number
  interest: number
  creditLimit: number
  vaultAssets: number
  /** Available demo liquidity; excludes money reserved for claimable withdrawals. */
  vaultCash: number
  connected: boolean
  scenario: DemoScenario
  activities: DemoActivity[]
  queue: DemoWithdrawal[]
}
export interface DemoResult { ok: boolean; message: string }
export interface DemoQuote extends DemoResult {
  max: number
  queued: boolean
  interestPaid: number
  principalPaid: number
}
export interface DemoStore extends DemoBalances {
  connect: () => void
  disconnect: () => void
  setScenario: (scenario: DemoScenario) => void
  transact: (kind: DemoTransactionKind, amount: number) => DemoResult
  simulateLiquidityStress: () => DemoResult
  reset: () => void
  cancelWithdrawal: (id: string) => DemoResult
  settleWithdrawal: (id: string) => DemoResult
  claimWithdrawal: (id: string) => DemoResult
}

const cents = (value: number) => Math.round(value * 100)
const money = (value: number) => Math.round(value) / 100
const validMoney = (value: unknown): value is number => typeof value === 'number'
  && Number.isFinite(value) && value >= 0 && value <= 1_000_000_000_000
  && Math.abs(value * 100 - Math.round(value * 100)) < 0.0001
const scenarios: DemoScenario[] = ['healthy', 'proof-pending', 'control-expired']
const transactionKinds: DemoTransactionKind[] = ['supply', 'withdraw', 'borrow', 'repay']
let sequence = 0
const nextId = () => `preview-${Date.now().toString(36)}-${(++sequence).toString(36)}-${Math.random().toString(36).slice(2, 8)}`

function activity(kind: DemoActivity['kind'], title: string, detail: string, amount?: number): DemoActivity {
  return { id: nextId(), kind, title, detail, ...(amount === undefined ? {} : { amount }), createdAt: new Date().toISOString() }
}

function initialState(): DemoBalances {
  return {
    walletBalance: 85_000,
    supplied: 12_500,
    debt: 42_000,
    interest: 126,
    creditLimit: 98_000,
    vaultAssets: 2_480_000,
    vaultCash: 782_000,
    connected: false,
    scenario: 'healthy',
    activities: [activity('scenario', 'Your preview is ready', 'Illustrative balances only. No wallet, funds, or network connection.')],
    queue: [],
  }
}

export function getDemoMaxAmount(state: DemoBalances, kind: DemoTransactionKind): number {
  if (kind === 'supply') return state.walletBalance
  if (kind === 'withdraw') return state.supplied
  if (kind === 'repay') return money(Math.min(cents(state.walletBalance), cents(state.debt) + cents(state.interest)))
  if (kind === 'borrow') {
    if (state.scenario !== 'healthy') return 0
    return money(Math.max(0, Math.min(cents(state.creditLimit) - cents(state.debt) - cents(state.interest), cents(state.vaultCash))))
  }
  return 0
}

/** Pure quote: review and execution share the same cent-based checks. */
export function getDemoQuote(state: DemoBalances, kind: DemoTransactionKind, amount: number): DemoQuote {
  const quote: DemoQuote = { ok: false, message: '', max: getDemoMaxAmount(state, kind), queued: false, interestPaid: 0, principalPaid: 0 }
  const fail = (message: string) => ({ ...quote, message })
  if (!transactionKinds.includes(kind)) return fail('Choose a supported demo transaction.')
  if (!state.connected) return fail('Connect the demo wallet to continue. No real wallet is required.')
  if (!validMoney(amount) || cents(amount) < 1) return fail('Enter at least 0.01 USDC, with no more than two decimal places.')
  if (kind === 'borrow' && state.scenario === 'proof-pending') return fail('New borrowing is paused while the simulated source proof is pending. Repayment remains available.')
  if (kind === 'borrow' && state.scenario === 'control-expired') return fail('New borrowing is paused because simulated payment control has expired. Repayment remains available.')
  const value = cents(amount)
  if ((kind === 'supply' || kind === 'repay') && value > cents(state.walletBalance)) return fail('The demo wallet has insufficient USDC.')
  if (kind === 'withdraw' && value > cents(state.supplied)) return fail('This exceeds your available supplied balance. Queued withdrawals are already reserved.')
  if (kind === 'borrow') {
    if (value > Math.max(0, cents(state.creditLimit) - cents(state.debt) - cents(state.interest))) return fail('This exceeds your available credit, including accrued interest.')
    if (value > cents(state.vaultCash)) return fail('The demo vault does not have enough available liquidity for this borrow.')
  }
  if (kind === 'repay' && value > cents(state.debt) + cents(state.interest)) return fail('This exceeds your outstanding principal and interest. Use MAX to repay exactly.')
  if (kind === 'withdraw') quote.queued = value > cents(state.vaultCash) || state.queue.some((entry) => entry.status === 'pending')
  if (kind === 'repay') {
    quote.interestPaid = money(Math.min(value, cents(state.interest)))
    quote.principalPaid = money(value - cents(quote.interestPaid))
  }
  return { ...quote, ok: true, message: quote.queued ? 'Your withdrawal will join the demo queue. Existing requests have priority.' : 'Ready to simulate. No funds will move on-chain.' }
}

function restoreSnapshot(value: unknown): DemoBalances | null {
  if (!value || typeof value !== 'object') return null
  const candidate = value as Partial<DemoBalances>
  const fields = ['walletBalance', 'supplied', 'debt', 'interest', 'creditLimit', 'vaultAssets', 'vaultCash'] as const
  if (fields.some((field) => !validMoney(candidate[field])) || typeof candidate.connected !== 'boolean'
    || !scenarios.includes(candidate.scenario as DemoScenario) || !Array.isArray(candidate.queue) || !Array.isArray(candidate.activities)) return null
  const ids = new Set<string>()
  if (candidate.queue.length > 100 || candidate.queue.some((entry) => {
    if (!entry || typeof entry.id !== 'string' || ids.has(entry.id) || !validMoney(entry.amount) || entry.amount < 0.01
      || (entry.status !== 'pending' && entry.status !== 'claimable')) return true
    ids.add(entry.id)
    return false
  })) return null
  const activities = candidate.activities.filter((entry) => entry && typeof entry.id === 'string'
    && typeof entry.title === 'string' && typeof entry.detail === 'string' && typeof entry.kind === 'string'
    && typeof entry.createdAt === 'string' && Number.isFinite(Date.parse(entry.createdAt))
    && (entry.amount === undefined || validMoney(entry.amount))).slice(0, 80)
  // Explicit field selection prevents persisted JSON from replacing store actions.
  return {
    walletBalance: candidate.walletBalance!, supplied: candidate.supplied!, debt: candidate.debt!,
    interest: candidate.interest!, creditLimit: candidate.creditLimit!, vaultAssets: candidate.vaultAssets!,
    vaultCash: candidate.vaultCash!, connected: candidate.connected, scenario: candidate.scenario!,
    queue: candidate.queue.map(({ id, amount, status }) => ({ id, amount, status })), activities,
  }
}

export const useDemoStore = create<DemoStore>()(persist((set, get) => ({
  ...initialState(),
  connect: () => {
    if (get().connected) return
    set((state) => ({ connected: true, activities: [activity('wallet', 'Demo wallet connected', 'Local preview account. No extension or signature was requested.'), ...state.activities].slice(0, 80) }))
  },
  disconnect: () => set({ connected: false }),
  setScenario: (scenario) => {
    if (!scenarios.includes(scenario) || scenario === get().scenario) return
    const detail = scenario === 'healthy' ? 'Simulated checks restored. New borrowing is available.'
      : scenario === 'proof-pending' ? 'Simulated proof pending. New borrowing paused; debt unchanged.'
        : 'Simulated payment control expired. New borrowing paused; debt unchanged.'
    set((state) => ({ scenario, activities: [activity('scenario', 'Preview scenario changed', detail), ...state.activities].slice(0, 80) }))
  },
  transact: (kind, amount) => {
    const state = get()
    const quote = getDemoQuote(state, kind, amount)
    if (!quote.ok) return { ok: false, message: quote.message }
    const value = cents(amount)
    let patch: Partial<DemoBalances>
    let title: string
    let detail: string
    if (kind === 'supply') {
      patch = { walletBalance: money(cents(state.walletBalance) - value), supplied: money(cents(state.supplied) + value), vaultAssets: money(cents(state.vaultAssets) + value), vaultCash: money(cents(state.vaultCash) + value) }
      title = 'Supply complete'
      detail = 'Demo USDC added to your supplied balance. No on-chain transaction.'
    } else if (kind === 'withdraw') {
      patch = { supplied: money(cents(state.supplied) - value) }
      if (quote.queued) {
        if (state.queue.length >= 100) return { ok: false, message: 'Resolve an existing demo withdrawal before adding another.' }
        patch.queue = [...state.queue, { id: nextId(), amount: money(value), status: 'pending' }]
        title = 'Withdrawal queued'
        detail = 'Amount reserved from your supplied balance. Claim after demo liquidity is allocated, or cancel to restore it.'
      } else {
        patch.walletBalance = money(cents(state.walletBalance) + value)
        patch.vaultAssets = money(cents(state.vaultAssets) - value)
        patch.vaultCash = money(cents(state.vaultCash) - value)
        title = 'Withdrawal complete'
        detail = 'Demo USDC returned to your preview wallet. No on-chain transaction.'
      }
    } else if (kind === 'borrow') {
      patch = { walletBalance: money(cents(state.walletBalance) + value), debt: money(cents(state.debt) + value), vaultCash: money(cents(state.vaultCash) - value) }
      title = 'Borrow complete'
      detail = 'Demo principal increased and available credit decreased. Vault NAV is unchanged.'
    } else {
      patch = { walletBalance: money(cents(state.walletBalance) - value), interest: money(cents(state.interest) - cents(quote.interestPaid)), debt: money(cents(state.debt) - cents(quote.principalPaid)), vaultCash: money(cents(state.vaultCash) + value) }
      title = 'Repayment complete'
      detail = `Demo repayment: ${quote.interestPaid.toFixed(2)} USDC interest and ${quote.principalPaid.toFixed(2)} USDC principal. No proof changed your debt.`
    }
    set({ ...patch, activities: [activity(kind, title, detail, money(value)), ...state.activities].slice(0, 80) })
    return { ok: true, message: title }
  },
  simulateLiquidityStress: () => {
    const state = get()
    if (state.queue.length > 0) return { ok: false, message: 'Resolve existing withdrawals before changing the demo liquidity fixture.' }
    if (state.vaultCash <= 5_000) return { ok: false, message: 'The demo already has limited liquidity. Supply or repay demo USDC to replenish it.' }
    const reallocated = money(cents(state.vaultCash) - 500_000)
    set({ vaultCash: 5_000, activities: [activity('scenario', 'Limited liquidity preview enabled', 'Synthetic reallocation of vault cash into other sample borrower loans. Vault NAV, your wallet, and your debt are unchanged. No funds were transferred.', reallocated), ...state.activities].slice(0, 80) })
    return { ok: true, message: 'Available demo liquidity is now 5,000 USDC. Withdraw more to preview the queue; supply or repay to replenish cash.' }
  },
  cancelWithdrawal: (id) => {
    const state = get()
    if (!state.connected) return { ok: false, message: 'Connect the demo wallet first.' }
    const entry = state.queue.find((item) => item.id === id)
    if (!entry || entry.status !== 'pending') return { ok: false, message: 'Only an existing pending withdrawal can be cancelled.' }
    set({ supplied: money(cents(state.supplied) + cents(entry.amount)), queue: state.queue.filter((item) => item.id !== id), activities: [activity('withdrawal', 'Withdrawal cancelled', 'Reserved demo USDC restored to your supplied balance.', entry.amount), ...state.activities].slice(0, 80) })
    return { ok: true, message: 'Withdrawal cancelled. Supplied balance restored.' }
  },
  settleWithdrawal: (id) => {
    const state = get()
    if (!state.connected) return { ok: false, message: 'Connect the demo wallet first.' }
    const entry = state.queue.find((item) => item.id === id)
    if (!entry || entry.status !== 'pending') return { ok: false, message: 'This withdrawal is not pending.' }
    if (state.queue.find((item) => item.status === 'pending')?.id !== id) return { ok: false, message: 'Allocate the earlier queued withdrawal first.' }
    if (cents(entry.amount) > cents(state.vaultCash)) return { ok: false, message: 'Not enough demo liquidity yet. A simulated supply or repayment can replenish it.' }
    set({ vaultCash: money(cents(state.vaultCash) - cents(entry.amount)), vaultAssets: money(cents(state.vaultAssets) - cents(entry.amount)), queue: state.queue.map((item) => item.id === id ? { ...item, status: 'claimable' as const } : item), activities: [activity('withdrawal', 'Withdrawal ready to claim', 'Demo liquidity reserved for this claim; no wallet funds have moved.', entry.amount), ...state.activities].slice(0, 80) })
    return { ok: true, message: 'Demo liquidity allocated. Your withdrawal is ready to claim.' }
  },
  claimWithdrawal: (id) => {
    const state = get()
    if (!state.connected) return { ok: false, message: 'Connect the demo wallet first.' }
    const entry = state.queue.find((item) => item.id === id)
    if (!entry || entry.status !== 'claimable') return { ok: false, message: 'This withdrawal is not ready or has already been claimed.' }
    set({ walletBalance: money(cents(state.walletBalance) + cents(entry.amount)), queue: state.queue.filter((item) => item.id !== id), activities: [activity('withdrawal', 'Withdrawal claimed', 'Reserved demo USDC credited once to your preview wallet.', entry.amount), ...state.activities].slice(0, 80) })
    return { ok: true, message: 'Demo withdrawal claimed.' }
  },
  reset: () => set(initialState()),
}), {
  name: DEMO_STORAGE_KEY,
  version: 1,
  storage: createJSONStorage(() => ({
    getItem: (name) => { try { return localStorage.getItem(name) } catch { return null } },
    setItem: (name, value) => { try { localStorage.setItem(name, value) } catch { /* Restricted storage: keep this preview in memory. */ } },
    removeItem: (name) => { try { localStorage.removeItem(name) } catch { /* Nothing to remove when browser storage is unavailable. */ } },
  })),
  partialize: ({ walletBalance, supplied, debt, interest, creditLimit, vaultAssets, vaultCash, connected, scenario, activities, queue }) => ({ walletBalance, supplied, debt, interest, creditLimit, vaultAssets, vaultCash, connected, scenario, activities, queue }),
  merge: (persisted, current) => ({ ...current, ...(restoreSnapshot(persisted) ?? initialState()) }),
}))
