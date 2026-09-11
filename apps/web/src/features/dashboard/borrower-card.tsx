import { ethers } from 'ethers'
import { SectionCard } from '@/components/shared/section-card'
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
  const { availableCredit, borrowerInfo, stablecoinDecimals, stablecoinBalance, currentDebt, accruedInterest, isLoading } =
    useBorrowerInfo(borrowerAddress, stablecoin)
  const { borrowAPR } = useVaultInfo()

  // Determine if borrow should be disabled (unregistered or no credit)
  const borrowerStatus = typeof borrowerInfo?.status === 'bigint' ? Number(borrowerInfo.status) : 0
  const creditLimit = typeof borrowerInfo?.creditLimit === 'bigint' ? borrowerInfo.creditLimit : 0n
  const isBorrowDisabled = !borrowerInfo || borrowerStatus === 0 || creditLimit === 0n
  const aprDisplay = borrowAPR !== null ? `${(Number(borrowAPR) / 100).toFixed(2)}%` : '—'

  // BTC connection status
  const ZERO_BYTES32 = '0x0000000000000000000000000000000000000000000000000000000000000000'
  const btcPayoutKeyHash = typeof borrowerInfo?.btcPayoutKeyHash === 'string' ? borrowerInfo.btcPayoutKeyHash : ZERO_BYTES32
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

  return (
    <SectionCard title="My Credit">
      <div className="space-y-3">
        <div>
          <Label className="text-[10px] uppercase tracking-widest">Wallet Address</Label>
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
          <KeyValueRow
            label="Borrow APR"
            value={
              isLoading ? <Skeleton className="h-4 w-20" /> : aprDisplay
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
            label="Total Repayment"
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
        </KeyValueList>

        <div className="space-y-2.5 pt-2">
          <div>
            <Label className="text-[10px] uppercase tracking-widest">Borrow</Label>
            {isBorrowDisabled ? (
              <div className="mt-1 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3">
                <p className="text-xs text-amber-200 font-medium">BTC wallet not linked</p>
                <p className="text-xs text-muted-foreground mt-1">
                  Link your BTC wallet in the &quot;Link BTC Wallet&quot; section below to enable borrowing.
                </p>
              </div>
            ) : (
              <>
                <p className="text-[10px] text-muted-foreground mt-0.5">
                  Fixed APR: {aprDisplay}
                </p>
                <div className="flex gap-2 mt-1">
                  <Input
                    value={borrowAmount}
                    onChange={(e) => setBorrowAmount(e.target.value)}
                    placeholder="e.g. 1000"
                    className="font-mono text-xs"
                  />
                  <Button size="sm" onClick={() => void doBorrow()} disabled={!walletAccount}>
                    Borrow
                  </Button>
                </div>
              </>
            )}
          </div>
          <div>
            <Label className="text-[10px] uppercase tracking-widest">Approve Spending</Label>
            <div className="flex gap-2 mt-1">
              <Input
                value={approveAmount}
                onChange={(e) => setApproveAmount(e.target.value)}
                placeholder="e.g. 1000000"
                className="font-mono text-xs"
              />
              <Button variant="secondary" size="sm" onClick={() => void approveStablecoin()} disabled={!walletAccount}>
                Approve
              </Button>
            </div>
          </div>
          <div>
            <Label className="text-[10px] uppercase tracking-widest">Repay</Label>
            <div className="flex gap-2 mt-1">
              <Input
                value={repayAmount}
                onChange={(e) => setRepayAmount(e.target.value)}
                placeholder="e.g. 100"
                className="font-mono text-xs"
              />
              <Button size="sm" onClick={() => void doRepay()} disabled={!walletAccount}>
                Repay
              </Button>
            </div>
          </div>
        </div>
      </div>
    </SectionCard>
  )
}
