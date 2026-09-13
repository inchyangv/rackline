import { useEffect, useState } from 'react'
import { ethers } from 'ethers'
import { useManagerRead, useStablecoinRead } from './use-contracts'
import { useWalletStore } from '@/stores/wallet-store'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

/** Mirrors IHashCreditManager.BorrowerStatus. */
export const BorrowerStatus = {
  None: 0,
  Active: 1,
  Frozen: 2,
  Closed: 3,
} as const

export type BorrowerInfo = {
  status: number
  btcPayoutKeyHash: string
  creditLimit: bigint
  currentDebt: bigint
  registeredAt: bigint
  payoutCount: number
}

const ZERO_BYTES32 = `0x${'0'.repeat(64)}`

function toBorrowerInfo(raw: unknown): BorrowerInfo | null {
  if (!isRecord(raw)) return null
  const nested = isRecord(raw.info) ? raw.info : raw
  const status = typeof nested.status === 'bigint' ? Number(nested.status) : Number(nested.status ?? 0)
  return {
    status: Number.isFinite(status) ? status : 0,
    btcPayoutKeyHash: typeof nested.btcPayoutKeyHash === 'string' ? nested.btcPayoutKeyHash : ZERO_BYTES32,
    creditLimit: typeof nested.creditLimit === 'bigint' ? nested.creditLimit : 0n,
    currentDebt: typeof nested.currentDebt === 'bigint' ? nested.currentDebt : 0n,
    registeredAt: typeof nested.registeredAt === 'bigint' ? nested.registeredAt : 0n,
    payoutCount: typeof nested.payoutCount === 'bigint' ? Number(nested.payoutCount) : 0,
  }
}

export function useBorrowerInfo(borrowerAddress: string, stablecoinAddress: string) {
  const managerRead = useManagerRead()
  const stablecoinRead = useStablecoinRead(stablecoinAddress)
  const refreshKey = useWalletStore((s) => s.refreshKey)
  const [availableCredit, setAvailableCredit] = useState<bigint | null>(null)
  const [borrowerInfo, setBorrowerInfo] = useState<BorrowerInfo | null>(null)
  const [stablecoinDecimals, setStablecoinDecimals] = useState(6)
  const [stablecoinBalance, setStablecoinBalance] = useState<bigint | null>(null)
  const [currentDebt, setCurrentDebt] = useState<bigint | null>(null)
  const [accruedInterest, setAccruedInterest] = useState<bigint | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function run(): Promise<void> {
      if (!managerRead || !ethers.isAddress(borrowerAddress)) {
        setBorrowerInfo(null)
        setAvailableCredit(null)
        setStablecoinBalance(null)
        setCurrentDebt(null)
        setAccruedInterest(null)
        setError(null)
        return
      }

      setIsLoading(true)
      setError(null)
      try {
        const [credit, infoRaw, debt, interest] = await Promise.all([
          managerRead.getAvailableCredit(borrowerAddress) as Promise<bigint>,
          managerRead.getBorrowerInfo(borrowerAddress) as Promise<unknown>,
          managerRead.getCurrentDebt(borrowerAddress) as Promise<bigint>,
          managerRead.getAccruedInterest(borrowerAddress) as Promise<bigint>,
        ])

        if (cancelled) return
        setAvailableCredit(credit)
        setCurrentDebt(debt)
        setAccruedInterest(interest)
        setBorrowerInfo(toBorrowerInfo(infoRaw))
      } catch (err) {
        if (cancelled) return
        setBorrowerInfo(null)
        setAvailableCredit(null)
        setCurrentDebt(null)
        setAccruedInterest(null)
        setError(err instanceof Error ? err.message : 'Failed to read facility.')
      }

      try {
        if (!stablecoinRead) return
        const [decimals, balance] = await Promise.all([
          stablecoinRead.decimals() as Promise<number>,
          stablecoinRead.balanceOf(borrowerAddress) as Promise<bigint>,
        ])
        if (cancelled) return
        setStablecoinDecimals(Number(decimals))
        setStablecoinBalance(balance)
      } catch {
        if (cancelled) return
        setStablecoinDecimals(6)
        setStablecoinBalance(null)
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [managerRead, stablecoinRead, borrowerAddress, refreshKey])

  const isBtcLinked = !!borrowerInfo && borrowerInfo.btcPayoutKeyHash !== ZERO_BYTES32

  return {
    availableCredit,
    borrowerInfo,
    isBtcLinked,
    stablecoinDecimals,
    stablecoinBalance,
    currentDebt,
    accruedInterest,
    isLoading,
    error,
  }
}
