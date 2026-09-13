import { Figure } from '@/components/shared/figure'
import { cn } from '@/lib/utils'

type Props = {
  /** Percentage, 0…100. `null` renders an empty track. */
  value: number | null
  label: string
  valueText?: string
  className?: string
}

export function Meter({ value, label, valueText, className }: Props) {
  const pct =
    value === null || !Number.isFinite(value) ? null : Math.min(100, Math.max(0, value))

  return (
    <div className={cn('flex items-center gap-3', className)}>
      <div
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct ?? undefined}
        aria-valuetext={valueText}
        className="h-1.5 min-w-0 flex-1 bg-ink-2"
      >
        {pct === null ? null : (
          // Floor a non-zero fill to a visible sliver: at 0.01% a bare
          // percentage width paints nothing and the track reads as a hairline.
          <div
            className="h-full bg-signal"
            style={{ width: pct > 0 ? `max(2px, ${pct}%)` : 0 }}
          />
        )}
      </div>
      {valueText ? <span className="num shrink-0 text-xs text-bone-2">
          <Figure>{valueText}</Figure>
        </span> : null}
    </div>
  )
}
