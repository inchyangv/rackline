import type { ReactNode } from 'react'
import { Section } from './section'

type Props = {
  title: string
  description?: string
  full?: boolean
  className?: string
  children: ReactNode
}

/** Legacy alias for a raised `Section` (kept for the unrouted feature tabs). */
export function SectionCard({ title, description, full, className, children }: Props) {
  return (
    <Section raised title={title} description={description} full={full} className={className}>
      {children}
    </Section>
  )
}
