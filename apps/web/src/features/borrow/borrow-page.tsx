import { useEffect } from 'react'
import { useFacility } from '@/hooks/use-facility'
import { useApiStore } from '@/stores/api-store'
import { useWalletStore } from '@/stores/wallet-store'
import { BorrowDisclosure } from './borrow-disclosure'
import { DrawRepayPanel } from './draw-repay-panel'
import { FacilityHeader } from './facility-header'
import { FacilitySummary } from './facility-summary'
import { SetupPanel } from './setup-panel'
import { Statement } from './statement'

export function BorrowPage() {
  const viewed = useApiStore((s) => s.borrowerAddress)
  const setViewed = useApiStore((s) => s.setViewed)
  const walletAccount = useWalletStore((s) => s.walletAccount)
  const setGauge = useWalletStore((s) => s.setGauge)

  const facility = useFacility(viewed)

  // The mark's bottom rule reads principal/limit while this page is mounted.
  useEffect(() => {
    setGauge(facility.gauge)
  }, [facility.gauge, setGauge])
  useEffect(() => () => setGauge(null), [setGauge])

  // With no address there is nothing to show: the header carries the one line.
  const hasFacility = facility.state !== 'no-address'
  // Nothing to act on yet: setup leads, the action block follows it.
  const setupFirst = facility.state === 'not-registered' || facility.state === 'no-address'

  return (
    <div className="grid grid-cols-1 gap-x-12 py-8 lg:grid-cols-12 lg:grid-rows-[auto_1fr]">
      <h1 className="sr-only">Borrow — facility</h1>

      <div className="lg:col-span-7 lg:row-start-1">
        <FacilityHeader
          viewed={viewed}
          facility={facility}
          walletAccount={walletAccount}
          onView={setViewed}
        />
        {hasFacility ? (
          <>
            <FacilitySummary facility={facility} />
            <Statement address={viewed} decimals={facility.decimals} />
          </>
        ) : null}
      </div>

      <div className="mt-8 space-y-6 lg:col-span-5 lg:row-span-2 lg:row-start-1 lg:mt-0">
        {setupFirst ? (
          <>
            <SetupPanel facility={facility} viewed={viewed} onView={setViewed} />
            <DrawRepayPanel facility={facility} viewed={viewed} />
          </>
        ) : (
          <>
            <DrawRepayPanel facility={facility} viewed={viewed} />
            <SetupPanel facility={facility} viewed={viewed} onView={setViewed} />
          </>
        )}
      </div>

      {/* Last in DOM order so a phone reaches the action block before the prose;
          the grid puts it back under the left column from lg up. */}
      <BorrowDisclosure className="mt-8 lg:col-span-7 lg:row-start-2 lg:mt-0 lg:self-start" />
    </div>
  )
}
