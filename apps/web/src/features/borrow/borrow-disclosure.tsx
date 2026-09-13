import { Disclosure } from '@/components/shared/disclosure'
import { Section } from '@/components/shared/section'

const ITEMS = [
  'Interest accrues continuously at the pool’s current rate, which the administrator may change; a change applies to interest not yet settled.',
  'Any amount may be repaid at any time; repayments settle accrued interest first, then principal.',
  'Each new draw adds accrued interest to principal before the draw is applied.',
  'There is no maturity date, minimum payment, or due date in this deployment.',
  'The limit may be recomputed or frozen by the administrator; if debt exceeds the limit, new draws stop but no repayment is forced.',
  'The facility remains open after full repayment.',
]

export function BorrowDisclosure({ className }: { className?: string }) {
  return (
    <Section className={className}>
      <Disclosure title="How repayment works" items={ITEMS} />
    </Section>
  )
}
