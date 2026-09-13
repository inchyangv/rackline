import { useEffect, useState } from 'react'
import { useStablecoinRead } from '@/hooks/use-contracts'
import { useWalletStore } from '@/stores/wallet-store'
import { useConfigStore } from '@/stores/config-store'

/** mUSDT on this deployment. Used until the token answers for itself. */
const FALLBACK_DECIMALS = 6

/**
 * Decimals of the pool asset, read from the token. Vault shares use the same
 * scale. Pass the vault's own `asset()` where it is known; the configured
 * address is only a stand-in until that read lands.
 */
export function usePoolDecimals(assetAddress?: string | null): number {
  const configStablecoin = useConfigStore((s) => s.stablecoinAddress)
  const token = useStablecoinRead(assetAddress || configStablecoin)
  const refreshKey = useWalletStore((s) => s.refreshKey)
  const [decimals, setDecimals] = useState(FALLBACK_DECIMALS)

  useEffect(() => {
    let cancelled = false
    async function run(): Promise<void> {
      if (!token) return
      try {
        const raw = (await token.decimals()) as bigint | number
        const next = Number(raw)
        if (!cancelled && Number.isInteger(next) && next >= 0 && next <= 36) setDecimals(next)
      } catch {
        if (!cancelled) setDecimals(FALLBACK_DECIMALS)
      }
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [token, refreshKey])

  return decimals
}
