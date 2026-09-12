import { useEffect, useState } from 'react'
import { ethers } from 'ethers'
import { useManagerRead, useStablecoinRead } from './use-contracts'
import { useWalletStore } from '@/stores/wallet-store'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

export function useBorrowerInfo(borrowerAddress: string, stablecoinAddress: string) {
  const managerRead = useManagerRead()
  const stablecoinRead = useStablecoinRead(stablecoinAddress)
  const txStatus = useWalletStore((s) => s.txState.status)
  const [availableCredit, setAvailableCredit] = useState<bigint | null>(null)
  const [borrowerInfo, setBorrowerInfo] = useState<Record<string, unknown> | null>(null)
  const [stablecoinDecimals, setStablecoinDecimals] = useState(6)
  const [stablecoinBalance, setStablecoinBalance] = useState<bigint | null>(null)
  const [currentDebt, setCurrentDebt] = useState<bigint | null>(null)
  const [accruedInterest, setAccruedInterest] = useState<bigint | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  useEffect(() => {
    let cancelled = false

    async function run(): Promise<void> {
      if (!managerRead || !ethers.isAddress(borrowerAddress)) {
        setBorrowerInfo(null)
        setAvailableCredit(null)
        setStablecoinBalance(null)
        setCurrentDebt(null)
        setAccruedInterest(null)
        setIsLoading(false)
        return
      }

      setIsLoading(true)
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

        if (isRecord(infoRaw)) {
          const nested = infoRaw.info
          setBorrowerInfo(isRecord(nested) ? nested : infoRaw)
        } else {
          setBorrowerInfo(null)
        }
      } catch {
        if (cancelled) return
        setBorrowerInfo(null)
        setAvailableCredit(null)
        setCurrentDebt(null)
        setAccruedInterest(null)
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
    const interval = setInterval(() => {
      void run()
    }, 10_000)

    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [managerRead, stablecoinRead, borrowerAddress, txStatus])

  return { availableCredit, borrowerInfo, stablecoinDecimals, stablecoinBalance, currentDebt, accruedInterest, isLoading }
}
