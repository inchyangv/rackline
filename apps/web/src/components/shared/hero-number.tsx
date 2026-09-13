import type { ReactNode } from 'react'
import { Figure } from '@/components/shared/figure'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

type Props = {
  label: string
  value: string
  unit?: string
  /** Exact, ungrouped value — shown as the native tooltip on the number. */
  exact?: string
  loading?: boolean
  sub?: ReactNode
  className?: string
}

/** The one hero number on a page. Everything else is a ledger row. */
export function HeroNumber({ label, value, unit, exact, loading, sub, className }: Props) {
  return (
    <div className={className}>
      <div className="text-xs text-bone-2">{label}</div>
      {loading ? (
        <Skeleton className="mt-2 h-14 w-64" />
      ) : (
        <div className="mt-2 flex flex-wrap items-baseline gap-2">
          <span
            title={exact}
            className={cn(
              'num font-medium text-[clamp(26px,10.5vw,36px)] sm:text-[56px]',
              'leading-none tracking-[-0.02em] text-bone',
            )}
          >
            <Figure>{value}</Figure>
          </span>
          {unit ? <span className="text-[13px] text-bone-2">{unit}</span> : null}
        </div>
      )}
      {sub ? <div className="mt-3 text-xs text-bone-3">{sub}</div> : null}
    </div>
  )
}
