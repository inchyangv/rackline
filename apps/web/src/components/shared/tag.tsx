import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export type TagTone = 'neutral' | 'ok' | 'warn' | 'err' | 'signal'

const toneClass: Record<TagTone, string> = {
  neutral: 'text-bone-2 border-rule-strong',
  ok: 'text-ok border-ok/40',
  warn: 'text-warn border-warn/40',
  err: 'text-err border-err/40',
  signal: 'text-signal border-signal/40',
}

type Props = {
  tone?: TagTone
  children: ReactNode
  className?: string
  title?: string
}

export function Tag({ tone = 'neutral', children, className, title }: Props) {
  return (
    <span
      title={title}
      className={cn(
        'inline-flex h-5 max-w-full shrink-0 items-center rounded-sm border px-1.5',
        // `font-sans` keeps tags sans-serif inside mono ledger cells.
        'font-sans text-[11px] font-medium whitespace-nowrap',
        toneClass[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}
