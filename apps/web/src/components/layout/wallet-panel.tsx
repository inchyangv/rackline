import { Wallet, ArrowLeftRight, AlertTriangle } from 'lucide-react'
import { Button } from '@/components/ui/button'
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
  const refreshWalletState = useWalletStore((s) => s.refreshWalletState)
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
    <div className="flex flex-col gap-3 rounded-2xl border border-border/40 bg-gradient-to-b from-[rgba(18,30,61,0.72)] to-[rgba(12,21,45,0.84)] p-3.5 sm:p-4">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
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
          </div>
        </div>

        <Button
          variant="default"
          size="sm"
          className="w-full sm:w-auto"
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
      </div>

      {chainMismatch && (
        <div className="flex items-center justify-between gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2">
          <div className="flex items-center gap-1.5 text-xs text-amber-300 min-w-0">
            <AlertTriangle className="h-3.5 w-3.5 flex-shrink-0" />
            <span>Wrong network — switch to {getChainName(chainId)} to use HashCredit</span>
          </div>
          <Button
            variant="outline"
            size="xs"
            className="border-amber-500/40 text-amber-300 hover:bg-amber-500/20 flex-shrink-0"
            onClick={async () => {
              const ok = await ensureWalletChain(chainId, rpcUrl)
              if (ok) await refreshWalletState()
            }}
          >
            <ArrowLeftRight className="mr-1 h-3 w-3" />
            Switch
          </Button>
        </div>
      )}
    </div>
  )
}
