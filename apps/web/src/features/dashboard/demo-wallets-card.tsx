import { useMemo } from 'react'
import { WalletCards, RefreshCw } from 'lucide-react'
import { SectionCard } from '@/components/shared/section-card'
import { EmptyState } from '@/components/shared/empty-state'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { DemoWalletItem } from './demo-wallet-item'
import { useDemoStore } from '@/stores/demo-store'
import { useApiStore } from '@/stores/api-store'
import { useBtcHistory } from '@/hooks/use-btc-history'

const BTC_HISTORY_REFRESH_INTERVAL_MS = 30_000

export function DemoWalletsCard() {
  const demoWallets = useDemoStore((s) => s.demoWallets)
  const borrowerBtcMap = useDemoStore((s) => s.borrowerBtcMap)
  const demoBtcPayoutHistory = useDemoStore((s) => s.demoBtcPayoutHistory)
  const btcHistoryMiningOnly = useDemoStore((s) => s.btcHistoryMiningOnly)
  const btcHistoryAutoRefreshEnabled = useDemoStore((s) => s.btcHistoryAutoRefreshEnabled)
  const setBtcHistoryMiningOnly = useDemoStore((s) => s.setBtcHistoryMiningOnly)
  const setBtcHistoryAutoRefreshEnabled = useDemoStore((s) => s.setBtcHistoryAutoRefreshEnabled)
  const createDemoWallet = useDemoStore((s) => s.createDemoWallet)
  const removeDemoWallet = useDemoStore((s) => s.removeDemoWallet)
  const applyAsBorrower = useApiStore((s) => s.applyAsBorrower)
  const {
    fetchBtcAddressHistory,
    refreshAllLinkedBtc,
    btcChainHistoryByAddress,
    btcChainHistoryLoading,
    btcChainHistoryError,
  } = useBtcHistory()

  const payoutCountByBorrower = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const payout of demoBtcPayoutHistory) {
      const key = payout.borrower.toLowerCase()
      counts[key] = (counts[key] ?? 0) + 1
    }
    return counts
  }, [demoBtcPayoutHistory])

  return (
    <SectionCard
      title="Demo Wallets (Generate)"
      description="Demo-only. Private keys stored in browser localStorage. Never use on mainnet."
      full
    >
      <div className="space-y-3">
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" size="sm" onClick={() => createDemoWallet(1)}>
            Generate 1 Wallet
          </Button>
          <Button size="sm" onClick={() => createDemoWallet(3)}>
            Generate 3 Wallets
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void refreshAllLinkedBtc()}
            disabled={Object.keys(borrowerBtcMap).length === 0}
          >
            <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
            Refresh linked BTC
          </Button>
        </div>

        <div className="flex flex-wrap gap-4">
          <div className="flex items-center gap-2">
            <Checkbox
              id="mining-only"
              checked={btcHistoryMiningOnly}
              onCheckedChange={(v) => setBtcHistoryMiningOnly(v === true)}
            />
            <Label htmlFor="mining-only" className="text-xs text-muted-foreground cursor-pointer">
              Mining rewards only
            </Label>
          </div>
          <div className="flex items-center gap-2">
            <Checkbox
              id="auto-refresh"
              checked={btcHistoryAutoRefreshEnabled}
              onCheckedChange={(v) => setBtcHistoryAutoRefreshEnabled(v === true)}
            />
            <Label htmlFor="auto-refresh" className="text-xs text-muted-foreground cursor-pointer">
              Auto-refresh every {Math.floor(BTC_HISTORY_REFRESH_INTERVAL_MS / 1000)}s
            </Label>
          </div>
        </div>

        {demoWallets.length === 0 ? (
          <EmptyState
            icon={WalletCards}
            title="No demo wallets generated yet"
            description="Generate demo wallets to test borrower registration and proof flows"
            actionLabel="Generate Wallet"
            onAction={() => createDemoWallet(1)}
          />
        ) : (
          <div className="space-y-2">
            {demoWallets.map((w) => {
              const linkedBtcAddress = borrowerBtcMap[w.address.toLowerCase()] ?? ''
              const linkedPayouts = payoutCountByBorrower[w.address.toLowerCase()] ?? 0
              const historyKey = linkedBtcAddress ? linkedBtcAddress.toLowerCase() : ''
              return (
                <DemoWalletItem
                  key={w.address}
                  wallet={w}
                  linkedBtcAddress={linkedBtcAddress}
                  linkedPayouts={linkedPayouts}
                  chainHistory={historyKey ? btcChainHistoryByAddress[historyKey] : undefined}
                  chainHistoryLoading={historyKey ? Boolean(btcChainHistoryLoading[historyKey]) : false}
                  chainHistoryError={historyKey ? (btcChainHistoryError[historyKey] ?? '') : ''}
                  onSetAsBorrower={applyAsBorrower}
                  onRemove={removeDemoWallet}
                  onLoadHistory={(addr) =>
                    void fetchBtcAddressHistory(addr, btcHistoryMiningOnly ? 50 : 12, btcHistoryMiningOnly)
                  }
                />
              )
            })}
          </div>
        )}
      </div>
    </SectionCard>
  )
}
