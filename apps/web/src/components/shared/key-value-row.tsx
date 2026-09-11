import { cn } from '@/lib/utils'

type Props = {
  label: string
  value: React.ReactNode
  mono?: boolean
  pre?: boolean
  className?: string
}

export function KeyValueRow({ label, value, mono = false, pre = false, className }: Props) {
  return (
    <div
      className={cn(
        'grid grid-cols-[minmax(122px,150px)_minmax(0,1fr)] gap-2.5 items-start',
        'rounded-xl border border-border/40 bg-gradient-to-br from-card/80 to-card/60 px-3 py-2.5',
        className,
      )}
    >
      <div className="text-xs text-muted-foreground">{label}</div>
      <div
        className={cn(
          'text-xs leading-relaxed',
          mono && 'font-mono',
          pre && 'whitespace-pre-wrap break-words',
        )}
      >
        {value ?? '—'}
      </div>
    </div>
  )
}
