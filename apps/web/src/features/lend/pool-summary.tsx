import { AddressDisplay } from '@/components/shared/address-display'
import { Figure } from '@/components/shared/figure'
import { HeroNumber } from '@/components/shared/hero-number'
import { Ledger, LedgerRow } from '@/components/shared/ledger'
import { Meter } from '@/components/shared/meter'
import { Money } from '@/components/shared/money'
import { Section } from '@/components/shared/section'
import { Tag } from '@/components/shared/tag'
import type { VaultInfo } from '@/hooks/use-vault-info'
import { STABLECOIN_SYMBOL } from '@/lib/constants'
import { exactAmount, formatAmount, formatBps } from '@/lib/format'
import { useConfigStore } from '@/stores/config-store'
import { sharePriceText } from './share-price'

type Props = {
  vault: VaultInfo
  decimals: number
}

/** Interest earned by the pool but not yet paid in: book value less cash and principal. */
function uncollectedInterest(
  totalAssets: bigint | null,
  cash: bigint | null,
  borrowed: bigint | null,
): bigint | null {
  if (totalAssets === null || cash === null || borrowed === null) return null
  const rest = totalAssets - cash - borrowed
  return rest > 0n ? rest : 0n
}

export function PoolSummary({ vault, decimals }: Props) {
  const vaultAddress = useConfigStore((s) => s.vaultAddress)
  const {
    totalAssets,
    totalBorrowed,
    availableLiquidity,
    totalShares,
    utilizationRate,
    borrowAPR,
    isLoading,
  } = vault

  const utilizationPct = utilizationRate === null ? null : Number(utilizationRate) / 100
  const utilizationLabel = formatBps(utilizationRate)
  const uncollected = uncollectedInterest(totalAssets, availableLiquidity, totalBorrowed)
  const price = sharePriceText(totalAssets, totalShares)

  const showHelper =
    utilizationRate !== null && totalBorrowed !== null && totalAssets !== null

  return (
    <Section>
      <HeroNumber
        label="Cash in pool"
        value={formatAmount(availableLiquidity, decimals)}
        exact={exactAmount(availableLiquidity, decimals)}
        unit={STABLECOIN_SYMBOL}
        loading={isLoading}
        sub={
          <>
            Principal on loan <Money value={totalBorrowed} decimals={decimals} /> · Utilization{' '}
            <span className="num">
              <Figure>{utilizationLabel}</Figure>
            </span>
          </>
        }
      />

      <div className="mt-6">
        <Meter value={utilizationPct} label="Utilization" valueText={utilizationLabel} />
        {showHelper ? (
          <p className="mt-2 max-w-prose text-xs leading-relaxed text-bone-3">
            At{' '}
            <span className="num">
              <Figure>{utilizationLabel}</Figure>
            </span>{' '}
            utilization, borrower interest accrues on{' '}
            <Money value={totalBorrowed} decimals={decimals} unit={null} /> of{' '}
            <Money value={totalAssets} decimals={decimals} /> (gross, before losses; not a
            forecast).
          </p>
        ) : null}
      </div>

      <Ledger className="mt-6">
        <LedgerRow
          label="Book value"
          title="Cash + principal on loan + interest accrued but uncollected"
          value={<Money value={totalAssets} decimals={decimals} />}
          loading={isLoading}
        />
        <LedgerRow
          label="Principal on loan"
          value={<Money value={totalBorrowed} decimals={decimals} />}
          loading={isLoading}
        />
        <LedgerRow
          label="Interest accrued, uncollected"
          value={<Money value={uncollected} decimals={decimals} />}
          loading={isLoading}
        />
        <LedgerRow
          label="Utilization"
          value={
            <span className="num">
              <Figure>{utilizationLabel}</Figure>
            </span>
          }
          mono={false}
          loading={isLoading}
        />
        <LedgerRow
          label="Borrower rate"
          mono={false}
          value={
            borrowAPR === null ? (
              '—'
            ) : (
              <>
                <span className="num">
                  <Figure>{formatBps(borrowAPR)}</Figure>
                </span>{' '}
                APR
              </>
            )
          }
          action={<Tag tone="neutral">Set by pool admin · may change</Tag>}
          loading={isLoading}
        />
        <LedgerRow
          label="Share price"
          mono={false}
          value={
            price === null ? (
              '—'
            ) : (
              <>
                <span className="num">
                  <Figure>{price}</Figure>
                </span>{' '}
                <span className="font-sans text-bone-2">{STABLECOIN_SYMBOL}/share</span>
              </>
            )
          }
          loading={isLoading}
        />
        <LedgerRow
          label="Total shares"
          value={<Money value={totalShares} decimals={decimals} unit={null} />}
          loading={isLoading}
        />
        <LedgerRow
          label="Vault contract"
          mono={false}
          value={<AddressDisplay address={vaultAddress} explorer label="vault" />}
        />
      </Ledger>
    </Section>
  )
}
