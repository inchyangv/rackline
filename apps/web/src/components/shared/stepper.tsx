import { Check } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

export type StepState = 'done' | 'current' | 'todo' | 'unavailable' | 'attention'

const glyphClass: Record<StepState, string> = {
  done: 'text-ok border-ok/40',
  current: 'text-bone border-bone',
  todo: 'text-bone-3 border-rule-strong',
  unavailable: 'text-bone-3 border-rule',
  attention: 'text-warn border-warn/40',
}

/** Read out before the title so the glyph never carries state on its own. */
const stateLabel: Record<StepState, string> = {
  done: 'done',
  current: 'current',
  todo: 'not started',
  unavailable: 'not available',
  attention: 'needs attention',
}

type StepperProps = {
  children: ReactNode
  className?: string
}

export function Stepper({ children, className }: StepperProps) {
  return <ol className={cn('relative', className)}>{children}</ol>
}

type StepProps = {
  index: number
  state: StepState
  title: string
  helper?: ReactNode
  meta?: ReactNode
  children?: ReactNode
}

export function Step({ index, state, title, helper, meta, children }: StepProps) {
  const showChildren =
    Boolean(children) && (state === 'current' || state === 'attention' || state === 'done')

  return (
    <li className="group relative pl-8 pb-6 last:pb-0">
      <span
        aria-hidden="true"
        className="absolute top-6 bottom-1 left-[9px] w-px bg-rule group-last:hidden"
      />
      <span
        aria-hidden="true"
        className={cn(
          'absolute top-0 left-0 inline-flex size-5 items-center justify-center',
          'num rounded-sm border text-[11px]',
          glyphClass[state],
        )}
      >
        {state === 'done' ? (
          <Check className="size-3" strokeWidth={1.5} />
        ) : state === 'unavailable' ? (
          '—'
        ) : (
          index
        )}
      </span>
      <div className="flex items-baseline justify-between gap-3">
        <span
          className={cn(
            'text-sm font-medium',
            state === 'unavailable' ? 'text-bone-3' : 'text-bone',
          )}
        >
          <span className="sr-only">{`Step ${index}, ${stateLabel[state]}: `}</span>
          {title}
        </span>
        {meta ? <span className="shrink-0">{meta}</span> : null}
      </div>
      {helper ? <div className="mt-0.5 text-xs leading-relaxed text-bone-3">{helper}</div> : null}
      {showChildren ? <div className="mt-3">{children}</div> : null}
    </li>
  )
}
