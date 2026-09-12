import { ethers } from 'ethers'
import { useState } from 'react'
import { SectionCard } from '@/components/shared/section-card'
import { KeyValueList } from '@/components/shared/key-value-list'
import { KeyValueRow } from '@/components/shared/key-value-row'
import { Skeleton } from '@/components/ui/skeleton'
import { useVaultInfo } from '@/hooks/use-vault-info'
import { PoolStatusCard } from './pool-status-card'
import { DepositCard } from './deposit-card'
import { WithdrawCard } from './withdraw-card'
import { STABLECOIN_SYMBOL } from '@/lib/constants'

const DECIMALS = 6

export function PoolTab() {
  const vault = useVaultInfo()
  const { myShares, myShareValue, isLoading } = vault
  const [actionTab, setActionTab] = useState<'deposit' | 'withdraw'>('deposit')

  return (
    <>
      {/* Pool Status */}
      <PoolStatusCard vault={vault} />

      {/* My Position */}
      <SectionCard title="My Position" description="Your current pool position">
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
            value={
              isLoading ? (
                <Skeleton className="h-4 w-32" />
              ) : myShares === null ? (
                '—'
              ) : (
                ethers.formatUnits(myShares, DECIMALS)
              )
            }
            mono
          />
          <KeyValueRow
            label="Current Value"
            value={
              isLoading ? (
                <Skeleton className="h-4 w-32" />
              ) : myShareValue === null ? (
                '—'
              ) : (
                `${ethers.formatUnits(myShareValue, DECIMALS)} ${STABLECOIN_SYMBOL}`
              )
            }
            mono
          />
        </KeyValueList>
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
