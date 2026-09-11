import { ethers } from 'ethers'
import { SectionCard } from '@/components/shared/section-card'
import { KeyValueList } from '@/components/shared/key-value-list'
import { KeyValueRow } from '@/components/shared/key-value-row'
import { Skeleton } from '@/components/ui/skeleton'
import { useVaultInfo } from '@/hooks/use-vault-info'
import { PoolStatusCard } from './pool-status-card'
import { DepositCard } from './deposit-card'
import { WithdrawCard } from './withdraw-card'

const DECIMALS = 6

export function PoolTab() {
  const vault = useVaultInfo()
  const { myShares, myShareValue, isLoading } = vault

  return (
    <>
      <PoolStatusCard vault={vault} />

      <SectionCard title="My Position" description="Your current pool position">
        <KeyValueList>
          <KeyValueRow
            label="My Shares"
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
                `${ethers.formatUnits(myShareValue, DECIMALS)} mUSDT`
              )
            }
            mono
          />
        </KeyValueList>
      </SectionCard>

      <DepositCard />
      <WithdrawCard vault={vault} />
    </>
  )
}
