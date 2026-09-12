import { cn } from '@/lib/utils'

type Props = {
  children: React.ReactNode
  className?: string
}

export function MetricsBar({ children, className }: Props) {
  return (
    <div
      className={cn(
        'mt-3.5 overflow-x-auto',
        className,
      )}
    >
      <div className="flex sm:grid sm:grid-cols-2 lg:grid-cols-4 gap-3 min-w-max sm:min-w-0">
        {children}
      </div>
    </div>
  )
}
