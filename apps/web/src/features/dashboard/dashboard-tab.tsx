import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { BorrowerCard } from './borrower-card'
import { ClaimSection } from './claim-section'
import { ProtocolStatusCard } from './protocol-status-card'

export function DashboardTab() {
  const [showProtocol, setShowProtocol] = useState(false)

  return (
    <>
      <BorrowerCard />
      <ClaimSection />
      <div className="col-span-full">
        <button
          className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors mb-2"
          onClick={() => setShowProtocol((v) => !v)}
          aria-expanded={showProtocol}
        >
          {showProtocol ? (
            <ChevronDown className="h-3.5 w-3.5" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5" />
          )}
          Protocol Details
        </button>
        {showProtocol && <ProtocolStatusCard />}
      </div>
    </>
  )
}
