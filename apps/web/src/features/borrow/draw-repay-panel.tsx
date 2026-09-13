import { useEffect, useRef, useState } from 'react'
import { AmountInput } from '@/components/shared/amount-input'
import { Figure } from '@/components/shared/figure'
import { Ledger, LedgerRow } from '@/components/shared/ledger'
import { Money } from '@/components/shared/money'
import { Reason } from '@/components/shared/reason'
import { Section } from '@/components/shared/section'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useAllowance } from '@/hooks/use-allowance'
import type { Facility } from '@/hooks/use-facility'
import { useManagerReads } from '@/hooks/use-manager-reads'
import { Erc20Abi, HashCreditManagerAbi } from '@/lib/abis'
import { STABLECOIN_SYMBOL } from '@/lib/constants'
import { exactAmount, formatBps, parseAmount } from '@/lib/format'
import type { ActionCtx } from '@/lib/reasons'
import { drawReason, repayReason } from '@/lib/reasons'
import { useConfigStore } from '@/stores/config-store'
import { sendContractTx } from '@/stores/tx-store'
import { useWalletStore } from '@/stores/wallet-store'

type Mode = 'draw' | 'repay'

type Props = {
  facility: Facility
  viewed: string
}

const SECONDS_PER_YEAR = 31_536_000n
/** Interest can accrue between signing and confirmation; ~15 minutes of it. */
const BUFFER_SECONDS = 900n
const BPS_DENOMINATOR = 10_000n

function ceilDiv(numerator: bigint, denominator: bigint): bigint {
  return (numerator + denominator - 1n) / denominator
}

/**
 * Total owed plus a buffer for interest accruing before the transaction lands,
 * rounded up to the nearest 0.01. The contract collects only what is owed.
 */
function payoffAmount(totalOwed: bigint, aprBps: bigint | null, decimals: number): bigint {
  const buffer = ceilDiv(
    totalOwed * (aprBps ?? 0n) * BUFFER_SECONDS,
    BPS_DENOMINATOR * SECONDS_PER_YEAR,
  )
  const step = 10n ** BigInt(Math.max(0, decimals - 2))
  const gross = totalOwed + buffer
  return step > 1n ? ceilDiv(gross, step) * step : gross
}

