import { env } from './env'

export function normalizeBaseUrl(url: string): string {
  return url.trim().replace(/\/+$/, '')
}

export function getBtcTxExplorerUrl(txid: string): string {
  const txidHex = txid.replace(/^0x/, '').trim()
  if (!/^[0-9a-fA-F]{64}$/.test(txidHex)) return ''
  const base = normalizeBaseUrl(env.btcExplorerTxBase || 'https://mempool.space/testnet/tx')
  return `${base}/${txidHex}`
}

const EVM_EXPLORER_BASE = 'https://testnet-explorer.hsk.xyz'

export function getEvmTxExplorerUrl(hash: string): string {
  if (!hash || !/^0x[0-9a-fA-F]{64}$/.test(hash)) return ''
  return `${EVM_EXPLORER_BASE}/tx/${hash}`
}
