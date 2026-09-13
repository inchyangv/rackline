import { useState } from 'react'
import { AddressDisplay } from '@/components/shared/address-display'
import { Figure } from '@/components/shared/figure'
import { Money } from '@/components/shared/money'
import { Reason } from '@/components/shared/reason'
import { Section } from '@/components/shared/section'
import type { StepState } from '@/components/shared/stepper'
import { Step, Stepper } from '@/components/shared/stepper'
import type { TagTone } from '@/components/shared/tag'
import { Tag } from '@/components/shared/tag'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { useApiClient } from '@/hooks/use-api-client'
import type { Facility } from '@/hooks/use-facility'
import { BtcSpvVerifierAbi } from '@/lib/abis'
import { copyToClipboard } from '@/lib/clipboard'
import { STABLECOIN_SYMBOL } from '@/lib/constants'
import { describeTxError, getErrorMessage } from '@/lib/ethereum'
import { sameAddress, shortAddr } from '@/lib/format'
import type { ActionCtx } from '@/lib/reasons'
import { commonReason } from '@/lib/reasons'
import { useApiStore } from '@/stores/api-store'
import { useConfigStore } from '@/stores/config-store'
import { sendContractTx } from '@/stores/tx-store'
import { useWalletStore } from '@/stores/wallet-store'

type Props = {
  facility: Facility
  viewed: string
  onView: (address: string, following: boolean) => void
}

type StageKey = 'sig' | 'chain' | 'register'
type StageState = 'idle' | 'active' | 'done' | 'failed'

const ORDER: StageKey[] = ['sig', 'chain', 'register']

const STAGE_LABEL: Record<StageKey, string> = {
  sig: 'Check signature',
  chain: 'Verify on-chain (wallet transaction)',
  register: 'Register facility',
}

const STAGE_TEXT: Record<StageState, string> = {
  idle: 'Waiting',
  active: 'In progress',
  done: 'Done',
  failed: 'Failed',
}

const STAGE_TONE: Record<StageState, TagTone> = {
  idle: 'neutral',
  active: 'signal',
  done: 'ok',
  failed: 'err',
}

const HOW_TO = [
  'Open your Bitcoin wallet’s Sign Message screen.',
  'Select the payout address you entered above.',
  'Sign the exact message below (do not edit spaces or newlines).',
  'Paste the base64 signature below.',
]

