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
  embedded?: boolean
}

export function WithdrawCard({ vault, embedded = false }: Props) {
  const walletAccount = useWalletStore((s) => s.walletAccount)
  const vaultAddress = useConfigStore((s) => s.vaultAddress)
  const vaultContract = useVaultRead()

  const { myShares, myShareValue, availableLiquidity } = vault

  // mUSDT-based input (user-facing), shares derived internally
  const [usdtAmount, setUsdtAmount] = useState('')
  const [requiredShares, setRequiredShares] = useState<bigint | null>(null)

  // Derive required shares from mUSDT input
  useEffect(() => {
    let cancelled = false
    async function preview() {
      if (!vaultContract || !usdtAmount) {
        setRequiredShares(null)
        return
      }
      try {
        const parsed = ethers.parseUnits(usdtAmount, DECIMALS)
        if (parsed <= 0n) {
          setRequiredShares(null)
          return
        }
        const shares = (await vaultContract.convertToShares(parsed)) as bigint
        if (!cancelled) setRequiredShares(shares)
      } catch {
        if (!cancelled) setRequiredShares(null)
      }
    }
    void preview()
    return () => {
      cancelled = true
    }
  }, [vaultContract, usdtAmount])

  function handleMax() {
    if (myShareValue !== null && myShareValue > 0n) {
      setUsdtAmount(ethers.formatUnits(myShareValue, DECIMALS))
    }
  }

  async function doWithdraw() {
    // Use requiredShares if derived, otherwise parse from input as shares fallback
    const sharesToRedeem =
      requiredShares !== null
        ? requiredShares
        : ethers.parseUnits(usdtAmount || '0', DECIMALS)
    toast.promise(
      sendContractTx('withdraw', vaultAddress, LendingVaultAbi, (c) => c.withdraw(sharesToRedeem)),
      { loading: 'Withdrawing...', success: 'Withdraw confirmed!', error: 'Withdraw failed' },
    )
  }

  const disabled = !walletAccount
  const exceedsLiquidity =
    requiredShares !== null && availableLiquidity !== null && requiredShares > availableLiquidity

  const content = (
    <div className="space-y-3">
      <KeyValueList>
        <KeyValueRow
          label={
            <span className="flex items-center gap-1">
              My Shares
              <span
                className="text-[10px] text-muted-foreground cursor-help"
                title="Pool ownership tokens. Value grows as the pool earns yield."
              >
                ⓘ
              </span>
            </span>
          }
          value={myShares === null ? '—' : ethers.formatUnits(myShares, DECIMALS)}
          mono
        />
        <KeyValueRow
          label="Current Value"
          value={myShareValue === null ? '—' : `${ethers.formatUnits(myShareValue, DECIMALS)} mUSDT`}
          mono
        />
        {requiredShares !== null && (
          <KeyValueRow
            label="Shares to redeem"
            value={ethers.formatUnits(requiredShares, DECIMALS)}
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
        <div className="flex items-center justify-between mb-1">
          <Label className="text-[11px] uppercase tracking-wider">Amount</Label>
          <Button
            variant="ghost"
            size="xs"
            className="text-[11px] text-primary"
            onClick={handleMax}
            disabled={disabled || myShareValue === null || myShareValue === 0n}
          >
            Max
          </Button>
        </div>
        <div className="relative">
          <Input
            value={usdtAmount}
            onChange={(e) => setUsdtAmount(e.target.value)}
            placeholder="0.00"
            className="font-mono text-xs pr-16"
            type="text"
            inputMode="decimal"
          />
          <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-muted-foreground pointer-events-none">
            mUSDT
          </span>
        </div>
      </div>

      <Button
        size="sm"
        onClick={() => void doWithdraw()}
        disabled={disabled || !usdtAmount || exceedsLiquidity}
      >
        Withdraw
      </Button>
    </div>
  )

  if (embedded) return content

  return (
    <SectionCard title="Withdraw" description="Redeem shares for mUSDT">
      {content}
    </SectionCard>
  )
}
