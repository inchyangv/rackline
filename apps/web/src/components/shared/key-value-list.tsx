import { cn } from '@/lib/utils'

type Props = {
  children: React.ReactNode
  className?: string
}

export function KeyValueList({ children, className }: Props) {
  return (
    <div
      className={cn(
        'rounded-lg border border-border/30 bg-card/40 px-3',
        className,
      )}
    >
      {children}
    </div>
  )
}
