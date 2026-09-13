import type { LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

type Props = {
  icon?: LucideIcon
  title: string
  description?: string
  actionLabel?: string
  onAction?: () => void
  className?: string
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  actionLabel,
  onAction,
  className,
}: Props) {
  return (
    <div className={cn('py-6', className)}>
      {Icon ? (
        <Icon aria-hidden="true" className="mb-2 size-4 text-bone-3" strokeWidth={1.5} />
      ) : null}
      <p className="text-[13px] text-bone-2">{title}</p>
      {description ? (
        <p className="mt-1 max-w-prose text-xs leading-relaxed text-bone-3">{description}</p>
      ) : null}
      {actionLabel && onAction ? (
        <Button type="button" variant="outline" size="sm" className="mt-3" onClick={onAction}>
          {actionLabel}
        </Button>
      ) : null}
    </div>
  )
}
