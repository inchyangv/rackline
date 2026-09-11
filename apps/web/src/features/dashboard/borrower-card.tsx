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
import { sendContractTx } from '@/stores/tx-store'
import { HashCreditManagerAbi, Erc20Abi } from '@/lib/abis'
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
  const { availableCredit, borrowerInfo, stablecoinDecimals, stablecoinBalance, isLoading } =
    useBorrowerInfo(borrowerAddress, stablecoin)

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
    <SectionCard title="Borrower">
      <div className="space-y-3">
        <div>
          <Label className="text-[10px] uppercase tracking-widest">Borrower address (EVM)</Label>
          <Input
            value={borrowerAddress}
            onChange={(e) => setBorrowerAddress(e.target.value)}
            placeholder="0x..."
            className="mt-1 font-mono text-xs"
          />
        </div>

        <KeyValueList>
          <KeyValueRow
            label="availableCredit"
            value={
              isLoading ? (
                <Skeleton className="h-4 w-32" />
              ) : availableCredit === null ? (
                '—'
              ) : (
                `${ethers.formatUnits(availableCredit, stablecoinDecimals)} (decimals=${stablecoinDecimals})`
              )
            }
            mono
          />
          <KeyValueRow
            label="stablecoinBalance"
            value={
              isLoading ? (
                <Skeleton className="h-4 w-32" />
              ) : stablecoinBalance === null ? (
                '—'
              ) : (
                ethers.formatUnits(stablecoinBalance, stablecoinDecimals)
              )
            }
            mono
          />
          <KeyValueRow
            label="borrowerInfo"
            value={borrowerInfo ? JSON.stringify(borrowerInfo, null, 2) : '—'}
            mono
            pre
          />
        </KeyValueList>

        <div className="space-y-2.5 pt-2">
          <div>
            <Label className="text-[10px] uppercase tracking-widest">Borrow (Execute Loan)</Label>
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
          </div>
          <div>
            <Label className="text-[10px] uppercase tracking-widest">Approve (Stablecoin Allowance)</Label>
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

        <p className="text-xs text-muted-foreground">
          Enter amounts in human-readable units. (e.g. `1000` = 1000 USDC)
        </p>
      </div>
    </SectionCard>
  )
}
