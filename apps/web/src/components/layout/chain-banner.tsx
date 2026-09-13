import { Button } from '@/components/ui/button'
import { BRAND } from '@/lib/brand'
import { ensureWalletChain } from '@/lib/ethereum'
import { useConfigStore } from '@/stores/config-store'
import { useWalletStore } from '@/stores/wallet-store'

/**
 * Shown only while the wallet is on another chain. Every action is blocked in
 * that state, so the banner carries the single remedy.
 */
export function ChainBanner() {
  const walletChainId = useWalletStore((s) => s.walletChainId)
  const chainId = useConfigStore((s) => s.chainId)
  const rpcUrl = useConfigStore((s) => s.rpcUrl)

  if (walletChainId === null || walletChainId === chainId) return null

  return (
    <div className="border-b border-warn/40 bg-warn/10 text-warn">
      <div className="mx-auto flex min-h-9 w-full max-w-[1120px] flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 py-2 text-xs sm:px-6">
        <p className="min-w-0">
          Wallet is on chain <span className="num">{walletChainId}</span>. {BRAND.name} runs on{' '}
          {BRAND.network} (<span className="num">{chainId}</span>).
        </p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="shrink-0 border-warn/40 text-warn hover:bg-warn/10"
          onClick={() => void ensureWalletChain(chainId, rpcUrl)}
        >
          Switch network
        </Button>
      </div>
    </div>
  )
}
