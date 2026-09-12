import { useState, useEffect } from 'react'
import { ethers } from 'ethers'
import type { TabId } from '@/types'
import { Header } from './header'
import { WalletPanel } from './wallet-panel'
import { Footer } from './footer'
import { MetricsBar } from '@/components/shared/metrics-bar'
import { MetricCard } from '@/components/shared/metric-card'
import { useWalletStore } from '@/stores/wallet-store'
import { useApiStore } from '@/stores/api-store'
import { useManagerReads } from '@/hooks/use-manager-reads'
import { useBorrowerInfo } from '@/hooks/use-borrower-info'
import { useVaultInfo } from '@/hooks/use-vault-info'
import { DashboardTab } from '@/features/dashboard/dashboard-tab'
import { PoolTab } from '@/features/pool/pool-tab'
import { getLocalStorageString, setLocalStorageString } from '@/lib/storage'
import { STABLECOIN_SYMBOL } from '@/lib/constants'
import { getEvmTxExplorerUrl } from '@/lib/explorer'

export function AppShell() {
  const [tab, setTab] = useState<TabId>(() => {
    const v = getLocalStorageString('hashcredit_tab', 'dashboard')
    return v === 'dashboard' || v === 'pool'
      ? v
      : 'dashboard'
  })

  useEffect(() => {
    setLocalStorageString('hashcredit_tab', tab)
  }, [tab])

  const walletAccount = useWalletStore((s) => s.walletAccount)
  const txState = useWalletStore((s) => s.txState)
  const borrowerAddress = useApiStore((s) => s.borrowerAddress)
  const setBorrowerAddress = useApiStore((s) => s.setBorrowerAddress)
  const resetForDisconnect = useApiStore((s) => s.resetForDisconnect)

  // Set default borrower from wallet
  useEffect(() => {
    if (walletAccount) {
      if (!borrowerAddress) setBorrowerAddress(walletAccount)
      return
    }
    resetForDisconnect()
  }, [walletAccount, borrowerAddress, setBorrowerAddress, resetForDisconnect])

  const activeBorrower = walletAccount || ''

  const { stablecoin } = useManagerReads()
  const { availableCredit, currentDebt, stablecoinBalance, stablecoinDecimals, isLoading } =
    useBorrowerInfo(activeBorrower, stablecoin)

  // Vault info for Pool tab metrics
  const vault = useVaultInfo()
  const { totalAssets, borrowAPR: vaultAPR, myShares, myShareValue, isLoading: vaultLoading } = vault

  // Dashboard metrics
  const availableCreditDisplay =
    availableCredit === null
      ? '—'
      : `${ethers.formatUnits(availableCredit, stablecoinDecimals)} ${STABLECOIN_SYMBOL}`
  const stablecoinBalanceDisplay =
    stablecoinBalance === null
      ? '—'
      : `${ethers.formatUnits(stablecoinBalance, stablecoinDecimals)} ${STABLECOIN_SYMBOL}`
  const outstandingDebtDisplay =
    currentDebt === null
      ? '—'
      : `${ethers.formatUnits(currentDebt, stablecoinDecimals)} ${STABLECOIN_SYMBOL}`

  // Pool tab metrics
  const poolTvlDisplay =
    totalAssets === null ? '—' : `${ethers.formatUnits(totalAssets, 6)} ${STABLECOIN_SYMBOL}`
  const poolAprDisplay =
    vaultAPR === null ? '—' : `${(Number(vaultAPR) / 100).toFixed(2)}%`
  const mySharesDisplay =
    myShares === null ? '—' : ethers.formatUnits(myShares, 6)
  const myShareValueDisplay =
    myShareValue === null ? '—' : `${ethers.formatUnits(myShareValue, 6)} ${STABLECOIN_SYMBOL}`

  const txHash = 'hash' in txState ? txState.hash : undefined
  const txExplorerUrl = txHash ? getEvmTxExplorerUrl(txHash) : ''

  const txOverview =
    txState.status === 'idle' ? (
      'No transactions yet'
    ) : txState.status === 'signing' ? (
      `Signing: ${txState.label}`
    ) : txState.status === 'pending' ? (
      `Pending: ${txState.label}`
    ) : txState.status === 'confirmed' ? (
      txExplorerUrl ? (
        <a
          href={txExplorerUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 hover:underline"
        >
          Confirmed: {txState.label}
          <span className="text-[10px]">↗</span>
        </a>
      ) : (
        `Confirmed: ${txState.label}`
      )
    ) : (
      `Error: ${txState.label} — ${txState.message}`
    )

  const txOverviewTone =
    txState.status === 'confirmed'
      ? ('ok' as const)
      : txState.status === 'error'
        ? ('err' as const)
        : txState.status === 'pending'
          ? ('warn' as const)
          : ('' as const)

  return (
    <div className="mx-auto max-w-[1320px] px-4 py-5 sm:px-6 lg:px-8 relative z-[1]">
      {/* Chrome panel */}
      <div className="relative rounded-2xl border border-border/50 bg-gradient-to-br from-[rgba(12,19,41,0.94)] via-[rgba(14,24,54,0.85)] to-[rgba(16,34,52,0.9)] p-4 sm:p-5 shadow-[0_22px_44px_rgba(3,6,20,0.52),inset_0_1px_0_rgba(190,216,255,0.06)] overflow-hidden mb-4 animate-in fade-in slide-in-from-bottom-2 duration-500">
        {/* Top accent line */}
        <div className="absolute inset-x-0 top-0 h-0.5 bg-gradient-to-r from-primary/20 via-[rgba(88,122,232,0.9)] to-primary/20" />
        {/* Glow orb */}
        <div className="absolute -top-[120px] -right-[110px] w-[320px] h-[320px] rounded-full bg-[radial-gradient(circle,rgba(79,167,154,0.22)_0%,rgba(79,167,154,0)_68%)] pointer-events-none" />

        <div className="grid grid-cols-1 lg:grid-cols-[1.1fr_0.9fr] gap-4 items-stretch">
          <Header tab={tab} onTabChange={setTab} />
          <WalletPanel />
        </div>

        {/* Metrics bar — content changes per tab */}
        <MetricsBar>
          {tab === 'dashboard' ? (
            <>
              <MetricCard
                label="Available Credit"
                value={availableCreditDisplay}
                loading={isLoading}
              />
              <MetricCard
                label="Balance"
                value={stablecoinBalanceDisplay}
                loading={isLoading}
              />
              <MetricCard
                label="Outstanding Debt"
                value={outstandingDebtDisplay}
                loading={isLoading}
              />
            </>
          ) : (
            <>
              <MetricCard
                label="My Shares"
                value={mySharesDisplay}
                loading={vaultLoading}
              />
              <MetricCard
                label="My Value"
                value={myShareValueDisplay}
                loading={vaultLoading}
              />
              <MetricCard
                label="Pool TVL"
                value={poolTvlDisplay}
                loading={vaultLoading}
              />
              <MetricCard
                label="Borrow APR"
                value={poolAprDisplay}
                loading={vaultLoading}
              />
            </>
          )}
          <MetricCard label="Status" value={txOverview} tone={txOverviewTone} small />
        </MetricsBar>
      </div>

      {/* Tab content */}
      <main key={tab} className="grid grid-cols-1 md:grid-cols-2 gap-3.5 animate-in fade-in slide-in-from-bottom-1 duration-300">
        {tab === 'dashboard' && <DashboardTab />}
        {tab === 'pool' && <PoolTab />}
      </main>

      <Footer />
    </div>
  )
}
