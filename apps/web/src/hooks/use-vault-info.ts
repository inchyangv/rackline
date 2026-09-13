import { useEffect, useState, useCallback } from 'react'
import { useVaultRead } from './use-contracts'
import { useWalletStore } from '@/stores/wallet-store'
import { ethers } from 'ethers'

export type VaultInfo = {
  /** The token the vault actually settles in, per `asset()`. Null until read. */
  asset: string | null
  totalAssets: bigint | null
  totalBorrowed: bigint | null
  availableLiquidity: bigint | null
  totalShares: bigint | null
  utilizationRate: bigint | null
  borrowAPR: bigint | null
  myShares: bigint | null
  myShareValue: bigint | null
  isLoading: boolean
  error: string | null
}

export function useVaultInfo(): VaultInfo {
  const vault = useVaultRead()
  const walletAccount = useWalletStore((s) => s.walletAccount)
  const refreshKey = useWalletStore((s) => s.refreshKey)

  const [asset, setAsset] = useState<string | null>(null)
  const [totalAssets, setTotalAssets] = useState<bigint | null>(null)
  const [totalBorrowed, setTotalBorrowed] = useState<bigint | null>(null)
  const [availableLiquidity, setAvailableLiquidity] = useState<bigint | null>(null)
  const [totalShares, setTotalShares] = useState<bigint | null>(null)
  const [utilizationRate, setUtilizationRate] = useState<bigint | null>(null)
  const [borrowAPR, setBorrowAPR] = useState<bigint | null>(null)
  const [myShares, setMyShares] = useState<bigint | null>(null)
  const [myShareValue, setMyShareValue] = useState<bigint | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const fetchVaultInfo = useCallback(async () => {
    if (!vault) {
      setIsLoading(false)
      return
    }

    try {
      const [ta, tb, al, ts, ur, apr, token] = await Promise.all([
        vault.totalAssets() as Promise<bigint>,
        vault.totalBorrowed() as Promise<bigint>,
        vault.availableLiquidity() as Promise<bigint>,
        vault.totalShares() as Promise<bigint>,
        vault.utilizationRate() as Promise<bigint>,
        vault.borrowAPR() as Promise<bigint>,
        // The authoritative token for balances, allowances and approvals. Read
        // on its own terms: a vault that cannot answer must not blank the pool.
        (vault.asset() as Promise<string>).catch(() => null),
      ])

      setAsset(token !== null && ethers.isAddress(token) ? token : null)
      setTotalAssets(ta)
      setTotalBorrowed(tb)
      setAvailableLiquidity(al)
      setTotalShares(ts)
      setUtilizationRate(ur)
      setBorrowAPR(apr)
      setError(null)

      if (ethers.isAddress(walletAccount)) {
        const shares = (await vault.sharesOf(walletAccount)) as bigint
        setMyShares(shares)
        if (shares > 0n) {
          const value = (await vault.convertToAssets(shares)) as bigint
          setMyShareValue(value)
        } else {
          setMyShareValue(0n)
        }
      } else {
        setMyShares(null)
        setMyShareValue(null)
      }
    } catch (err) {
      console.error('[useVaultInfo] fetch failed:', err)
      setAsset(null)
      setTotalAssets(null)
      setTotalBorrowed(null)
      setAvailableLiquidity(null)
      setTotalShares(null)
      setUtilizationRate(null)
      setBorrowAPR(null)
      setMyShares(null)
      setMyShareValue(null)
      setError(err instanceof Error ? err.message : 'Failed to read pool.')
    } finally {
      setIsLoading(false)
    }
  }, [vault, walletAccount])

  useEffect(() => {
    void fetchVaultInfo()
  }, [fetchVaultInfo, refreshKey])

  return {
    asset,
    totalAssets,
    totalBorrowed,
    availableLiquidity,
    totalShares,
    utilizationRate,
    borrowAPR,
    myShares,
    myShareValue,
    isLoading,
    error,
  }
}
