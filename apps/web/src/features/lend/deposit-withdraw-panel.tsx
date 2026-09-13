import { useEffect, useState } from 'react'
import { ethers } from 'ethers'
import type { Contract } from 'ethers'
import { AmountInput } from '@/components/shared/amount-input'
import { Figure } from '@/components/shared/figure'
import { Ledger, LedgerRow } from '@/components/shared/ledger'
import { Money } from '@/components/shared/money'
import { Reason } from '@/components/shared/reason'
import { Section } from '@/components/shared/section'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useAllowance } from '@/hooks/use-allowance'
import { useStablecoinRead, useVaultRead } from '@/hooks/use-contracts'
import type { VaultInfo } from '@/hooks/use-vault-info'
import { Erc20Abi, LendingVaultAbi } from '@/lib/abis'
import { STABLECOIN_SYMBOL } from '@/lib/constants'
import { exactAmount, parseAmount } from '@/lib/format'
import type { ActionCtx } from '@/lib/reasons'
import { depositReason, withdrawReason } from '@/lib/reasons'
import { sendContractTx } from '@/stores/tx-store'
import { useConfigStore } from '@/stores/config-store'
import { useWalletStore } from '@/stores/wallet-store'
import { sharePriceText } from './share-price'

const APPROVE_LABEL = `Approve ${STABLECOIN_SYMBOL}`
const PREVIEW_DEBOUNCE_MS = 300

type Props = {
  vault: VaultInfo
  decimals: number
}

function lower(a: bigint | null, b: bigint | null): bigint | null {
  if (a === null || b === null) return null
  return a < b ? a : b
}

/** Amount field text for a known balance: the exact figure, so Max is not rounded down. */
function fieldValue(value: bigint | null, decimals: number): string {
  if (value === null || value <= 0n) return ''
  return exactAmount(value, decimals)
}

/**
 * Shares to burn for `assets`. The vault truncates on conversion, so add one
 * base unit when the round trip comes back short, then cap at what is held.
 */
async function sharesForAssets(
  vault: Contract,
  assets: bigint,
  held: bigint | null,
  cash: bigint | null,
): Promise<bigint> {
  let shares = (await vault.convertToShares(assets)) as bigint
  const roundTrip = (await vault.convertToAssets(shares)) as bigint
  // Round up only while the extra unit stays inside the cash the vault can
  // pay out — withdraw() reverts with InsufficientLiquidity otherwise.
  if (roundTrip < assets && (cash === null || assets < cash)) shares += 1n
  if (held !== null && shares > held) shares = held
  return shares
}

/** Failures are surfaced centrally by `sendContractTx` — one toast, one strip. */
function fireAndForget(pending: Promise<void>): void {
  void pending.catch(() => undefined)
}

