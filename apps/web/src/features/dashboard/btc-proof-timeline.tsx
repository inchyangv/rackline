import { useMemo } from 'react'
import { Clock, FileText } from 'lucide-react'
import { ethers } from 'ethers'
import { SectionCard } from '@/components/shared/section-card'
import { EmptyState } from '@/components/shared/empty-state'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { ExplorerLink } from '@/components/shared/explorer-link'
import { shortBtcAddress, shortAddr } from '@/lib/format'
import { useDemoStore } from '@/stores/demo-store'
import { useApiStore } from '@/stores/api-store'

export function BtcProofTimeline() {
  const demoBtcPayoutHistory = useDemoStore((s) => s.demoBtcPayoutHistory)
  const demoWallets = useDemoStore((s) => s.demoWallets)
  const borrowerAddress = useApiStore((s) => s.borrowerAddress)

  const filteredHistory = useMemo(() => {
    const q = borrowerAddress.trim()
    if (!ethers.isAddress(q)) return demoBtcPayoutHistory
    const key = q.toLowerCase()
    return demoBtcPayoutHistory.filter((x) => x.borrower.toLowerCase() === key)
  }, [demoBtcPayoutHistory, borrowerAddress])

  const recentHistory = filteredHistory.slice(0, 20)

  return (
    <SectionCard
      title="BTC Proof Timeline (Demo)"
      description="Links proof build/submit events to Demo Wallets and BTC addresses. Use borrower search to filter."
      full
    >
      {recentHistory.length === 0 ? (
        <EmptyState
          icon={Clock}
          title="No BTC proof events recorded yet"
          description="Build and submit proofs to see them here"
        />
      ) : (
        <div className="space-y-2">
          {recentHistory.map((item) => {
            const linkedWallet = demoWallets.find(
              (w) => w.address.toLowerCase() === item.borrower.toLowerCase(),
            )
            return (
              <div
                key={item.id}
                className="rounded-xl border border-border/30 bg-gradient-to-br from-card/80 to-card/60 p-3 space-y-2"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="text-sm font-bold flex items-center gap-2">
                      <FileText className="h-3.5 w-3.5 text-muted-foreground" />
                      {linkedWallet?.name ?? 'External Borrower Wallet'}
                    </div>
                    <div className="font-mono text-xs text-muted-foreground truncate">
                      {item.borrower}
                    </div>
                  </div>
                  <Badge
                    variant={item.source === 'build+submit' ? 'default' : 'secondary'}
                    className="shrink-0"
                  >
                    {item.source === 'build+submit' ? 'Build + Submit' : 'Build Only'}
                  </Badge>
                </div>

                <Separator className="bg-border/20" />

                <div className="text-xs text-muted-foreground space-y-1">
                  <p>
                    BTC:{' '}
                    <span className="font-mono">
                      {item.btcAddress ? shortBtcAddress(item.btcAddress) : '—'}
                    </span>{' '}
                    | TX: <ExplorerLink txid={item.txid} /> | vout: {item.vout} | amount:{' '}
                    {item.amountSats === null ? '—' : `${item.amountSats} sats`}
                  </p>
                  <p>
                    checkpoint/target: {item.checkpointHeight}/{item.targetHeight}
                    {item.submitTxHash && (
                      <>
                        {' '}
                        | submit tx:{' '}
                        <span className="font-mono">{shortAddr(item.submitTxHash)}</span>
                      </>
                    )}
                    {' | '}recorded: {new Date(item.createdAt).toLocaleString()}
                  </p>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </SectionCard>
  )
}
