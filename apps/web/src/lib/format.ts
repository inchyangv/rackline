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
