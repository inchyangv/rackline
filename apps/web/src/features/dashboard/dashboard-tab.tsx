import { BorrowerCard } from './borrower-card'
import { ProtocolStatusCard } from './protocol-status-card'
import { ClaimSection } from './claim-section'
import { AdminSection } from '@/features/admin/admin-tab'

export function DashboardTab() {
  return (
    <>
      <BorrowerCard />
      <ProtocolStatusCard />
      <ClaimSection />
      <AdminSection />
    </>
  )
}
