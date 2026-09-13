import type { ReactNode } from 'react'
import { Ledger } from './ledger'

type Props = {
  children: ReactNode
  className?: string
}

/** Legacy alias for `Ledger` (kept for the unrouted admin/operations/proof tabs). */
export function KeyValueList({ children, className }: Props) {
  return <Ledger className={className}>{children}</Ledger>
}
