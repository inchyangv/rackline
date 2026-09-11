import { ethers } from 'ethers'
import type { DemoWallet, BorrowerBtcMap, DemoBtcPayoutRecord } from '@/types'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

export function parseDemoWallets(raw: string): DemoWallet[] {
  try {
    const v = JSON.parse(raw) as unknown
    if (!Array.isArray(v)) return []
    return v
      .filter((x) => isRecord(x))
      .map((x) => ({
        name: typeof x.name === 'string' ? x.name : 'Demo Wallet',
        address: typeof x.address === 'string' ? x.address : '',
        privateKey: typeof x.privateKey === 'string' ? x.privateKey : '',
        createdAt: typeof x.createdAt === 'number' ? x.createdAt : Date.now(),
      }))
      .filter((w) => ethers.isAddress(w.address) && /^0x[0-9a-fA-F]{64}$/.test(w.privateKey))
  } catch {
    return []
  }
}

export function parseBorrowerBtcMap(raw: string): BorrowerBtcMap {
  try {
    const v = JSON.parse(raw) as unknown
    if (!isRecord(v)) return {}
    const out: BorrowerBtcMap = {}
    for (const [k, val] of Object.entries(v)) {
      if (!ethers.isAddress(k)) continue
      if (typeof val !== 'string') continue
      const btc = val.trim()
      if (!btc) continue
      out[k.toLowerCase()] = btc
    }
    return out
  } catch {
    return {}
  }
}

export function parseDemoBtcPayoutHistory(raw: string): DemoBtcPayoutRecord[] {
  try {
    const v = JSON.parse(raw) as unknown
    if (!Array.isArray(v)) return []
    return v
      .filter((x) => isRecord(x))
      .map((x) => {
        const source: DemoBtcPayoutRecord['source'] = x.source === 'build+submit' ? 'build+submit' : 'build'
        return {
          id: typeof x.id === 'string' ? x.id : '',
          createdAt: typeof x.createdAt === 'number' ? x.createdAt : Date.now(),
          borrower: typeof x.borrower === 'string' ? x.borrower : '',
          btcAddress: typeof x.btcAddress === 'string' ? x.btcAddress : '',
          txid: typeof x.txid === 'string' ? x.txid : '',
          vout: typeof x.vout === 'number' ? x.vout : 0,
          amountSats: typeof x.amountSats === 'number' ? x.amountSats : null,
          checkpointHeight: typeof x.checkpointHeight === 'number' ? x.checkpointHeight : 0,
          targetHeight: typeof x.targetHeight === 'number' ? x.targetHeight : 0,
          source,
          submitTxHash: typeof x.submitTxHash === 'string' ? x.submitTxHash : null,
        }
      })
      .filter((x) => x.id && ethers.isAddress(x.borrower) && x.txid)
      .slice(0, 200)
  } catch {
    return []
  }
}
