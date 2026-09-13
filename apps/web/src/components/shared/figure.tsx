import type { ReactNode } from 'react'

/**
 * Renders a formatted number so its group separators and decimal point are
 * kerned (see `.num .sep` in index.css). Use inside a `num` element.
 */
export function Figure({ children }: { children: string }): ReactNode {
  const parts = children.split(/([.,])/)
  return (
    <>
      {parts.map((part, i) =>
        part === '.' || part === ',' ? (
          <span key={i} className="sep">
            {part}
          </span>
        ) : (
          part
        ),
      )}
    </>
  )
}
