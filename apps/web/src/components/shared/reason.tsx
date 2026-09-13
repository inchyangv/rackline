import type { ComponentPropsWithoutRef, ReactNode } from 'react'
import { cn } from '@/lib/utils'

/** `id` and `role` pass through so a control can point `aria-describedby` here. */
type Props = ComponentPropsWithoutRef<'p'> & {
  children: ReactNode
  tone?: 'muted' | 'warn' | 'err'
  className?: string
}

/** One line of prose explaining why an action is unavailable. */
export function Reason({ children, tone = 'muted', className, ...rest }: Props) {
  return (
    <p
      {...rest}
      className={cn(
        'text-xs leading-relaxed',
        tone === 'warn' ? 'text-warn' : tone === 'err' ? 'text-err' : 'text-bone-3',
        className,
      )}
    >
      {children}
    </p>
  )
}
