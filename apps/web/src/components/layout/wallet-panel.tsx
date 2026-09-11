import { Wallet, ArrowLeftRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useWalletStore } from '@/stores/wallet-store'
import { useConfigStore } from '@/stores/config-store'
import { getEthereum, ensureWalletChain } from '@/lib/ethereum'
import { shortAddr } from '@/lib/format'

export function WalletPanel() {
  const walletAccount = useWalletStore((s) => s.walletAccount)
  const walletChainId = useWalletStore((s) => s.walletChainId)
  const connectWallet = useWalletStore((s) => s.connectWallet)
  const chainId = useConfigStore((s) => s.chainId)
  const rpcUrl = useConfigStore((s) => s.rpcUrl)
  const hasInjectedWallet = getEthereum() !== null
  const chainMismatch = walletChainId !== null && walletChainId !== chainId

  return (
    <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 rounded-2xl border border-border/40 bg-gradient-to-b from-[rgba(18,30,61,0.72)] to-[rgba(12,21,45,0.84)] p-3.5 sm:p-4">
      <div className="grid gap-2 min-w-0">
        <div className="flex items-center gap-2.5">
          <span className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">
            Wallet
          </span>
          <span className="font-mono text-xs">
            {walletAccount ? shortAddr(walletAccount) : 'Disconnected'}
          </span>
        </div>
        <div className="flex items-center gap-2.5">
          <span className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">
            Chain
          </span>
          <span className="font-mono text-xs">{walletChainId ?? '—'}</span>
          {chainMismatch && (
            <Badge variant="outline" className="border-warning/40 text-warning text-[10px]">
              Expected: {chainId}
            </Badge>
          )}
        </div>
      </div>

      <div className="flex gap-2 w-full sm:w-auto">
        <Button
          variant="default"
          size="sm"
          className="flex-1 sm:flex-none"
          onClick={() => void connectWallet()}
          disabled={!hasInjectedWallet}
        >
          <Wallet className="mr-1.5 h-3.5 w-3.5" />
          {hasInjectedWallet ? 'Connect' : 'No Wallet'}
        </Button>
        <Button
          variant="secondary"
          size="sm"
          className="flex-1 sm:flex-none"
          onClick={() => void ensureWalletChain(chainId, rpcUrl)}
          disabled={!hasInjectedWallet}
        >
          <ArrowLeftRight className="mr-1.5 h-3.5 w-3.5" />
          Chain {chainId}
        </Button>
      </div>
    </div>
  )
}
