import { useId } from 'react'
import { BRAND } from '@/lib/brand'
import { cn } from '@/lib/utils'
import { useWalletStore } from '@/stores/wallet-store'

/** Rules run from x=5 to x=21 — a 16-unit span inside the 24-unit box. */
const RULE_X = 5
const RULE_SPAN = 16
/** Width of the bottom rule when there is no gauge value to show. */
const FALLBACK_WIDTH = 8

function bottomRuleWidth(gauge: number | null | undefined): number {
  if (gauge === null || gauge === undefined || !Number.isFinite(gauge)) return FALLBACK_WIDTH
  const clamped = Math.min(1, Math.max(0, gauge))
  return Math.max(2, RULE_SPAN * clamped)
}

type MarkProps = {
  /** 0…1 — drives the width of the bottom rule. `null` renders the fallback width. */
  gauge?: number | null
  size?: number
  className?: string
}

/**
 * Spine plus three rules. The middle rule is signal: it sweeps while a
 * transaction is in flight and flashes once when one fails.
 */
export function Mark({ gauge = null, size = 24, className }: MarkProps) {
  const rawId = useId()
  const clipId = `mark-sweep-${rawId.replace(/[^a-zA-Z0-9_-]/g, '')}`
  const status = useWalletStore((s) => s.txState.status)
  const inFlight = status === 'signing' || status === 'pending'
  const failed = status === 'error'

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      aria-hidden="true"
      focusable="false"
      className={cn('shrink-0', className)}
    >
      <defs>
        <clipPath id={clipId}>
          <rect x={RULE_X} y="11" width={RULE_SPAN} height="2" />
        </clipPath>
      </defs>
      {/* spine */}
      <rect x="3" y="3" width="2" height="18" fill="var(--bone)" />
      {/* top rule */}
      <rect x={RULE_X} y="5" width={RULE_SPAN} height="2" fill="var(--bone)" />
      {/* signal rule */}
      {inFlight ? (
        <g clipPath={`url(#${clipId})`}>
          <rect
            x={RULE_X}
            y="11"
            width={RULE_SPAN}
            height="2"
            fill="var(--signal)"
            className="animate-sweep"
            style={{ transformBox: 'fill-box' }}
          />
        </g>
      ) : (
        <rect
          key={failed ? 'failed' : 'settled'}
          x={RULE_X}
          y="11"
          width={RULE_SPAN}
          height="2"
          fill="var(--signal)"
          className={failed ? 'animate-flash-err' : undefined}
        />
      )}
      {/* gauge rule */}
      <rect x={RULE_X} y="17" width={bottomRuleWidth(gauge)} height="2" fill="var(--bone)" />
    </svg>
  )
}

export function Wordmark({ className }: { className?: string }) {
  return <span className={cn('wordmark text-bone', className)}>{BRAND.wordmark}</span>
}

export function Logo({ gauge = null, className }: { gauge?: number | null; className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-2.5', className)}>
      {/* The mark's ink starts 3 units into its box; pull it back so the logo
          block aligns optically with the content column below it. */}
      <Mark gauge={gauge} className="-ms-[3px]" />
      <Wordmark />
    </span>
  )
}
