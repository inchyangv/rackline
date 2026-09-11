import { cn } from '@/lib/utils'

type Props = {
  children: React.ReactNode
  className?: string
}

export function KeyValueList({ children, className }: Props) {
  return <div className={cn('grid gap-2', className)}>{children}</div>
}
