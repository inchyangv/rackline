import { useState, useEffect, useCallback } from 'react'
import { ethers } from 'ethers'
import { SectionCard } from '@/components/shared/section-card'
import { KeyValueList } from '@/components/shared/key-value-list'
import { KeyValueRow } from '@/components/shared/key-value-row'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { useWalletStore } from '@/stores/wallet-store'
import { useConfigStore } from '@/stores/config-store'
import { useVaultRead, useStablecoinRead } from '@/hooks/use-contracts'
import { sendContractTx } from '@/stores/tx-store'
import { LendingVaultAbi, Erc20Abi } from '@/lib/abis'
import { toast } from 'sonner'

const DECIMALS = 6

export function DepositCard() {
  const walletAccount = useWalletStore((s) => s.walletAccount)
  const vaultAddress = useConfigStore((s) => s.vaultAddress)
  const stablecoinAddress = useConfigStore((s) => s.stablecoinAddress)
  const stablecoinContract = useStablecoinRead(stablecoinAddress)
  const vaultContract = useVaultRead()

  const [amount, setAmount] = useState('')
  const [balance, setBalance] = useState<bigint | null>(null)
  const [expectedShares, setExpectedShares] = useState<bigint | null>(null)

  // Fetch mUSDT balance
  const fetchBalance = useCallback(async () => {
    if (!stablecoinContract || !ethers.isAddress(walletAccount)) {
      setBalance(null)
      return
    }
    try {
      const bal = (await stablecoinContract.balanceOf(walletAccount)) as bigint
      setBalance(bal)
    } catch {
      setBalance(null)
    }
  }, [stablecoinContract, walletAccount])

  useEffect(() => {
    void fetchBalance()
    const interval = setInterval(() => void fetchBalance(), 10_000)
    return () => clearInterval(interval)
  }, [fetchBalance])

  // Preview expected shares
  useEffect(() => {
    let cancelled = false
    async function preview() {
      if (!vaultContract || !amount) {
        setExpectedShares(null)
        return
      }
      try {
        const parsed = ethers.parseUnits(amount, DECIMALS)
        if (parsed <= 0n) {
          setExpectedShares(null)
          return
        }
        const shares = (await vaultContract.convertToShares(parsed)) as bigint
        if (!cancelled) setExpectedShares(shares)
      } catch {
        if (!cancelled) setExpectedShares(null)
      }
    }
    void preview()
    return () => {
      cancelled = true
    }
  }, [vaultContract, amount])

  async function doApprove() {
    const parsed = ethers.parseUnits(amount || '0', DECIMALS)
    toast.promise(
      sendContractTx('approve', stablecoinAddress, Erc20Abi, (c) =>
        c.approve(vaultAddress, parsed),
      ),
      { loading: 'Approving...', success: 'Approval confirmed!', error: 'Approval failed' },
    )
  }

  async function doDeposit() {
    const parsed = ethers.parseUnits(amount || '0', DECIMALS)
    toast.promise(
      sendContractTx('deposit', vaultAddress, LendingVaultAbi, (c) => c.deposit(parsed)),
      { loading: 'Depositing...', success: 'Deposit confirmed!', error: 'Deposit failed' },
    )
  }

  const disabled = !walletAccount

  return (
    <SectionCard title="Deposit" description="Deposit mUSDT to earn yield">
      <div className="space-y-3">
        <KeyValueList>
          <KeyValueRow
            label="My mUSDT Balance"
            value={
              balance === null
                ? '—'
                : `${ethers.formatUnits(balance, DECIMALS)} mUSDT`
            }
            mono
          />
          {expectedShares !== null && (
            <KeyValueRow
              label="Expected Shares"
              value={ethers.formatUnits(expectedShares, DECIMALS)}
              mono
            />
          )}
        </KeyValueList>

        <div>
          <Label className="text-[10px] uppercase tracking-widest">Amount (mUSDT)</Label>
          <Input
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="e.g. 1000"
            className="mt-1 font-mono text-xs"
            type="text"
            inputMode="decimal"
          />
        </div>

        <div className="flex gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => void doApprove()}
            disabled={disabled || !amount}
          >
            Approve
          </Button>
          <Button size="sm" onClick={() => void doDeposit()} disabled={disabled || !amount}>
            Deposit
          </Button>
        </div>
      </div>
    </SectionCard>
  )
}