/** Values the verifier contract needs, recovered from the payout signature. */
type SigParams = {
  pubKeyX: string | number
  pubKeyY: string | number
  btcMsgHash: string | number
  v: string | number
  r: string | number
  s: string | number
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function scalar(value: unknown): string | number | null {
  if (typeof value === 'string' && value) return value
  if (typeof value === 'number' && Number.isFinite(value)) return value
  return null
}

/** The API reports its own failures in the body, so read them before trusting it. */
function apiFailure(raw: unknown, fallback: string): string | null {
  if (!isRecord(raw)) return fallback
  if (raw.success === true) return null
  const reported = scalar(raw.error)
  return reported === null ? fallback : String(reported)
}

function readSigParams(raw: unknown): { params: SigParams | null; error: string } {
  const failure = apiFailure(raw, 'The signature could not be read.')
  if (failure !== null || !isRecord(raw)) {
    return { params: null, error: failure ?? 'The signature could not be read.' }
  }
  const pubKeyX = scalar(raw.pub_key_x)
  const pubKeyY = scalar(raw.pub_key_y)
  const btcMsgHash = scalar(raw.btc_msg_hash)
  const v = scalar(raw.v)
  const r = scalar(raw.r)
  const s = scalar(raw.s)
  if (pubKeyX === null || pubKeyY === null || btcMsgHash === null || v === null || r === null || s === null) {
    return { params: null, error: 'The signature service did not return the values the verifier needs.' }
  }
  return { params: { pubKeyX, pubKeyY, btcMsgHash, v, r, s }, error: '' }
}

function resetFrom(from: StageKey): Record<StageKey, StageState> {
  const start = ORDER.indexOf(from)
  return {
    sig: ORDER.indexOf('sig') < start ? 'done' : 'idle',
    chain: ORDER.indexOf('chain') < start ? 'done' : 'idle',
    register: ORDER.indexOf('register') < start ? 'done' : 'idle',
  }
}

export function SetupPanel({ facility, viewed, onView }: Props) {
  const claimBtcAddress = useApiStore((s) => s.claimBtcAddress)
  const setClaimBtcAddress = useApiStore((s) => s.setClaimBtcAddress)
  const claimBtcSignature = useApiStore((s) => s.claimBtcSignature)
  const setClaimBtcSignature = useApiStore((s) => s.setClaimBtcSignature)

  const walletAccount = useWalletStore((s) => s.walletAccount)
  const walletChainId = useWalletStore((s) => s.walletChainId)
  const bumpRefresh = useWalletStore((s) => s.bumpRefresh)
  const chainId = useConfigStore((s) => s.chainId)
  const spvVerifierAddress = useConfigStore((s) => s.spvVerifierAddress)

  const { apiRequest } = useApiClient()

  const [stages, setStages] = useState<Record<StageKey, StageState>>(resetFrom('sig'))
  const [failedAt, setFailedAt] = useState<StageKey | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const [params, setParams] = useState<SigParams | null>(null)
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState(false)

  const { decimals } = facility

  // Checked by the API and by the verifier contract — byte for byte.
  const message = walletAccount ? `HashCredit: Link BTC to ${walletAccount}` : ''

  const ctx: ActionCtx = {
    walletAccount,
    walletChainId,
    chainId,
    viewed,
    paused: facility.paused,
  }

  const blocked =
    commonReason(ctx, { requireSameAccount: false }) ??
    (!claimBtcAddress.trim() ? 'Enter the payout address that receives your pool payouts.' : null) ??
    (!claimBtcSignature.trim() ? 'Paste the signature produced by your payout wallet.' : null)

  function setStage(key: StageKey, value: StageState) {
    setStages((prev) => ({ ...prev, [key]: value }))
  }

  function fail(key: StageKey, message_: string) {
    setStages((prev) => ({ ...prev, [key]: 'failed' }))
    setFailedAt(key)
    setFailure(message_)
  }

  async function run(from: StageKey) {
    const start = ORDER.indexOf(from)
    if (start < 0 || !walletAccount) return

    setFailure(null)
    setFailedAt(null)
    setStages(resetFrom(from))
    setBusy(true)
    try {
      let current = params

      if (start <= 0) {
        setStage('sig', 'active')
        let raw: unknown
        try {
          raw = await apiRequest('/claim/extract-sig-params', {
            method: 'POST',
            body: JSON.stringify({ message, signature_b64: claimBtcSignature.trim() }),
          })
        } catch (err) {
          fail('sig', getErrorMessage(err))
          return
        }
        const read = readSigParams(raw)
        if (!read.params) {
          fail('sig', read.error)
          return
        }
        current = read.params
        setParams(read.params)
        setStage('sig', 'done')
      }

      if (start <= 1) {
        if (!current) {
          fail('chain', 'The signature values are no longer in hand. Check the signature again.')
          return
        }
        const p = current
        setStage('chain', 'active')
        try {
          await sendContractTx('Verify payout address', spvVerifierAddress, BtcSpvVerifierAbi, (c) =>
            c.claimBtcAddress(p.pubKeyX, p.pubKeyY, p.btcMsgHash, p.v, p.r, p.s),
          )
        } catch (err) {
          fail('chain', describeTxError(err))
          return
        }
        setStage('chain', 'done')
      }

      if (start <= 2) {
        setStage('register', 'active')
        try {
          const raw = await apiRequest('/claim/register-and-grant', {
            method: 'POST',
            body: JSON.stringify({ borrower: walletAccount, btc_address: claimBtcAddress.trim() }),
          })
          const problem = apiFailure(raw, 'Registration did not complete.')
          if (problem !== null) {
            fail('register', problem)
            return
          }
        } catch (err) {
          fail('register', getErrorMessage(err))
          return
        }
        setStage('register', 'done')
        bumpRefresh()
      }
    } finally {
      setBusy(false)
    }
  }

  async function copyMessage() {
    if (!message) return
    await copyToClipboard(message)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1500)
  }

  const mismatch = Boolean(walletAccount) && Boolean(viewed) && !sameAddress(viewed, walletAccount)

  if (mismatch) {
    return (
      <Section title="Set up your facility">
        <Reason>
          Viewing <span className="num">{shortAddr(viewed)}</span>. Facility setup is only available
          for the connected wallet (<span className="num">{shortAddr(walletAccount)}</span>).
        </Reason>
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="mt-3"
          onClick={() => onView(walletAccount, true)}
        >
          View my facility
        </Button>
      </Section>
    )
  }

  const started = ORDER.some((key) => stages[key] !== 'idle')
  // Every chain-derived step describes the connected wallet's own facility.
  // Without that ownership the viewed address is a stranger's state.
  const isOwn = Boolean(walletAccount) && sameAddress(viewed, walletAccount)
  const hasLimit = isOwn && (facility.creditLimit ?? 0n) > 0n

  const connectState: StepState = walletAccount ? 'done' : 'current'
  const verifyState: StepState = !isOwn
    ? 'todo'
    : facility.isBtcLinked
      ? 'done'
      : failedAt
        ? 'attention'
        : 'current'
  const limitState: StepState = hasLimit
    ? 'done'
    : isOwn && facility.state === 'limit-not-set'
      ? 'attention'
      : 'todo'

  const doneTag = <Tag tone="ok">Done</Tag>

  return (
    <Section title="Set up your facility">
      <Stepper>
        <Step
          index={1}
          state={connectState}
          title="Connect wallet"
          meta={connectState === 'done' ? doneTag : undefined}
        />

        <Step
          index={2}
          state={verifyState}
          title="Verify payout address"
          meta={verifyState === 'done' ? doneTag : undefined}
          helper={
            <>
              <span className="block text-bone-2">
                Sign a message with the wallet that receives your pool payouts.
              </span>
              <span className="mt-0.5 block">
                This deployment uses the Bitcoin testnet payout flow. Provider settlement accounts
                (Aethir, GPU.net) are not connected here.
              </span>
            </>
          }
        >
          {verifyState === 'done' ? undefined : (
            <div className="space-y-4">
              <div>
                <Label htmlFor="payout-address">Payout address</Label>
                <Input
                  id="payout-address"
                  className="num mt-1.5 text-[13px]"
                  value={claimBtcAddress}
                  placeholder="tb1…"
                  autoComplete="off"
                  spellCheck={false}
                  onChange={(e) => setClaimBtcAddress(e.target.value.trim())}
                />
              </div>

              <ol className="space-y-1">
                {HOW_TO.map((line, i) => (
                  <li key={line} className="grid grid-cols-[1.25rem_minmax(0,1fr)] gap-1">
                    <span aria-hidden="true" className="num text-xs text-bone-3">
                      {i + 1}
                    </span>
                    <span className="text-xs leading-relaxed text-bone-2">{line}</span>
                  </li>
                ))}
              </ol>

              <div>
                <p className="text-xs leading-relaxed text-bone-3">
                  The message references HashCredit, the name of the on-chain verifier contract this
                  deployment uses. Sign it exactly as shown.
                </p>
                <div className="mt-2 flex items-center justify-between gap-2">
                  <Label htmlFor="claim-message">Message to sign</Label>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={!message}
                    onClick={() => void copyMessage()}
                  >
                    {copied ? 'Copied' : 'Copy'}
                  </Button>
                </div>
                <Textarea
                  id="claim-message"
                  readOnly
                  rows={2}
                  className="num mt-1.5 min-h-16 text-xs"
                  value={message}
                />
              </div>

              <div>
                <Label htmlFor="claim-signature">Signature</Label>
                <Textarea
                  id="claim-signature"
                  rows={2}
                  className="num mt-1.5 min-h-16 text-xs"
                  placeholder="Paste the base64 signature"
                  spellCheck={false}
                  value={claimBtcSignature}
                  onChange={(e) => setClaimBtcSignature(e.target.value)}
                />
              </div>

              <Button
                type="button"
                loading={busy}
                disabled={blocked !== null}
                onClick={() => void run('sig')}
              >
                Verify and register
              </Button>
              {blocked ? <Reason tone="muted">{blocked}</Reason> : null}

              {started ? (
                <ol className="divide-y divide-rule border-t border-rule">
                  {ORDER.map((key) => (
                    <li key={key} className="py-2">
                      <div className="flex items-baseline justify-between gap-3">
                        <span className="text-[13px] text-bone-2">{STAGE_LABEL[key]}</span>
                        <Tag tone={STAGE_TONE[stages[key]]}>{STAGE_TEXT[stages[key]]}</Tag>
                      </div>
                      {failedAt === key && failure ? (
                        <div className="mt-1.5 space-y-2">
                          <Reason tone="err">{failure}</Reason>
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            loading={busy}
                            onClick={() => void run(key)}
                          >
                            Retry from here
                          </Button>
                        </div>
                      ) : null}
                    </li>
                  ))}
                </ol>
              ) : null}
            </div>
          )}
        </Step>

        <Step
          index={3}
          state="unavailable"
          title="Payment control"
          meta={<Tag tone="neutral">Not in this deployment</Tag>}
          helper="For a production facility, settlement receivers are assigned to a controlled account so repayment is collected at source. In production this step is required before any limit is granted."
        />

        <Step
          index={4}
          state={limitState}
          title="Credit limit"
          meta={
            limitState === 'done' ? doneTag : limitState === 'attention' ? (
              <Tag tone="warn">Not set</Tag>
            ) : undefined
          }
          helper={
            <>
              On this testnet a{' '}
              <span className="num">
                <Figure>1,000.00</Figure>
              </span>{' '}
              {STABLECOIN_SYMBOL} limit is granted automatically when registration confirms.
              Production limits are set per facility from settlement history.
            </>
          }
        >
          {limitState === 'done' ? (
            <p className="text-xs text-bone-2">
              Limit granted: <Money value={facility.creditLimit} decimals={decimals} />
            </p>
          ) : limitState === 'attention' ? (
            <div className="space-y-2">
              <p className="text-xs leading-relaxed text-bone-2">
                Contact the operator desk with your address.
              </p>
              {walletAccount ? <AddressDisplay address={walletAccount} label="your" /> : null}
            </div>
          ) : undefined}
        </Step>
      </Stepper>
    </Section>
  )
}
