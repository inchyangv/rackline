import { BorrowerCard } from './borrower-card'
import { ManagerReadCard } from './manager-read-card'
import { CheckpointReadCard } from './checkpoint-read-card'
import { SpvVerifierReadCard } from './spv-verifier-read-card'
import { DemoWalletsCard } from './demo-wallets-card'
import { BtcProofTimeline } from './btc-proof-timeline'

export function DashboardTab() {
  return (
    <>
      <BorrowerCard />
      <ManagerReadCard />
      <CheckpointReadCard />
      <SpvVerifierReadCard />
      <DemoWalletsCard />
      <BtcProofTimeline />
    </>
  )
}
