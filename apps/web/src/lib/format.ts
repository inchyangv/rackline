import { ethers } from 'ethers'

export function shortAddr(addr: string): string {
  if (!addr) return ''
  return `${addr.slice(0, 6)}…${addr.slice(-4)}`
}

export function shortHash(hash: string): string {
  if (!hash) return ''
  return `${hash.slice(0, 10)}…${hash.slice(-4)}`
}

export function shortBtcAddress(addr: string): string {
  if (!addr) return ''
  if (addr.length <= 18) return addr
  return `${addr.slice(0, 8)}…${addr.slice(-6)}`
}

export function isHexBytes(value: string): boolean {
  return /^0x[0-9a-fA-F]*$/.test(value) && value.length % 2 === 0
}

export function sameAddress(a: string, b: string): boolean {
  return !!a && !!b && a.toLowerCase() === b.toLowerCase()
}

type AmountOptions = {
  /** Fraction digits to display. Default 2. */
  fractionDigits?: number
  /** Keep trailing zeros. Default true (money columns should align). */
  padZeros?: boolean
}

/**
 * Format a token amount (bigint, base units) for display with digit grouping.
 * TRUNCATES (floors toward zero) at `fractionDigits` — a ledger must never show
 * more than the holder can actually move. Never throws on odd inputs.
 */
export function formatAmount(
  value: bigint | null | undefined,
  decimals: number,
  { fractionDigits = 2, padZeros = true }: AmountOptions = {},
): string {
  if (value === null || value === undefined) return '—'
  const negative = value < 0n
  const abs = negative ? -value : value
  const fd = Math.max(0, Math.min(fractionDigits, decimals))
  const base = 10n ** BigInt(decimals)
  const whole = abs / base
  const fracFull = (abs % base).toString().padStart(decimals, '0')
  let fracStr = fracFull.slice(0, fd)
  if (!padZeros) fracStr = fracStr.replace(/0+$/, '')
  const wholeStr = whole.toLocaleString('en-US')
  const out = fracStr ? `${wholeStr}.${fracStr}` : wholeStr
  return negative ? `-${out}` : out
}

/** Exact, ungrouped decimal string (for tooltips and inputs). */
export function exactAmount(value: bigint | null | undefined, decimals: number): string {
  if (value === null || value === undefined) return '—'
  const s = ethers.formatUnits(value, decimals)
  // ethers keeps at least one fraction digit ("1000.0"); trim to the exact value.
  return s.includes('.') ? s.replace(/0+$/, '').replace(/\.$/, '') : s
}

/** Basis points → percentage string, e.g. 800n → "8.00%". */
export function formatBps(bps: bigint | null | undefined, fractionDigits = 2): string {
  if (bps === null || bps === undefined) return '—'
  return `${(Number(bps) / 100).toFixed(fractionDigits)}%`
}

/** Parse a user-entered decimal string into base units; returns null when invalid. */
export function parseAmount(input: string, decimals: number): bigint | null {
  const trimmed = input.trim().replace(/,/g, '')
  if (!trimmed || !/^\d*(\.\d*)?$/.test(trimmed)) return null
  try {
    const v = ethers.parseUnits(trimmed === '.' ? '0' : trimmed, decimals)
    return v
  } catch {
    return null
  }
}
