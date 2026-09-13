import { BRAND } from './brand'
import { STABLECOIN_SYMBOL } from './constants'
import { formatAmount, sameAddress } from './format'
import type { Facility } from '@/hooks/use-facility'

/**
 * Pure reason resolvers. Each returns `null` when the action is allowed, or a
 * single plain sentence explaining why it is not. Order matters: the first
 * matching reason is the one shown, so these read top to bottom.
 */

export type ActionCtx = {
  walletAccount: string
  walletChainId: number | null
  chainId: number
  viewed: string
  paused: boolean | null
}

const DEFAULT_DECIMALS = 6

/** "1,000.00 mUSDT" */
function amount(value: bigint | null, decimals: number): string {
  return `${formatAmount(value, decimals)} ${STABLECOIN_SYMBOL}`
}

const NO_FACILITY_VIEW = 'Connect a wallet, or enter an address, to view a facility.'

export function commonReason(
  c: ActionCtx,
  opts: { requireSameAccount: boolean },
): string | null {
  if (!c.walletAccount) return 'Connect a wallet.'
  if (c.walletChainId !== null && c.walletChainId !== c.chainId) {
    return `Wallet is on chain ${c.walletChainId}. Switch to ${BRAND.network} (${c.chainId}) to transact.`
  }
  if (opts.requireSameAccount && !sameAddress(c.viewed, c.walletAccount)) {
    return 'Viewing another account — connect as it to transact.'
  }
  if (c.paused === true) return 'Facility operations are paused by the protocol.'
  return null
}

export function drawReason(
  f: Facility,
  value: bigint | null,
  raw: string,
  c: ActionCtx,
): string | null {
  const common = commonReason(c, { requireSameAccount: true })
  if (common) return common

  switch (f.state) {
    case 'no-address':
      return NO_FACILITY_VIEW
    case 'not-registered':
      return 'No facility for this address. Complete setup to open one.'
    case 'limit-not-set':
      return 'Registered, but no credit limit has been set on this facility.'
    case 'frozen':
      return 'Facility is frozen. Draws are suspended; repayment remains open.'
    case 'closed':
      return 'Facility is closed.'
    default:
      break
  }

  if (!raw.trim()) return 'Enter an amount.'
  if (value === null || value <= 0n) return 'Enter a valid amount.'
  if (f.undrawnLimit !== null && value > f.undrawnLimit) {
    return `Amount exceeds undrawn limit (${amount(f.undrawnLimit, f.decimals)}).`
  }
  if (f.poolLiquidity !== null && value > f.poolLiquidity) {
    return `Pool liquidity is below the requested amount (${amount(f.poolLiquidity, f.decimals)} in pool).`
  }
  return null
}

export function repayReason(
  f: Facility,
  value: bigint | null,
  raw: string,
  c: ActionCtx,
): string | null {
  const common = commonReason(c, { requireSameAccount: true })
  if (common) return common

  if (f.state === 'no-address') return NO_FACILITY_VIEW
  if (f.state === 'not-registered') return 'No facility for this address.'
  if (f.totalOwed === 0n) return 'Nothing outstanding.'
  if (!raw.trim()) return 'Enter an amount.'
  if (value === null || value <= 0n) return 'Enter a valid amount.'
  if (f.walletBalance !== null && value > f.walletBalance) {
    return `Amount exceeds wallet balance (${amount(f.walletBalance, f.decimals)}).`
  }
  return null
}

export function depositReason(
  ctx: { walletBalance: bigint | null; amount: bigint | null; raw: string; decimals?: number },
  c: ActionCtx,
): string | null {
  const common = commonReason(c, { requireSameAccount: false })
  if (common) return common

  const decimals = ctx.decimals ?? DEFAULT_DECIMALS
  if (!ctx.raw.trim()) return 'Enter an amount.'
  if (ctx.amount === null || ctx.amount <= 0n) return 'Enter a valid amount.'
  if (ctx.walletBalance !== null && ctx.amount > ctx.walletBalance) {
    return `Amount exceeds wallet balance (${amount(ctx.walletBalance, decimals)}).`
  }
  return null
}

export function withdrawReason(
  ctx: {
    position: bigint | null
    /** Cash in the pool. Not a reason on its own — the page explains the shortfall. */
    cash: bigint | null
    amount: bigint | null
    raw: string
    decimals?: number
  },
  c: ActionCtx,
): string | null {
  const common = commonReason(c, { requireSameAccount: false })
  if (common) return common

  const decimals = ctx.decimals ?? DEFAULT_DECIMALS
  if (ctx.position === 0n) return 'No position.'
  if (!ctx.raw.trim()) return 'Enter an amount.'
  if (ctx.amount === null || ctx.amount <= 0n) return 'Enter a valid amount.'
  if (ctx.position !== null && ctx.amount > ctx.position) {
    return `Amount exceeds your position (${amount(ctx.position, decimals)}).`
  }
  return null
}
