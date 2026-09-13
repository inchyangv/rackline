import { formatAmount } from '@/lib/format'

/** Share prices are shown to six decimal places, so scale by 1e6 and format at 6 dp. */
const PRICE_SCALE = 1_000_000n
const PRICE_DECIMALS = 6

/**
 * Assets per share as a six-decimal string. `null` when it cannot be worked out.
 * An empty pool prices at par, which is what the vault converts at.
 */
export function sharePriceText(assets: bigint | null, shares: bigint | null): string | null {
  if (assets === null || shares === null) return null
  const scaled = shares === 0n ? PRICE_SCALE : (assets * PRICE_SCALE) / shares
  return formatAmount(scaled, PRICE_DECIMALS, { fractionDigits: PRICE_DECIMALS })
}
