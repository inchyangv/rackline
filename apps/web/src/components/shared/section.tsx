import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

type Props = {
  eyebrow?: string
  title?: string
  description?: string
  aside?: ReactNode
  /** The one action block per page: ink-1 surface inside a hairline border. */
  raised?: boolean
  full?: boolean
  id?: string
  className?: string
  children: ReactNode
}

/** Sections stack on the page ground and are separated by hairlines. */
export function Section({
  eyebrow,
  title,
  description,
  aside,
  raised,
  full,
  id,
  className,
  children,
}: Props) {
  const hasHeader = Boolean(eyebrow || title || description || aside)

  return (
    <section
      id={id}
      className={cn(
        raised
          ? 'bg-ink-1 border border-rule rounded-lg p-5'
          : 'pt-6 pb-2 border-t border-rule first:border-t-0',
        full && 'col-span-full',
        className,
      )}
    >
      {hasHeader ? (
        <div className="mb-3 flex items-start justify-between gap-4">
          <div className="min-w-0">
            {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
            {title ? (
              <h2 className={cn('text-sm font-semibold text-bone', eyebrow && 'mt-1.5')}>
                {title}
              </h2>
            ) : null}
            {description ? <p className="mt-1 text-xs text-bone-3">{description}</p> : null}
          </div>
          {aside ? <div className="shrink-0">{aside}</div> : null}
        </div>
      ) : null}
      {children}
    </section>
  )
}
