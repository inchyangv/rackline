import { Trash2, Copy, User, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { ExplorerLink } from '@/components/shared/explorer-link'
import { shortBtcAddress, shortAddr } from '@/lib/format'
import { copyToClipboard } from '@/lib/clipboard'
import { toast } from 'sonner'
import type { DemoWallet, BtcAddressHistorySnapshot } from '@/types'

type Props = {
  wallet: DemoWallet
  linkedBtcAddress: string
  linkedPayouts: number
  chainHistory?: BtcAddressHistorySnapshot
  chainHistoryLoading: boolean
  chainHistoryError: string
  onSetAsBorrower: (address: string) => void
  onRemove: (address: string) => void
  onLoadHistory: (address: string) => void
}

export function DemoWalletItem({
  wallet,
  linkedBtcAddress,
  linkedPayouts,
  chainHistory,
  chainHistoryLoading,
  chainHistoryError,
  onSetAsBorrower,
  onRemove,
  onLoadHistory,
}: Props) {
  const miningRewardCount = chainHistory
    ? chainHistory.items.filter((item) => item.is_mining_reward).length
    : 0

  const handleCopy = (text: string, label: string) => {
    void copyToClipboard(text)
    toast.success(`${label} copied`)
  }

  return (
    <div className="rounded-xl border border-border/30 bg-gradient-to-br from-card/80 to-card/60 p-3 space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-sm font-bold">{wallet.name}</div>
          <div className="font-mono text-xs text-muted-foreground truncate">{wallet.address}</div>
        </div>
        <div className="flex flex-wrap gap-1 shrink-0">
          <Button variant="secondary" size="sm" className="h-7 text-[11px]" onClick={() => onSetAsBorrower(wallet.address)}>
            <User className="mr-1 h-3 w-3" />
            Set as borrower
          </Button>
          <Button variant="ghost" size="sm" className="h-7 text-[11px]" onClick={() => handleCopy(wallet.address, 'Address')}>
            <Copy className="mr-1 h-3 w-3" />
            Addr
          </Button>
          <Button variant="ghost" size="sm" className="h-7 text-[11px]" onClick={() => handleCopy(wallet.privateKey, 'Private key')}>
            <Copy className="mr-1 h-3 w-3" />
            Key
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 text-[11px]"
            onClick={() => onLoadHistory(linkedBtcAddress)}
            disabled={!linkedBtcAddress || chainHistoryLoading}
          >
            <RefreshCw className={`mr-1 h-3 w-3 ${chainHistoryLoading ? 'animate-spin' : ''}`} />
            BTC
          </Button>
          <Button variant="ghost" size="sm" className="h-7 text-[11px] text-destructive hover:text-destructive" onClick={() => onRemove(wallet.address)}>
            <Trash2 className="h-3 w-3" />
          </Button>
        </div>
      </div>

      <Separator className="bg-border/20" />

      <div className="text-xs text-muted-foreground space-y-1">
        <p>
          Created: {new Date(wallet.createdAt).toLocaleString()} | Linked BTC:{' '}
          <span className="font-mono">{linkedBtcAddress ? shortBtcAddress(linkedBtcAddress) : '—'}</span>{' '}
          | Proofs: {linkedPayouts} | Key: <span className="font-mono">{shortAddr(wallet.privateKey)}</span>
        </p>

        {chainHistoryError && (
          <p className="text-destructive">BTC history error: {chainHistoryError}</p>
        )}

        {chainHistory && (
          <p>
            BTC balance: {chainHistory.balanceChainSats ?? 0} sats
            {chainHistory.balanceMempoolDeltaSats
              ? ` (mempool: ${chainHistory.balanceMempoolDeltaSats} sats)`
              : ''}{' '}
            | tx: {chainHistory.txCountChain ?? 0} | mining: {miningRewardCount} | mode:{' '}
            {chainHistory.miningOnly ? 'mining-only' : 'all'} | refreshed:{' '}
            {new Date(chainHistory.fetchedAt).toLocaleTimeString()}
          </p>
        )}

        {chainHistory && chainHistory.items.length > 0 && (
          <p>
            Recent tx:{' '}
            {chainHistory.items.slice(0, 3).map((item) => {
              const directionLabel = item.is_mining_reward ? 'mining reward' : item.direction
              const txLabel = `${directionLabel} ${item.net_sats >= 0 ? '+' : ''}${item.net_sats} sats`
              return (
                <span key={item.txid} className="mr-2">
                  <ExplorerLink txid={item.txid} /> ({txLabel})
                </span>
              )
            })}
          </p>
        )}
      </div>
    </div>
  )
}
