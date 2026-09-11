import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import type { TxState } from '@/types'

type Props = {
  txState: TxState
  className?: string
}

export function TxStatusPill({ txState, className }: Props) {
  if (txState.status === 'idle') {
    return (
      <Badge variant="outline" className={cn('text-muted-foreground', className)}>
        No transactions yet
      </Badge>
    )
  }

  if (txState.status === 'signing') {
    return (
      <Badge variant="outline" className={cn('border-primary/40 text-primary animate-pulse', className)}>
        Signing: {txState.label}
      </Badge>
    )
  }

  if (txState.status === 'pending') {
    return (
      <Badge variant="outline" className={cn('border-warning/40 text-warning animate-pulse', className)}>
        Pending: {txState.label}
        <span className="ml-1 font-mono text-[10px]">{txState.hash.slice(0, 10)}…</span>
      </Badge>
    )
  }

  if (txState.status === 'confirmed') {
    return (
      <Badge variant="outline" className={cn('border-success/40 text-success', className)}>
        Confirmed: {txState.label}
        <span className="ml-1 font-mono text-[10px]">{txState.hash.slice(0, 10)}…</span>
      </Badge>
    )
  }

  return (
    <Badge variant="destructive" className={className}>
      Error: {txState.label} — {txState.message}
    </Badge>
  )
}
