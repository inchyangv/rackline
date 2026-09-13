import { cn } from '@/lib/utils'

type Props = {
  title: string
  items: string[]
  className?: string
}

/** Plain-language terms. Numbered, never collapsed behind a toggle. */
export function Disclosure({ title, items, className }: Props) {
  return (
    <div className={cn('max-w-prose', className)}>
      <h3 className="eyebrow">{title}</h3>
      <ol className="mt-3 space-y-2">
        {items.map((item, i) => (
          <li key={i} className="grid grid-cols-[1.75rem_minmax(0,1fr)] gap-1">
            <span aria-hidden="true" className="num text-xs text-bone-3">
              {String(i + 1).padStart(2, '0')}
            </span>
            <span className="text-xs leading-relaxed text-bone-2">{item}</span>
          </li>
        ))}
      </ol>
    </div>
  )
}
