import { Disclosure } from '@/components/shared/disclosure'
import { Section } from '@/components/shared/section'

const ITEMS = [
  'Loans in this deployment are unsecured revolving credit to borrowers registered by proving a Bitcoin testnet payout address. No settlement-revenue assignment, escrow, or equipment security is in place.',
  'Deposits fund draws by registered borrowers.',
  'Share price includes interest that has accrued but not been paid, and outstanding principal at face value.',
  'This deployment has no loss-recognition mechanism: if a borrower does not repay, the shortfall is not reflected in share price and may not be recoverable.',
  'Returns are not fixed and not guaranteed.',
  'Withdrawals are limited to cash in the pool.',
  'Testnet tokens have no value.',
]

export function LendDisclosure() {
  return (
    <Section>
      <Disclosure title="What you are funding" items={ITEMS} />
    </Section>
  )
}
