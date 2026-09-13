import type { ReactNode } from 'react'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

type LedgerProps = {
  children: ReactNode
  className?: string
}

export function Ledger({ children, className }: LedgerProps) {
  return <dl className={cn('divide-y divide-rule', className)}>{children}</dl>
}

export type LedgerTone = 'default' | 'ok' | 'warn' | 'err' | 'muted'

const toneClass: Record<LedgerTone, string> = {
  default: 'text-bone',
  ok: 'text-ok',
  warn: 'text-warn',
  err: 'text-err',
  muted: 'text-bone-3',
}

type LedgerRowProps = {
  label: ReactNode
  value: ReactNode
  hint?: ReactNode
  title?: string
  mono?: boolean
  tone?: LedgerTone
  loading?: boolean
  action?: ReactNode
  className?: string
}

export function LedgerRow({
  label,
  value,
  hint,
  title,
  mono = true,
  tone = 'default',
  loading,
  action,
  className,
}: LedgerRowProps) {
  return (
    <div
      title={title}
      className={cn(
        'grid grid-cols-[minmax(120px,1fr)_minmax(0,1fr)] items-baseline gap-4 min-h-9 py-2',
        className,
      )}
    >
      <dt className="text-[13px] text-bone-2">
        {label}
        {hint ? <span className="mt-0.5 block text-xs text-bone-3">{hint}</span> : null}
      </dt>
      <dd
        className={cn(
          'min-w-0 text-right text-[13px]',
          toneClass[tone],
          // `break-words` only on bare mono cells: an address or hash still
          // breaks as a last resort, but `mUSDT` is never split mid-token.
          mono && (action ? 'num' : 'num break-words'),
        )}
      >
        {loading ? (
          <Skeleton className="ml-auto h-4 w-24" />
        ) : action ? (
          // The value and its tag wrap onto a second line instead of pushing
          // the value column past the page.
          <span className="flex flex-wrap items-baseline justify-end gap-x-2 gap-y-1">
            <span className="whitespace-nowrap">{value}</span>
            {action}
          </span>
        ) : (
          value
        )}
      </dd>
    </div>
  )
}
