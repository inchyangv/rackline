import { cn } from '@/lib/utils'

type Props = {
  label: React.ReactNode
  value: React.ReactNode
  mono?: boolean
  pre?: boolean
  className?: string
}

export function KeyValueRow({ label, value, mono = false, pre = false, className }: Props) {
  return (
    <div
      className={cn(
        'grid grid-cols-[minmax(90px,130px)_minmax(0,1fr)] gap-2.5 items-start',
        'border-b border-border/25 last:border-b-0 py-2.5',
        className,
      )}
    >
      <div className="text-xs text-muted-foreground leading-relaxed">{label}</div>
      <div
        className={cn(
          'text-sm leading-relaxed',
          mono && 'font-mono',
          pre && 'whitespace-pre-wrap break-words',
        )}
      >
        {value ?? '—'}
      </div>
    </div>
  )
}
