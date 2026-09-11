import { cn } from '@/lib/utils'

type Props = {
  children: React.ReactNode
  className?: string
}

export function MetricsBar({ children, className }: Props) {
  return (
    <div
      className={cn(
        'mt-3.5 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3',
        className,
      )}
    >
      {children}
    </div>
  )
}
