import { useEffect, useState } from 'react'
import { ethers } from 'ethers'
import { env } from '@/lib/env'
import { normalizeBaseUrl } from '@/lib/explorer'
import { useConfigStore } from '@/stores/config-store'
import { useWalletStore } from '@/stores/wallet-store'

export type StatementEntry = {
  block: number
  txHash: string
  kind: 'draw' | 'repay'
  /** Amount drawn or repaid, in token base units. */
  amount: bigint
  /** Principal outstanding after the entry (event `newDebt`). */
  balance: bigint
  /** Unix seconds, or null when the explorer omits it. */
  timestamp: number | null
  logIndex: number
}

/** First block of the current deployment — nothing to read before it. */
const DEPLOY_BLOCK = 4390740

const TOPICS = {
  draw: ethers.id('Borrowed(address,uint256,uint128)'),
  repay: ethers.id('Repaid(address,uint256,uint128)'),
} as const

const STATEMENT_ERROR = 'Statement unavailable (explorer API).'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function hexToNumber(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value !== 'string' || !value) return null
  const n = /^0x/i.test(value) ? Number.parseInt(value, 16) : Number(value)
  return Number.isFinite(n) ? n : null
}

function decodeEntry(kind: 'draw' | 'repay', log: unknown): StatementEntry | null {
  if (!isRecord(log)) return null
  const block = hexToNumber(log.blockNumber)
  const txHash = typeof log.transactionHash === 'string' ? log.transactionHash : ''
  const data = typeof log.data === 'string' ? log.data : ''
  if (block === null || !txHash || !/^0x[0-9a-fA-F]{128}$/.test(data)) return null
  try {
    const [amount, balance] = ethers.AbiCoder.defaultAbiCoder().decode(
      ['uint256', 'uint128'],
      data,
    ) as unknown as [bigint, bigint]
    return {
      block,
      txHash,
      kind,
      amount,
      balance,
      timestamp: hexToNumber(log.timeStamp),
      logIndex: hexToNumber(log.logIndex) ?? 0,
    }
  } catch {
    return null
  }
}

async function fetchEntries(
  kind: 'draw' | 'repay',
  manager: string,
  borrower: string,
  signal: AbortSignal,
): Promise<StatementEntry[]> {
  const params = new URLSearchParams({
    module: 'logs',
    action: 'getLogs',
    fromBlock: String(DEPLOY_BLOCK),
    toBlock: 'latest',
    address: manager,
    topic0: TOPICS[kind],
    topic1: ethers.zeroPadValue(borrower.toLowerCase(), 32),
    topic0_1_opr: 'and',
  })

  const res = await fetch(`${normalizeBaseUrl(env.explorerApiBase)}?${params.toString()}`, {
    signal,
    headers: { accept: 'application/json' },
  })
  if (!res.ok) throw new Error(`explorer responded ${res.status}`)

  const json: unknown = await res.json()
  if (!isRecord(json)) throw new Error('explorer response was not an object')

  if (json.status !== '1') {
    const message = typeof json.message === 'string' ? json.message : ''
    // An address with no history is a valid, empty statement.
    if (/no (logs|records) found/i.test(message)) return []
    throw new Error(message || 'explorer returned no status')
  }

  const result = Array.isArray(json.result) ? json.result : []
  return result
    .map((log) => decodeEntry(kind, log))
    .filter((entry): entry is StatementEntry => entry !== null)
}

/**
 * Draws and repayments for one borrower, read from `Borrowed` / `Repaid` logs
 * via the Blockscout logs API. Newest first. Refetches after every confirmed
 * transaction.
 */
export function useStatement(address: string): {
  entries: StatementEntry[]
  isLoading: boolean
  error: string | null
} {
  const managerAddress = useConfigStore((s) => s.managerAddress)
  const refreshKey = useWalletStore((s) => s.refreshKey)
  const [entries, setEntries] = useState<StatementEntry[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!ethers.isAddress(address) || !ethers.isAddress(managerAddress)) {
      setEntries([])
      setIsLoading(false)
      setError(null)
      return
    }

    const controller = new AbortController()
    setIsLoading(true)
    setError(null)

    void (async () => {
      try {
        const [draws, repayments] = await Promise.all([
          fetchEntries('draw', managerAddress, address, controller.signal),
          fetchEntries('repay', managerAddress, address, controller.signal),
        ])
        if (controller.signal.aborted) return
        const merged = [...draws, ...repayments].sort(
          (a, b) => b.block - a.block || b.logIndex - a.logIndex,
        )
        setEntries(merged)
        setError(null)
      } catch (err) {
        if (controller.signal.aborted) return
        if (isRecord(err) && err.name === 'AbortError') return
        console.error('[useStatement] fetch failed:', err)
        setEntries([])
        setError(STATEMENT_ERROR)
      } finally {
        if (!controller.signal.aborted) setIsLoading(false)
      }
    })()

    return () => controller.abort()
  }, [address, managerAddress, refreshKey])

  return { entries, isLoading, error }
}
