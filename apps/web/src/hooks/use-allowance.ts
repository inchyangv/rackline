import { useEffect, useState } from 'react'
import { ethers } from 'ethers'
import { useStablecoinRead } from './use-contracts'
import { useWalletStore } from '@/stores/wallet-store'

/**
 * ERC20 allowance of `owner` → `spender` for `tokenAddress`.
 * Refetches after every confirmed transaction.
 */
export function useAllowance(tokenAddress: string, owner: string, spender: string) {
  const token = useStablecoinRead(tokenAddress)
  const refreshKey = useWalletStore((s) => s.refreshKey)
  const [allowance, setAllowance] = useState<bigint | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  useEffect(() => {
    let cancelled = false
    async function run() {
      if (!token || !ethers.isAddress(owner) || !ethers.isAddress(spender)) {
        setAllowance(null)
        return
      }
      setIsLoading(true)
      try {
        const v = (await token.allowance(owner, spender)) as bigint
        if (!cancelled) setAllowance(v)
      } catch {
        if (!cancelled) setAllowance(null)
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [token, owner, spender, refreshKey])

  return { allowance, isLoading }
}