export function DepositWithdrawPanel({ vault, decimals }: Props) {
  const walletAccount = useWalletStore((s) => s.walletAccount)
  const walletChainId = useWalletStore((s) => s.walletChainId)
  const txState = useWalletStore((s) => s.txState)
  const refreshKey = useWalletStore((s) => s.refreshKey)
  const chainId = useConfigStore((s) => s.chainId)
  const vaultAddress = useConfigStore((s) => s.vaultAddress)
  const configStablecoin = useConfigStore((s) => s.stablecoinAddress)

  // The vault's own `asset()` is the token it will actually pull; the env value
  // is only a stand-in until that read lands.
  const tokenAddress = vault.asset ?? configStablecoin

  const vaultRead = useVaultRead()
  const token = useStablecoinRead(tokenAddress)
  const { allowance } = useAllowance(tokenAddress, walletAccount, vaultAddress)

  const [tabValue, setTabValue] = useState('deposit')
  const [depositRaw, setDepositRaw] = useState('')
  const [withdrawRaw, setWithdrawRaw] = useState('')
  const [walletBalance, setWalletBalance] = useState<bigint | null>(null)
  const [depositShares, setDepositShares] = useState<bigint | null>(null)
  const [withdrawShares, setWithdrawShares] = useState<bigint | null>(null)

  const depositValue = parseAmount(depositRaw, decimals)
  const withdrawValue = parseAmount(withdrawRaw, decimals)

  const { myShares, myShareValue, availableLiquidity, totalBorrowed } = vault
  const redeemableNow = lower(myShareValue, availableLiquidity)

  const busy = txState.status === 'signing' || txState.status === 'pending'
  const label = txState.status === 'idle' ? '' : txState.label
  const approving = busy && label === APPROVE_LABEL

  // Wallet balance of the pool asset.
  useEffect(() => {
    let cancelled = false
    async function run(): Promise<void> {
      if (!token || !ethers.isAddress(walletAccount)) {
        setWalletBalance(null)
        return
      }
      try {
        const balance = (await token.balanceOf(walletAccount)) as bigint
        if (!cancelled) setWalletBalance(balance)
      } catch {
        if (!cancelled) setWalletBalance(null)
      }
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [token, walletAccount, refreshKey])

  // Deposit preview: shares the vault would mint.
  useEffect(() => {
    if (!vaultRead || depositValue === null || depositValue <= 0n) {
      setDepositShares(null)
      return
    }
    let cancelled = false
    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          const shares = (await vaultRead.convertToShares(depositValue)) as bigint
          if (!cancelled) setDepositShares(shares)
        } catch {
          if (!cancelled) setDepositShares(null)
        }
      })()
    }, PREVIEW_DEBOUNCE_MS)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [vaultRead, depositValue, refreshKey])

  // Withdraw preview: shares the vault would burn for the amount typed.
  useEffect(() => {
    if (!vaultRead || withdrawValue === null || withdrawValue <= 0n) {
      setWithdrawShares(null)
      return
    }
    let cancelled = false
    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          const shares = await sharesForAssets(
            vaultRead,
            withdrawValue,
            myShares,
            availableLiquidity,
          )
          if (!cancelled) setWithdrawShares(shares)
        } catch {
          if (!cancelled) setWithdrawShares(null)
        }
      })()
    }, PREVIEW_DEBOUNCE_MS)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [vaultRead, withdrawValue, myShares, availableLiquidity, refreshKey])

  const ctx: ActionCtx = {
    walletAccount,
    walletChainId,
    chainId,
    viewed: walletAccount,
    // Vault deposits and withdrawals do not run through the manager's pause.
    paused: null,
  }

  const depositBlock = depositReason(
    { walletBalance, amount: depositValue, raw: depositRaw, decimals },
    ctx,
  )
  const withdrawBlock = withdrawReason(
    {
      position: myShareValue,
      cash: availableLiquidity,
      amount: withdrawValue,
      raw: withdrawRaw,
      decimals,
    },
    ctx,
  )

  const needsApproval =
    depositValue !== null &&
    depositValue > 0n &&
    (allowance === null || allowance < depositValue)

  const depositBlocked = Boolean(depositBlock)

  const overCash =
    withdrawBlock === null &&
    withdrawValue !== null &&
    availableLiquidity !== null &&
    withdrawValue > availableLiquidity

  // Blocked by prose, not by `disabled`: the control stays focusable and points
  // at the sentence that explains it.
  const withdrawBlocked = Boolean(withdrawBlock) || overCash

  const depositPrice =
    depositShares !== null && depositShares > 0n && depositValue !== null
      ? sharePriceText(depositValue, depositShares)
      : null
  const withdrawPrice =
    withdrawShares !== null && withdrawShares > 0n && withdrawValue !== null
      ? sharePriceText(withdrawValue, withdrawShares)
      : null

  function handleApprove(): void {
    if (depositValue === null || depositValue <= 0n) return
    fireAndForget(
      sendContractTx(APPROVE_LABEL, tokenAddress, Erc20Abi, (c) =>
        c.approve(vaultAddress, depositValue),
      ),
    )
  }

  function handleDeposit(): void {
    if (depositValue === null || depositValue <= 0n) return
    fireAndForget(
      sendContractTx('Deposit', vaultAddress, LendingVaultAbi, (c) => c.deposit(depositValue)),
    )
  }

  function handleWithdraw(): void {
    if (withdrawValue === null || withdrawValue <= 0n) return
    fireAndForget(
      sendContractTx('Withdraw', vaultAddress, LendingVaultAbi, async (c) => {
        const shares = await sharesForAssets(c, withdrawValue, myShares, availableLiquidity)
        if (shares <= 0n) throw new Error('The share amount to redeem could not be read.')
        return c.withdraw(shares)
      }),
    )
  }

  return (
    <Section raised title="Pool actions">
      <Tabs value={tabValue} onValueChange={setTabValue}>
        <TabsList variant="segmented">
          <TabsTrigger value="deposit">Deposit</TabsTrigger>
          <TabsTrigger value="withdraw">Withdraw</TabsTrigger>
        </TabsList>

        <TabsContent value="deposit" className="space-y-4 pt-2">
          <Ledger>
            <LedgerRow
              label="Wallet balance"
              value={<Money value={walletBalance} decimals={decimals} />}
            />
          </Ledger>

          <AmountInput
            id="lend-deposit-amount"
            aria-label={`Deposit amount in ${STABLECOIN_SYMBOL}`}
            value={depositRaw}
            onChange={setDepositRaw}
            decimals={decimals}
            unit={STABLECOIN_SYMBOL}
            max={{
              label: 'Max',
              onClick: () => setDepositRaw(fieldValue(walletBalance, decimals)),
              disabled: walletBalance === null || walletBalance === 0n,
            }}
          />

          {depositShares !== null && depositPrice !== null ? (
            <p className="text-xs leading-relaxed text-bone-3">
              You receive ≈ <Money value={depositShares} decimals={decimals} unit={null} /> shares
              at{' '}
              <span className="num">
                <Figure>{depositPrice}</Figure>
              </span>{' '}
              {STABLECOIN_SYMBOL}/share
            </p>
          ) : null}

          <p className="text-xs leading-relaxed text-bone-3">
            Token allowance for deposit: <Money value={allowance} decimals={decimals} />
          </p>

          {needsApproval ? (
            <Button
              type="button"
              className="w-full"
              loading={approving}
              aria-disabled={depositBlocked || busy || undefined}
              aria-describedby={depositBlock ? 'deposit-reason' : undefined}
              onClick={() => {
                if (!depositBlocked && !busy) handleApprove()
              }}
            >
              {approving ? 'Approving…' : APPROVE_LABEL}
            </Button>
          ) : (
            <Button
              type="button"
              className="w-full"
              loading={busy && label === 'Deposit'}
              aria-disabled={depositBlocked || busy || undefined}
              aria-describedby={depositBlock ? 'deposit-reason' : undefined}
              onClick={() => {
                if (!depositBlocked && !busy) handleDeposit()
              }}
            >
              Deposit
            </Button>
          )}

          {depositBlock ? (
            <Reason id="deposit-reason" role="status">
              {depositBlock}
            </Reason>
          ) : null}
        </TabsContent>

        <TabsContent value="withdraw" className="space-y-4 pt-2">
          <Ledger>
            <LedgerRow
              label="Your position"
              value={<Money value={myShareValue} decimals={decimals} />}
              loading={vault.isLoading}
            />
            <LedgerRow
              label="Redeemable now"
              value={<Money value={redeemableNow} decimals={decimals} />}
              loading={vault.isLoading}
            />
          </Ledger>

          <AmountInput
            id="lend-withdraw-amount"
            aria-label={`Withdraw amount in ${STABLECOIN_SYMBOL}`}
            value={withdrawRaw}
            onChange={setWithdrawRaw}
            decimals={decimals}
            unit={STABLECOIN_SYMBOL}
            invalid={overCash}
            max={{
              label: 'Max available',
              onClick: () => setWithdrawRaw(fieldValue(redeemableNow, decimals)),
              disabled: redeemableNow === null || redeemableNow === 0n,
            }}
          />

          {withdrawShares !== null && withdrawPrice !== null ? (
            <p className="text-xs leading-relaxed text-bone-3">
              Redeems ≈ <Money value={withdrawShares} decimals={decimals} unit={null} /> shares at{' '}
              <span className="num">
                <Figure>{withdrawPrice}</Figure>
              </span>{' '}
              {STABLECOIN_SYMBOL}/share
            </p>
          ) : null}

          <Button
            type="button"
            className="w-full"
            loading={busy && label === 'Withdraw'}
            aria-disabled={withdrawBlocked || busy || undefined}
            aria-describedby={withdrawBlocked ? 'withdraw-reason' : undefined}
            onClick={() => {
              if (!withdrawBlocked && !busy) handleWithdraw()
            }}
          >
            Withdraw
          </Button>

          {withdrawBlock ? (
            <Reason id="withdraw-reason" role="status">
              {withdrawBlock}
            </Reason>
          ) : null}

          {overCash ? (
            <div className="space-y-2">
              <Reason id="withdraw-reason" role="status" tone="warn">
                Only <Money value={availableLiquidity} decimals={decimals} /> is available now;{' '}
                <Money value={totalBorrowed} decimals={decimals} /> is deployed to borrowers and
                returns as they repay. Withdraw up to{' '}
                <Money value={availableLiquidity} decimals={decimals} /> or try later.
              </Reason>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setWithdrawRaw(fieldValue(availableLiquidity, decimals))}
              >
                Use available
              </Button>
            </div>
          ) : null}
        </TabsContent>
      </Tabs>
    </Section>
  )
}
