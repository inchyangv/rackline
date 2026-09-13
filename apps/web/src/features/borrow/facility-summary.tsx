import { Figure } from '@/components/shared/figure'
import { HeroNumber } from '@/components/shared/hero-number'
import { Ledger, LedgerRow } from '@/components/shared/ledger'
import { Money } from '@/components/shared/money'
import { Section } from '@/components/shared/section'
import { Tag } from '@/components/shared/tag'
import type { Facility } from '@/hooks/use-facility'
import { STABLECOIN_SYMBOL } from '@/lib/constants'
import { exactAmount, formatAmount, formatBps } from '@/lib/format'

type Props = {
  facility: Facility
}

export function FacilitySummary({ facility }: Props) {
  const { decimals } = facility
  const pending = (value: bigint | null) => facility.isLoading && value === null

  return (
    <Section>
      <HeroNumber
        label="Drawable now"
        value={formatAmount(facility.drawableNow, decimals)}
        unit={STABLECOIN_SYMBOL}
        exact={exactAmount(facility.drawableNow, decimals)}
        loading={pending(facility.drawableNow)}
        sub={
          <>
            Undrawn limit <Money value={facility.undrawnLimit} decimals={decimals} /> · Pool
            liquidity <Money value={facility.poolLiquidity} decimals={decimals} />
          </>
        }
      />

      <Ledger className="mt-8">
        <LedgerRow
          label="Principal"
          mono={false}
          loading={pending(facility.principal)}
          value={<Money value={facility.principal} decimals={decimals} />}
        />
        <LedgerRow
          label="Accrued interest"
          mono={false}
          loading={pending(facility.accruedInterest)}
          value={<Money value={facility.accruedInterest} decimals={decimals} />}
        />
        <LedgerRow
          label="Total owed"
          mono={false}
          title="Principal + accrued interest as of the last block"
          loading={pending(facility.totalOwed)}
          value={<Money value={facility.totalOwed} decimals={decimals} />}
        />
        <LedgerRow
          label="Credit limit"
          mono={false}
          loading={pending(facility.creditLimit)}
          value={<Money value={facility.creditLimit} decimals={decimals} />}
        />
        <LedgerRow
          label="Borrow rate"
          mono={false}
          loading={pending(facility.borrowAprBps)}
          value={
            <>
              <span className="num">
                <Figure>{formatBps(facility.borrowAprBps)}</Figure>
              </span>{' '}
              APR
            </>
          }
          action={<Tag tone="neutral">Set by pool admin · may change</Tag>}
        />
        <LedgerRow label="Repayment order" mono={false} value="Interest, then principal" />
        <LedgerRow label="Maturity" mono={false} value="None" />
        <LedgerRow
          label="Pool liquidity"
          mono={false}
          loading={pending(facility.poolLiquidity)}
          value={<Money value={facility.poolLiquidity} decimals={decimals} />}
        />
      </Ledger>
    </Section>
  )
}
