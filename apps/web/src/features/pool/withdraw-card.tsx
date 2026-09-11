import { useState, useEffect } from 'react'
import { ethers } from 'ethers'
import { SectionCard } from '@/components/shared/section-card'
import { KeyValueList } from '@/components/shared/key-value-list'
import { KeyValueRow } from '@/components/shared/key-value-row'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { useWalletStore } from '@/stores/wallet-store'
import { useConfigStore } from '@/stores/config-store'
import { useVaultRead } from '@/hooks/use-contracts'
import { sendContractTx } from '@/stores/tx-store'
import { LendingVaultAbi } from '@/lib/abis'
import { toast } from 'sonner'
import type { VaultInfo } from '@/hooks/use-vault-info'

const DECIMALS = 6

type Props = {
  vault: VaultInfo
}

export function WithdrawCard({ vault }: Props) {
  const walletAccount = useWalletStore((s) => s.walletAccount)
  const vaultAddress = useConfigStore((s) => s.vaultAddress)
  const vaultContract = useVaultRead()

  const { myShares, availableLiquidity } = vault

  const [shares, setShares] = useState('')
  const [expectedAmount, setExpectedAmount] = useState<bigint | null>(null)

  // Preview expected mUSDT output
  useEffect(() => {
    let cancelled = false
    async function preview() {
      if (!vaultContract || !shares) {
        setExpectedAmount(null)
        return
      }
      try {
        const parsed = ethers.parseUnits(shares, DECIMALS)
        if (parsed <= 0n) {
          setExpectedAmount(null)
          return
        }
        const amount = (await vaultContract.convertToAssets(parsed)) as bigint
        if (!cancelled) setExpectedAmount(amount)
      } catch {
        if (!cancelled) setExpectedAmount(null)
      }
    }
    void preview()
    return () => {
      cancelled = true
    }
  }, [vaultContract, shares])

  function handleMax() {
    if (myShares !== null && myShares > 0n) {
      setShares(ethers.formatUnits(myShares, DECIMALS))
    }
  }

  async function doWithdraw() {
    const parsed = ethers.parseUnits(shares || '0', DECIMALS)
    toast.promise(
      sendContractTx('withdraw', vaultAddress, LendingVaultAbi, (c) => c.withdraw(parsed)),
      { loading: 'Withdrawing...', success: 'Withdraw confirmed!', error: 'Withdraw failed' },
    )
  }

  const disabled = !walletAccount
  const exceedsLiquidity =
    expectedAmount !== null && availableLiquidity !== null && expectedAmount > availableLiquidity

  return (
    <SectionCard title="Withdraw" description="Redeem shares for mUSDT">
      <div className="space-y-3">
        <KeyValueList>
          <KeyValueRow
            label="My Shares"
            value={myShares === null ? '—' : ethers.formatUnits(myShares, DECIMALS)}
            mono
          />
          {expectedAmount !== null && (
            <KeyValueRow
              label="Expected mUSDT"
              value={`${ethers.formatUnits(expectedAmount, DECIMALS)} mUSDT`}
              mono
            />
          )}
        </KeyValueList>

        {exceedsLiquidity && (
          <div className="rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive">
            Withdrawal amount exceeds available liquidity.
          </div>
        )}

        <div>
          <div className="flex items-center justify-between">
            <Label className="text-[10px] uppercase tracking-widest">Shares</Label>
            <Button
              variant="ghost"
              size="xs"
              className="text-[10px] uppercase tracking-widest text-primary"
              onClick={handleMax}
              disabled={disabled || myShares === null || myShares === 0n}
            >
              Max
            </Button>
          </div>
          <Input
            value={shares}
            onChange={(e) => setShares(e.target.value)}
            placeholder="e.g. 500"
            className="mt-1 font-mono text-xs"
            type="text"
            inputMode="decimal"
          />
        </div>

        <Button
          size="sm"
          onClick={() => void doWithdraw()}
          disabled={disabled || !shares || exceedsLiquidity}
        >
          Withdraw
        </Button>
      </div>
    </SectionCard>
  )
}