export function DrawRepayPanel({ facility, viewed }: Props) {
  const walletAccount = useWalletStore((s) => s.walletAccount)
  const walletChainId = useWalletStore((s) => s.walletChainId)
  const txState = useWalletStore((s) => s.txState)
  const chainId = useConfigStore((s) => s.chainId)
  const managerAddress = useConfigStore((s) => s.managerAddress)
  const configStablecoin = useConfigStore((s) => s.stablecoinAddress)

  // The manager's own token is authoritative: approving anything else would
  // approve a token the manager never pulls. The env value is the fallback
  // while that read is outstanding.
  const { stablecoin } = useManagerReads()
  const stablecoinAddress = stablecoin || configStablecoin

  const { decimals } = facility
  const { allowance } = useAllowance(stablecoinAddress, walletAccount, managerAddress)

  // Repayment leads whenever drawing cannot be the next move.
  const preferred: Mode =
    facility.state === 'frozen' ||
    facility.state === 'closed' ||
    ((facility.principal ?? 0n) > 0n && facility.drawableNow === 0n)
      ? 'repay'
      : 'draw'

  const [mode, setMode] = useState<Mode>(preferred)
  const chosen = useRef(false)

  useEffect(() => {
    if (!chosen.current) setMode(preferred)
  }, [preferred])

  const [drawRaw, setDrawRaw] = useState('')
  const [repayRaw, setRepayRaw] = useState('')
  const [busy, setBusy] = useState(false)

  const ctx: ActionCtx = {
    walletAccount,
    walletChainId,
    chainId,
    viewed,
    paused: facility.paused,
  }

  const drawAmount = parseAmount(drawRaw, decimals)
  const repayAmount = parseAmount(repayRaw, decimals)

  const drawBlocked = drawReason(facility, drawAmount, drawRaw, ctx)
  const repayBlocked = repayReason(facility, repayAmount, repayRaw, ctx)

  const approving =
    (txState.status === 'signing' || txState.status === 'pending') &&
    txState.label === 'Approve mUSDT'
  // An unread allowance is not "approval required": before an amount is typed
  // the next step is still Repay.
  const needsApproval =
    repayAmount !== null && repayAmount > 0n && (allowance === null || allowance < repayAmount)

  const payoff =
    facility.totalOwed === null
      ? null
      : payoffAmount(facility.totalOwed, facility.borrowAprBps, decimals)

  // The buffer sentence describes the payoff figure, not a partial payment.
  const atPayoff = payoff !== null && repayAmount !== null && repayAmount === payoff

  const overpaying =
    repayAmount !== null && facility.totalOwed !== null && repayAmount > facility.totalOwed

  async function run(send: () => Promise<void>, clear: () => void) {
    setBusy(true)
    try {
      await send()
      clear()
    } catch {
      // sendContractTx reports the failure; the strip and toast carry it.
    } finally {
      setBusy(false)
    }
  }

  function onDraw() {
    if (drawAmount === null) return
    void run(
      () =>
        sendContractTx('Draw', managerAddress, HashCreditManagerAbi, (c) => c.borrow(drawAmount)),
      () => setDrawRaw(''),
    )
  }

  function onApprove() {
    if (repayAmount === null) return
    void run(
      () =>
        sendContractTx('Approve mUSDT', stablecoinAddress, Erc20Abi, (c) =>
          c.approve(managerAddress, repayAmount),
        ),
      () => undefined,
    )
  }

  function onRepay() {
    if (repayAmount === null) return
    void run(
      () =>
        sendContractTx('Repay', managerAddress, HashCreditManagerAbi, (c) => c.repay(repayAmount)),
      () => setRepayRaw(''),
    )
  }

  return (
    <Section raised title="Facility actions">
      <Tabs
        value={mode}
        onValueChange={(value) => {
          chosen.current = true
          setMode(value === 'repay' ? 'repay' : 'draw')
        }}
      >
        <TabsList variant="segmented">
          <TabsTrigger value="draw">Draw</TabsTrigger>
          <TabsTrigger value="repay">Repay</TabsTrigger>
        </TabsList>

        <TabsContent value="draw" className="mt-4 space-y-3">
          <AmountInput
            id="draw-amount"
            aria-label="Draw amount"
            value={drawRaw}
            onChange={setDrawRaw}
            unit={STABLECOIN_SYMBOL}
            decimals={decimals}
            max={{
              label: 'Max',
              onClick: () => setDrawRaw(exactAmount(facility.drawableNow, decimals)),
              disabled: facility.drawableNow === null || facility.drawableNow === 0n,
            }}
          />
          <p className="text-xs leading-relaxed text-bone-3">
            Interest accrues on the outstanding balance at the current pool rate (
            <span className="num">
              <Figure>{formatBps(facility.borrowAprBps)}</Figure>
            </span>{' '}
            APR). Any interest accrued so far is added to principal.
          </p>
          {/* aria-disabled, not disabled: the control stays focusable so the
              reason below it can be read out as its description. */}
          <div>
            <Button
              type="button"
              className="w-full"
              loading={busy}
              aria-disabled={drawBlocked !== null || undefined}
              aria-describedby={drawBlocked ? 'draw-reason' : undefined}
              onClick={() => {
                if (drawBlocked === null && !busy) onDraw()
              }}
            >
              Draw
            </Button>
            {drawBlocked ? (
              <Reason id="draw-reason" role="status" tone="muted" className="mt-2">
                {drawBlocked}
              </Reason>
            ) : null}
          </div>
        </TabsContent>

        <TabsContent value="repay" className="mt-4 space-y-3">
          <Ledger>
            <LedgerRow
              label="Wallet balance"
              mono={false}
              value={<Money value={facility.walletBalance} decimals={decimals} />}
            />
          </Ledger>
          <AmountInput
            id="repay-amount"
            aria-label="Repay amount"
            value={repayRaw}
            onChange={setRepayRaw}
            unit={STABLECOIN_SYMBOL}
            decimals={decimals}
            max={{
              label: 'Repay in full',
              onClick: () => setRepayRaw(exactAmount(payoff, decimals)),
              disabled: payoff === null || payoff === 0n,
            }}
          />
          {atPayoff ? (
            <p className="text-xs leading-relaxed text-bone-3">
              Includes a small buffer for interest accruing before confirmation; only the exact
              amount owed is collected.
            </p>
          ) : null}
          {overpaying ? (
            <p className="text-xs leading-relaxed text-bone-3">
              Total owed is <Money value={facility.totalOwed} decimals={decimals} />; only{' '}
              <Money value={facility.totalOwed} decimals={decimals} /> will be collected.
            </p>
          ) : null}
          <Ledger>
            <LedgerRow
              label="Token allowance for repayment"
              mono={false}
              value={<Money value={allowance} decimals={decimals} />}
            />
          </Ledger>
          <div>
            {needsApproval ? (
              <Button
                type="button"
                className="w-full"
                loading={busy || approving}
                aria-disabled={repayBlocked !== null || approving || undefined}
                aria-describedby={repayBlocked ? 'repay-reason' : undefined}
                onClick={() => {
                  if (repayBlocked === null && !busy && !approving) onApprove()
                }}
              >
                {approving ? 'Approving…' : 'Approve mUSDT'}
              </Button>
            ) : (
              <Button
                type="button"
                className="w-full"
                loading={busy}
                aria-disabled={repayBlocked !== null || undefined}
                aria-describedby={repayBlocked ? 'repay-reason' : undefined}
                onClick={() => {
                  if (repayBlocked === null && !busy) onRepay()
                }}
              >
                Repay
              </Button>
            )}
            {repayBlocked ? (
              <Reason id="repay-reason" role="status" tone="muted" className="mt-2">
                {repayBlocked}
              </Reason>
            ) : null}
          </div>
        </TabsContent>
      </Tabs>
    </Section>
  )
}
