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

export function EmptyState({ icon: Icon, title, description, actionLabel, onAction, className }: Props) {
  return (
    <div className={cn('flex flex-col items-center justify-center py-8 text-center', className)}>
      {Icon && <Icon className="h-10 w-10 text-muted-foreground/50 mb-3" />}
      <h3 className="text-sm font-semibold text-muted-foreground">{title}</h3>
      {description && (
        <p className="mt-1 text-xs text-muted-foreground/70 max-w-[280px]">{description}</p>
      )}
      {actionLabel && onAction && (
        <Button variant="secondary" size="sm" className="mt-4" onClick={onAction}>
          {actionLabel}
        </Button>
      )}
    </div>
  )
}
