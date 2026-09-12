import { ethers } from 'ethers'
import { CheckCircle2, Circle } from 'lucide-react'
import { SectionCard } from '@/components/shared/section-card'
import { cn } from '@/lib/utils'
import { KeyValueList } from '@/components/shared/key-value-list'
import { KeyValueRow } from '@/components/shared/key-value-row'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useApiStore } from '@/stores/api-store'
import { useWalletStore } from '@/stores/wallet-store'
import { useConfigStore } from '@/stores/config-store'
import { useManagerReads } from '@/hooks/use-manager-reads'
import { useBorrowerInfo } from '@/hooks/use-borrower-info'
import { useVaultInfo } from '@/hooks/use-vault-info'
import { sendContractTx } from '@/stores/tx-store'
import { HashCreditManagerAbi, Erc20Abi } from '@/lib/abis'
import { STABLECOIN_SYMBOL } from '@/lib/constants'
import { toast } from 'sonner'

export function BorrowerCard() {
  const borrowerAddress = useApiStore((s) => s.borrowerAddress)
  const setBorrowerAddress = useApiStore((s) => s.setBorrowerAddress)
  const borrowAmount = useApiStore((s) => s.borrowAmount)
  const setBorrowAmount = useApiStore((s) => s.setBorrowAmount)
  const repayAmount = useApiStore((s) => s.repayAmount)
  const setRepayAmount = useApiStore((s) => s.setRepayAmount)
  const approveAmount = useApiStore((s) => s.approveAmount)
  const setApproveAmount = useApiStore((s) => s.setApproveAmount)
  const walletAccount = useWalletStore((s) => s.walletAccount)
  const managerAddress = useConfigStore((s) => s.managerAddress)
  const { stablecoin } = useManagerReads()
  const {
    availableCredit,
    borrowerInfo,
    stablecoinDecimals,
    stablecoinBalance,
    currentDebt,
    accruedInterest,
    isLoading,
  } = useBorrowerInfo(borrowerAddress, stablecoin)
  const { borrowAPR } = useVaultInfo()

  // Determine if borrow should be disabled (unregistered or no credit)
  const borrowerStatus = typeof borrowerInfo?.status === 'bigint' ? Number(borrowerInfo.status) : 0
  const creditLimit = typeof borrowerInfo?.creditLimit === 'bigint' ? borrowerInfo.creditLimit : 0n
  const isBorrowDisabled = !borrowerInfo || borrowerStatus === 0 || creditLimit === 0n
  const aprDisplay = borrowAPR !== null ? `${(Number(borrowAPR) / 100).toFixed(2)}%` : '—'

  // BTC connection status
  const ZERO_BYTES32 = '0x0000000000000000000000000000000000000000000000000000000000000000'
  const btcPayoutKeyHash =
    typeof borrowerInfo?.btcPayoutKeyHash === 'string' ? borrowerInfo.btcPayoutKeyHash : ZERO_BYTES32
  const isBtcLinked = btcPayoutKeyHash !== ZERO_BYTES32

  async function doBorrow() {
    const amount = ethers.parseUnits(borrowAmount || '0', stablecoinDecimals)
    toast.promise(
      sendContractTx('borrow', managerAddress, HashCreditManagerAbi, (c) => c.borrow(amount)),
      { loading: 'Borrowing...', success: 'Borrow confirmed!', error: 'Borrow failed' },
    )
  }

  async function approveStablecoin() {
    const amount = ethers.parseUnits(approveAmount || '0', stablecoinDecimals)
    toast.promise(
      sendContractTx('approve', stablecoin, Erc20Abi, (c) => c.approve(managerAddress, amount)),
      { loading: 'Approving...', success: 'Approval confirmed!', error: 'Approval failed' },
    )
  }

  async function doRepay() {
    const amount = ethers.parseUnits(repayAmount || '0', stablecoinDecimals)
    toast.promise(
      sendContractTx('repay', managerAddress, HashCreditManagerAbi, (c) => c.repay(amount)),
      { loading: 'Repaying...', success: 'Repay confirmed!', error: 'Repay failed' },
    )
  }

  function handleMaxBorrow() {
    if (availableCredit !== null && availableCredit > 0n) {
      setBorrowAmount(ethers.formatUnits(availableCredit, stablecoinDecimals))
    }
  }

  function handleMaxRepay() {
    if (currentDebt !== null && currentDebt > 0n) {
      setRepayAmount(ethers.formatUnits(currentDebt, stablecoinDecimals))
    }
  }

  const onboardingDone = !!walletAccount && isBtcLinked

  return (
    <>
      {/* Onboarding progress — shown until all steps complete */}
      {!onboardingDone && (
        <div className="col-span-full rounded-xl border border-primary/20 bg-primary/5 px-4 py-3">
          <p className="text-xs font-semibold text-foreground/80 mb-2.5">Get started</p>
          <div className="flex items-center gap-2">
            {[
              { label: 'Connect Wallet', done: !!walletAccount },
              { label: 'Link BTC Wallet', done: isBtcLinked },
              { label: 'Start Borrowing', done: false },
            ].map((step, i, arr) => (
              <>
                <div key={step.label} className="flex flex-col items-center gap-1 min-w-0">
                  {step.done ? (
                    <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                  ) : (
                    <Circle
                      className={cn(
                        'h-4 w-4',
                        i === arr.findIndex((s) => !s.done)
                          ? 'text-primary'
                          : 'text-muted-foreground/40',
                      )}
                    />
                  )}
                  <span
                    className={cn(
                      'text-[10px] text-center leading-tight',
                      step.done
                        ? 'text-emerald-400'
                        : i === arr.findIndex((s) => !s.done)
                          ? 'text-foreground/80 font-medium'
                          : 'text-muted-foreground/50',
                    )}
                  >
                    {step.label}
                  </span>
                </div>
                {i < arr.length - 1 && (
                  <div key={`line-${i}`} className="flex-1 h-px bg-border/30 mb-4" />
                )}
              </>
            ))}
          </div>
        </div>
      )}

      {/* Credit Overview — read-only */}
      <SectionCard title="Credit Overview">
        <div className="space-y-3">
          <div>
            <Label className="text-[11px] uppercase tracking-wider">Wallet Address</Label>
            <Input
              value={borrowerAddress}
              onChange={(e) => setBorrowerAddress(e.target.value)}
              placeholder="0x..."
              className="mt-1 font-mono text-xs"
            />
          </div>

          <KeyValueList>
            <KeyValueRow
              label="Available Credit"
              value={
                isLoading ? (
                  <Skeleton className="h-4 w-32" />
                ) : availableCredit === null ? (
                  '—'
                ) : (
                  `${ethers.formatUnits(availableCredit, stablecoinDecimals)} ${STABLECOIN_SYMBOL}`
                )
              }
              mono
            />
            <KeyValueRow
              label="Balance"
              value={
                isLoading ? (
                  <Skeleton className="h-4 w-32" />
                ) : stablecoinBalance === null ? (
                  '—'
                ) : (
                  `${ethers.formatUnits(stablecoinBalance, stablecoinDecimals)} ${STABLECOIN_SYMBOL}`
                )
              }
              mono
            />
            <KeyValueRow
              label="Outstanding Debt"
              value={
                isLoading ? (
                  <Skeleton className="h-4 w-32" />
                ) : currentDebt === null ? (
                  '—'
                ) : (
                  `${ethers.formatUnits(currentDebt, stablecoinDecimals)} ${STABLECOIN_SYMBOL}`
                )
              }
              mono
            />
            <KeyValueRow
              label="Accrued Interest"
              value={
                isLoading ? (
                  <Skeleton className="h-4 w-32" />
                ) : accruedInterest === null ? (
                  '—'
                ) : (
                  `${ethers.formatUnits(accruedInterest, stablecoinDecimals)} ${STABLECOIN_SYMBOL}`
                )
              }
              mono
            />
            <KeyValueRow
              label="Borrow APR"
              value={isLoading ? <Skeleton className="h-4 w-20" /> : aprDisplay}
              mono
            />
            <KeyValueRow
              label="BTC Wallet"
              value={
                isLoading ? (
                  <Skeleton className="h-4 w-24" />
                ) : !borrowerInfo ? (
                  '—'
                ) : isBtcLinked ? (
                  <span className="text-emerald-400">Linked</span>
                ) : (
                  <span className="text-amber-400">Not linked</span>
                )
              }
            />
          </KeyValueList>
        </div>
      </SectionCard>

      {/* Actions */}
      <SectionCard title="Actions" description="Borrow and repay against your credit line">
        <div className="space-y-4">
          {isBorrowDisabled && (
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3">
              <p className="text-xs text-amber-200 font-medium">BTC wallet not linked</p>
              <p className="text-xs text-muted-foreground mt-1">
                Link your BTC wallet in the &quot;Link BTC Wallet&quot; section to enable
                borrowing.
              </p>
            </div>
          )}

          {/* Borrow */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <Label className="text-[11px] uppercase tracking-wider">
                Borrow
                <span className="ml-2 text-muted-foreground font-normal normal-case tracking-normal">
                  APR {aprDisplay}
                </span>
              </Label>
              <Button
                variant="ghost"
                size="xs"
                className="text-[11px] text-primary"
                onClick={handleMaxBorrow}
                disabled={!walletAccount || availableCredit === null || availableCredit === 0n}
              >
                Max
              </Button>
            </div>
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Input
                  value={borrowAmount}
                  onChange={(e) => setBorrowAmount(e.target.value)}
                  placeholder="0.00"
                  className="font-mono text-xs pr-16"
                  disabled={isBorrowDisabled}
                />
                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground pointer-events-none">
                  {STABLECOIN_SYMBOL}
                </span>
              </div>
              <Button
                size="sm"
                onClick={() => void doBorrow()}
                disabled={!walletAccount || isBorrowDisabled}
              >
                Borrow
              </Button>
            </div>
          </div>

          {/* Approve Spending */}
          <div>
            <Label className="text-[11px] uppercase tracking-wider">Approve Spending</Label>
            <div className="flex gap-2 mt-1">
              <div className="relative flex-1">
                <Input
                  value={approveAmount}
                  onChange={(e) => setApproveAmount(e.target.value)}
                  placeholder="0.00"
                  className="font-mono text-xs pr-16"
                />
                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground pointer-events-none">
                  {STABLECOIN_SYMBOL}
                </span>
              </div>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => void approveStablecoin()}
                disabled={!walletAccount}
              >
                Approve
              </Button>
            </div>
          </div>

          {/* Repay */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <Label className="text-[11px] uppercase tracking-wider">
                Repay
                {currentDebt !== null && currentDebt > 0n && (
                  <span className="ml-2 text-muted-foreground font-normal normal-case tracking-normal">
                    Debt: {ethers.formatUnits(currentDebt, stablecoinDecimals)} {STABLECOIN_SYMBOL}
                  </span>
                )}
              </Label>
              <Button
                variant="ghost"
                size="xs"
                className="text-[11px] text-primary"
                onClick={handleMaxRepay}
                disabled={!walletAccount || currentDebt === null || currentDebt === 0n}
              >
                Max
              </Button>
            </div>
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Input
                  value={repayAmount}
                  onChange={(e) => setRepayAmount(e.target.value)}
                  placeholder="0.00"
                  className="font-mono text-xs pr-16"
                />
                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground pointer-events-none">
                  {STABLECOIN_SYMBOL}
                </span>
              </div>
              <Button size="sm" onClick={() => void doRepay()} disabled={!walletAccount}>
                Repay
              </Button>
            </div>
          </div>
        </div>
      </SectionCard>
    </>
  )
}
