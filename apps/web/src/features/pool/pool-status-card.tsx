import { ethers } from 'ethers'
import { ExternalLink } from 'lucide-react'
import { SectionCard } from '@/components/shared/section-card'
import { KeyValueList } from '@/components/shared/key-value-list'
import { KeyValueRow } from '@/components/shared/key-value-row'
import { Skeleton } from '@/components/ui/skeleton'
import { useConfigStore } from '@/stores/config-store'
import { shortAddr } from '@/lib/format'
import { STABLECOIN_SYMBOL } from '@/lib/constants'
import type { VaultInfo } from '@/hooks/use-vault-info'

const DECIMALS = 6
const EXPLORER_BASE = 'https://testnet-explorer.hsk.xyz'

type Props = {
  vault: VaultInfo
}

export function PoolStatusCard({ vault }: Props) {
  const vaultAddress = useConfigStore((s) => s.vaultAddress)
  const { totalAssets, totalBorrowed, availableLiquidity, utilizationRate, borrowAPR, isLoading } =
    vault

  function fmtAmount(val: bigint | null) {
    if (isLoading) return <Skeleton className="h-4 w-32" />
    if (val === null) return '—'
    return `${ethers.formatUnits(val, DECIMALS)} ${STABLECOIN_SYMBOL}`
  }

  function fmtBps(val: bigint | null) {
    if (isLoading) return <Skeleton className="h-4 w-20" />
    if (val === null) return '—'
    return `${(Number(val) / 100).toFixed(2)}%`
  }

  const explorerUrl = vaultAddress
    ? `${EXPLORER_BASE}/address/${vaultAddress}`
    : null

  return (
    <SectionCard title="Pool Status" description="Current lending pool metrics">
      <div className="mb-3 rounded-lg border border-border/30 bg-secondary/20 px-3 py-2 text-xs text-muted-foreground">
        Deposited {STABLECOIN_SYMBOL} is lent to SPV-verified BTC miners at a fixed APR.
        Depositors earn yield as borrowers repay interest.
        Share value grows over time as the pool accumulates interest.
      </div>
      <KeyValueList>
        <KeyValueRow
          label="Vault Contract"
          value={
            vaultAddress && explorerUrl ? (
              <a
                href={explorerUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-primary hover:underline"
              >
                {shortAddr(vaultAddress)}
                <ExternalLink className="h-3 w-3" />
              </a>
            ) : '—'
          }
          mono
        />
        <KeyValueRow label="Total Pool Assets" value={fmtAmount(totalAssets)} mono />
        <KeyValueRow label="Total Borrowed" value={fmtAmount(totalBorrowed)} mono />
        <KeyValueRow label="Available Liquidity" value={fmtAmount(availableLiquidity)} mono />
        <KeyValueRow label="Utilization Rate" value={fmtBps(utilizationRate)} mono />
        <KeyValueRow label="Borrow APR" value={fmtBps(borrowAPR)} mono />
      </KeyValueList>
    </SectionCard>
  )
}
