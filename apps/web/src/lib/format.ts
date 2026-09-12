export function shortAddr(addr: string): string {
  if (!addr) return ''
  return `${addr.slice(0, 6)}…${addr.slice(-4)}`
}

export function shortBtcAddress(addr: string): string {
  if (!addr) return ''
  if (addr.length <= 18) return addr
  return `${addr.slice(0, 8)}…${addr.slice(-6)}`
}

export function isHexBytes(value: string): boolean {
  return /^0x[0-9a-fA-F]*$/.test(value) && value.length % 2 === 0
}

/**
 * Format a numeric string with thousand separators and limited decimal places.
 * e.g. "1000.000000" → "1,000.00"
 */
export function formatAmount(value: string, decimals = 2): string {
  const num = parseFloat(value)
  if (isNaN(num)) return value
  return num.toLocaleString('en-US', {
    minimumFractionDigits: 0,
    maximumFractionDigits: decimals,
  })
}
