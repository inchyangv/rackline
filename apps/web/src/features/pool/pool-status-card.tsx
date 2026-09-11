import { ethers } from 'ethers'
import { SectionCard } from '@/components/shared/section-card'
import { KeyValueList } from '@/components/shared/key-value-list'
import { KeyValueRow } from '@/components/shared/key-value-row'
import { Skeleton } from '@/components/ui/skeleton'
import type { VaultInfo } from '@/hooks/use-vault-info'

const DECIMALS = 6

type Props = {
  vault: VaultInfo
}

export function PoolStatusCard({ vault }: Props) {
  const { totalAssets, totalBorrowed, availableLiquidity, utilizationRate, borrowAPR, isLoading } =
    vault

  function fmtAmount(val: bigint | null) {
    if (isLoading) return <Skeleton className="h-4 w-32" />
    if (val === null) return '—'
    return `${ethers.formatUnits(val, DECIMALS)} mUSDT`
  }

  function fmtBps(val: bigint | null) {
    if (isLoading) return <Skeleton className="h-4 w-20" />
    if (val === null) return '—'
    return `${(Number(val) / 100).toFixed(2)}%`
  }

  return (
    <SectionCard title="Pool Status" description="Current lending pool metrics">
      <KeyValueList>
        <KeyValueRow label="Total Pool Assets" value={fmtAmount(totalAssets)} mono />
        <KeyValueRow label="Total Borrowed" value={fmtAmount(totalBorrowed)} mono />
        <KeyValueRow label="Available Liquidity" value={fmtAmount(availableLiquidity)} mono />
        <KeyValueRow label="Utilization Rate" value={fmtBps(utilizationRate)} mono />
        <KeyValueRow label="Borrow APR" value={fmtBps(borrowAPR)} mono />
      </KeyValueList>
    </SectionCard>
  )
}
