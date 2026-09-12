import { ethers } from 'ethers'
import { useState } from 'react'
import { Layers } from 'lucide-react'
import { SectionCard } from '@/components/shared/section-card'
import { KeyValueList } from '@/components/shared/key-value-list'
import { KeyValueRow } from '@/components/shared/key-value-row'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/shared/empty-state'
import { useVaultInfo } from '@/hooks/use-vault-info'
import { useWalletStore } from '@/stores/wallet-store'
import { PoolStatusCard } from './pool-status-card'
import { DepositCard } from './deposit-card'
import { WithdrawCard } from './withdraw-card'
import { STABLECOIN_SYMBOL } from '@/lib/constants'

const DECIMALS = 6

export function PoolTab() {
  const vault = useVaultInfo()
  const { myShares, myShareValue, isLoading } = vault
  const walletAccount = useWalletStore((s) => s.walletAccount)
  const [actionTab, setActionTab] = useState<'deposit' | 'withdraw'>('deposit')

  return (
    <>
      {/* Pool Status */}
      <PoolStatusCard vault={vault} />

      {/* My Position */}
      <SectionCard title="My Position" description="Your current pool position">
        {!walletAccount ? (
          <EmptyState
            icon={Layers}
            title="Connect wallet to view position"
            description="Your pool shares and value will appear here once you connect your wallet."
          />
        ) : isLoading ? (
          <KeyValueList>
            <KeyValueRow label="My Shares" value={<Skeleton className="h-4 w-32" />} mono />
            <KeyValueRow label="Current Value" value={<Skeleton className="h-4 w-32" />} mono />
          </KeyValueList>
        ) : myShares === null || myShares === 0n ? (
          <EmptyState
            icon={Layers}
            title="No pool position yet"
            description="Deposit mUSDT below to start earning yield."
            actionLabel="Deposit"
            onAction={() => setActionTab('deposit')}
          />
        ) : (
          <KeyValueList>
            <KeyValueRow
              label={
                <span className="flex items-center gap-1">
                  My Shares
                  <span
                    className="text-[10px] text-muted-foreground cursor-help"
                    title="Pool ownership tokens. Value grows as the pool earns yield."
                  >
                    ⓘ
                  </span>
                </span>
              }
              value={ethers.formatUnits(myShares, DECIMALS)}
              mono
            />
            <KeyValueRow
              label="Current Value"
              value={
                myShareValue === null
                  ? '—'
                  : `${ethers.formatUnits(myShareValue, DECIMALS)} ${STABLECOIN_SYMBOL}`
              }
              mono
            />
          </KeyValueList>
        )}
      </SectionCard>

      {/* Deposit / Withdraw — single full-width tabbed card */}
      <SectionCard
        full
        title={
          <div className="flex gap-1">
            <button
              className={`px-3 py-1 text-sm rounded-md transition-colors ${
                actionTab === 'deposit'
                  ? 'bg-primary text-primary-foreground font-medium'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
              onClick={() => setActionTab('deposit')}
            >
              Deposit
            </button>
            <button
              className={`px-3 py-1 text-sm rounded-md transition-colors ${
                actionTab === 'withdraw'
                  ? 'bg-primary text-primary-foreground font-medium'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
              onClick={() => setActionTab('withdraw')}
            >
              Withdraw
            </button>
          </div>
        }
        description={
          actionTab === 'deposit' ? 'Deposit mUSDT to earn yield' : 'Redeem shares for mUSDT'
        }
      >
        {actionTab === 'deposit' ? (
          <DepositCard embedded />
        ) : (
          <WithdrawCard vault={vault} embedded />
        )}
      </SectionCard>
    </>
  )
}
