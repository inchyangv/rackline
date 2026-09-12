import { Wallet, ArrowLeftRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useWalletStore } from '@/stores/wallet-store'
import { useConfigStore } from '@/stores/config-store'
import { getEthereum, ensureWalletChain } from '@/lib/ethereum'
import { shortAddr } from '@/lib/format'
import { cn } from '@/lib/utils'

const CHAIN_NAMES: Record<number, string> = {
  133: 'HashKey Testnet',
  2370: 'Creditcoin Testnet',
}

function getChainName(id: number | null): string {
  if (id === null) return '—'
  return CHAIN_NAMES[id] ?? `Chain ${id}`
}

export function WalletPanel() {
  const walletAccount = useWalletStore((s) => s.walletAccount)
  const walletChainId = useWalletStore((s) => s.walletChainId)
  const connectWallet = useWalletStore((s) => s.connectWallet)
  const disconnectWallet = useWalletStore((s) => s.disconnectWallet)
  const chainId = useConfigStore((s) => s.chainId)
  const rpcUrl = useConfigStore((s) => s.rpcUrl)
  const hasInjectedWallet = getEthereum() !== null
  const isConnected = Boolean(walletAccount)
  const chainMismatch = walletChainId !== null && walletChainId !== chainId

  const networkName = getChainName(walletChainId ?? chainId)
  const dotColor = !isConnected
    ? 'bg-muted-foreground'
    : chainMismatch
      ? 'bg-amber-400'
      : 'bg-emerald-400'

  return (
    <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 rounded-2xl border border-border/40 bg-gradient-to-b from-[rgba(18,30,61,0.72)] to-[rgba(12,21,45,0.84)] p-3.5 sm:p-4">
      <div className="grid gap-2 min-w-0">
        <div className="flex items-center gap-2.5">
          <span className="text-[11px] uppercase tracking-wider text-muted-foreground font-semibold">
            Wallet
          </span>
          <span className={cn('font-mono text-xs', !walletAccount && 'text-muted-foreground italic')}>
            {walletAccount ? shortAddr(walletAccount) : 'Not connected'}
          </span>
        </div>
        <div className="flex items-center gap-2.5">
          <span className="text-[11px] uppercase tracking-wider text-muted-foreground font-semibold">
            Network
          </span>
          <span className="flex items-center gap-1.5 text-xs">
            <span className={cn('h-1.5 w-1.5 rounded-full flex-shrink-0', dotColor)} />
            <span title={`Chain ID: ${walletChainId ?? chainId}`}>{networkName}</span>
          </span>
          {chainMismatch && (
            <Badge variant="outline" className="border-warning/40 text-warning text-[10px]">
              Expected: {getChainName(chainId)}
            </Badge>
          )}
        </div>
      </div>

      <div className="flex gap-2 w-full sm:w-auto">
        <Button
          variant="default"
          size="sm"
          className="flex-1 sm:flex-none"
          onClick={() => {
            if (isConnected) {
              disconnectWallet()
              return
            }
            void connectWallet()
          }}
          disabled={!hasInjectedWallet}
        >
          <Wallet className="mr-1.5 h-3.5 w-3.5" />
          {hasInjectedWallet
            ? isConnected
              ? 'Disconnect'
              : 'Connect Wallet'
            : 'Install MetaMask'}
        </Button>
        <Button
          variant="secondary"
          size="sm"
          className="flex-1 sm:flex-none"
          onClick={() => void ensureWalletChain(chainId, rpcUrl)}
          disabled={!hasInjectedWallet}
        >
          <ArrowLeftRight className="mr-1.5 h-3.5 w-3.5" />
          Switch Network
        </Button>
      </div>
    </div>
  )
}
