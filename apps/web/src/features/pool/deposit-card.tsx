import { useState, useEffect, useCallback } from 'react'
import { ethers } from 'ethers'
import { CheckCircle2 } from 'lucide-react'
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
import { STABLECOIN_SYMBOL } from '@/lib/constants'
import { toast } from 'sonner'

const DECIMALS = 6

type Props = {
  embedded?: boolean
}

export function DepositCard({ embedded = false }: Props) {
  const walletAccount = useWalletStore((s) => s.walletAccount)
  const txStatus = useWalletStore((s) => s.txState.status)
  const vaultAddress = useConfigStore((s) => s.vaultAddress)
  const stablecoinAddress = useConfigStore((s) => s.stablecoinAddress)
  const stablecoinContract = useStablecoinRead(stablecoinAddress)
  const vaultContract = useVaultRead()

  const [amount, setAmount] = useState('')
  const [balance, setBalance] = useState<bigint | null>(null)
  const [allowance, setAllowance] = useState<bigint | null>(null)
  const [expectedShares, setExpectedShares] = useState<bigint | null>(null)

  const fetchBalance = useCallback(async () => {
    if (!stablecoinContract || !ethers.isAddress(walletAccount)) {
      setBalance(null)
      setAllowance(null)
      return
    }
    try {
      const [bal, allw] = await Promise.all([
        stablecoinContract.balanceOf(walletAccount) as Promise<bigint>,
        stablecoinContract.allowance(walletAccount, vaultAddress) as Promise<bigint>,
      ])
      setBalance(bal)
      setAllowance(allw)
    } catch {
      setBalance(null)
      setAllowance(null)
    }
  }, [stablecoinContract, walletAccount, vaultAddress])

  useEffect(() => {
    void fetchBalance()
    const interval = setInterval(() => void fetchBalance(), 10_000)
    return () => clearInterval(interval)
  }, [fetchBalance, txStatus])

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
    let parsed: bigint
    try {
      parsed = ethers.parseUnits(amount.trim() || '0', DECIMALS)
    } catch {
      toast.error('Invalid amount format')
      return
    }
    if (parsed <= 0n) {
      toast.error('Enter a valid amount')
      return
    }
    toast.promise(
      sendContractTx('approve', stablecoinAddress, Erc20Abi, (c) =>
        c.approve(vaultAddress, parsed),
      ),
      { loading: 'Approving...', success: 'Approval confirmed!', error: 'Approval failed' },
    )
  }

  async function doDeposit() {
    let parsed: bigint
    try {
      parsed = ethers.parseUnits(amount.trim() || '0', DECIMALS)
    } catch {
      toast.error('Invalid amount format')
      return
    }
    if (parsed <= 0n) {
      toast.error('Enter a valid amount')
      return
    }
    toast.promise(
      sendContractTx('deposit', vaultAddress, LendingVaultAbi, (c) => c.deposit(parsed)),
      { loading: 'Depositing...', success: 'Deposit confirmed!', error: 'Deposit failed' },
    )
  }

  function handleMax() {
    if (balance !== null && balance > 0n) {
      setAmount(ethers.formatUnits(balance, DECIMALS))
    }
  }

  const txBusy = txStatus === 'signing' || txStatus === 'pending'
  const disabled = !walletAccount || txBusy

  // Determine if approve step is needed
  let parsedAmount = 0n
  try {
    if (amount.trim()) parsedAmount = ethers.parseUnits(amount.trim(), DECIMALS)
  } catch { /* ignore */ }

  const needsApprove = parsedAmount > 0n && allowance !== null && allowance < parsedAmount
  const approveIsDone = parsedAmount > 0n && allowance !== null && allowance >= parsedAmount

  const content = (
    <div className="space-y-3">
      <KeyValueList>
        <KeyValueRow
          label={`My ${STABLECOIN_SYMBOL} Balance`}
          value={balance === null ? '—' : `${ethers.formatUnits(balance, DECIMALS)} ${STABLECOIN_SYMBOL}`}
          mono
        />
        {expectedShares !== null && (
          <KeyValueRow
            label="Expected Shares"
            value={
              <span className="flex items-center gap-1">
                {ethers.formatUnits(expectedShares, DECIMALS)}
                <span
                  className="text-[10px] text-muted-foreground cursor-help"
                  title="Pool ownership tokens. Value grows as the pool earns yield."
                >
                  ⓘ
                </span>
              </span>
            }
            mono
          />
        )}
      </KeyValueList>

      <div>
        <div className="flex items-center justify-between mb-1">
          <Label className="text-[11px] uppercase tracking-wider">Amount</Label>
          <Button
            variant="ghost"
            size="xs"
            className="text-[11px] text-primary"
            onClick={handleMax}
            disabled={disabled || balance === null || balance === 0n}
          >
            Max
          </Button>
        </div>
        <div className="relative">
          <Input
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="0.00"
            className="font-mono text-xs pr-16"
            type="text"
            inputMode="decimal"
            disabled={disabled}
          />
          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground pointer-events-none">
            {STABLECOIN_SYMBOL}
          </span>
        </div>
      </div>

      {/* Two-step: Approve → Deposit */}
      {parsedAmount > 0n ? (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <div className={`flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${approveIsDone ? 'bg-emerald-500/20 text-emerald-400' : 'bg-primary/20 text-primary'}`}>
              {approveIsDone ? <CheckCircle2 className="h-3.5 w-3.5" /> : '1'}
            </div>
            <Button
              variant={needsApprove ? 'default' : 'secondary'}
              size="sm"
              className="flex-1"
              onClick={() => void doApprove()}
              disabled={disabled || !amount.trim() || approveIsDone}
            >
              {approveIsDone ? 'Approved' : 'Step 1: Approve'}
            </Button>
          </div>
          <div className="flex items-center gap-2">
            <div className={`flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${!approveIsDone ? 'bg-muted/40 text-muted-foreground opacity-50' : 'bg-primary/20 text-primary'}`}>
              2
            </div>
            <Button
              size="sm"
              className="flex-1"
              onClick={() => void doDeposit()}
              disabled={disabled || !amount.trim() || needsApprove}
            >
              Step 2: Deposit
            </Button>
          </div>
          {needsApprove && (
            <p className="text-[11px] text-muted-foreground">
              Approve the vault to spend your {STABLECOIN_SYMBOL} before depositing.
            </p>
          )}
        </div>
      ) : (
        <div className="flex gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => void doApprove()}
            disabled={disabled || !amount.trim()}
          >
            Approve
          </Button>
          <Button size="sm" onClick={() => void doDeposit()} disabled={disabled || !amount.trim()}>
            Deposit
          </Button>
        </div>
      )}
    </div>
  )

  if (embedded) return content

  return (
    <SectionCard title="Deposit" description={`Deposit ${STABLECOIN_SYMBOL} to earn yield`}>
      {content}
    </SectionCard>
  )
}
