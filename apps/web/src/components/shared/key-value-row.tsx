import type { ReactNode } from 'react'
import { LedgerRow } from './ledger'

type Props = {
  label: ReactNode
  value: ReactNode
  mono?: boolean
  pre?: boolean
  className?: string
}

/** Legacy alias for `LedgerRow` (kept for the unrouted admin/operations/proof tabs). */
export function KeyValueRow({ label, value, mono = false, pre = false, className }: Props) {
  return (
    <LedgerRow
      label={label}
      mono={mono}
      className={className}
      value={
        pre ? (
          <span className="block whitespace-pre-wrap break-words text-left">{value ?? '—'}</span>
        ) : (
          (value ?? '—')
        )
      }
    />
  )
}
