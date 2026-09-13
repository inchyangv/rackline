import { useEffect } from 'react'
import { useVaultInfo } from '@/hooks/use-vault-info'
import { useWalletStore } from '@/stores/wallet-store'
import { DepositWithdrawPanel } from './deposit-withdraw-panel'
import { LendDisclosure } from './lend-disclosure'
import { PoolHeader } from './pool-header'
import { PoolSummary } from './pool-summary'
import { PositionPanel } from './position-panel'
import { usePoolDecimals } from './use-pool-decimals'

export function LendPage() {
  const vault = useVaultInfo()
  const decimals = usePoolDecimals(vault.asset)
  const setGauge = useWalletStore((s) => s.setGauge)

  const { utilizationRate } = vault

  // The mark's gauge rule reads pool utilization while this page is the one on
  // screen — published from here so the shell does not read the vault twice.
  useEffect(() => {
    setGauge(utilizationRate === null ? null : Number(utilizationRate) / 10_000)
  }, [utilizationRate, setGauge])

  useEffect(() => () => setGauge(null), [setGauge])

  return (
    <div className="grid grid-cols-1 gap-x-12 py-8 lg:grid-cols-12 lg:grid-rows-[auto_1fr]">
      <h1 className="sr-only">Lend — pool</h1>

      <div className="min-w-0 lg:col-span-7 lg:row-start-1">
        <PoolHeader />
        <PoolSummary vault={vault} decimals={decimals} />
        <PositionPanel vault={vault} decimals={decimals} />
      </div>

      <div className="mt-8 min-w-0 lg:col-span-5 lg:row-span-2 lg:row-start-1 lg:mt-0">
        <DepositWithdrawPanel vault={vault} decimals={decimals} />
      </div>

      {/* Last in DOM so a phone reaches the action block before the prose; the
          row placement puts it back under the left column on desktop. */}
      <div className="min-w-0 lg:col-span-7 lg:row-start-2 lg:self-start">
        <LendDisclosure />
      </div>
    </div>
  )
}
