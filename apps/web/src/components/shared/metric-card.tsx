import { cn } from '@/lib/utils'
import { Skeleton } from '@/components/ui/skeleton'

type Tone = 'ok' | 'warn' | 'err' | ''

type Props = {
  label: string
  value: React.ReactNode
  hint?: string
  tone?: Tone
  small?: boolean
  loading?: boolean
}

const toneClass: Record<Tone, string> = {
  ok: 'text-success',
  warn: 'text-warning',
  err: 'text-destructive',
  '': '',
}

export function MetricCard({ label, value, hint, tone = '', small, loading }: Props) {
  return (
    <article className="rounded-xl border border-border/40 bg-gradient-to-br from-card to-card/60 p-3 shadow-inner">
      <div className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">
        {label}
      </div>
      {loading ? (
        <Skeleton className="mt-2 h-6 w-24" />
      ) : (
        <div
          className={cn(
            'mt-2 font-bold tracking-tight',
            small ? 'text-sm md:text-base' : 'text-base md:text-lg',
            toneClass[tone],
          )}
        >
          {value}
        </div>
      )}
      {hint && <div className="mt-1.5 text-[11px] text-muted-foreground/70">{hint}</div>}
    </article>
  )
}
