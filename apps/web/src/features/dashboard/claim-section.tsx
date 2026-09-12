import { ethers } from 'ethers'
import { ChevronDown, ChevronRight, CheckCircle2 } from 'lucide-react'
import { SectionCard } from '@/components/shared/section-card'
import { KeyValueList } from '@/components/shared/key-value-list'
import { KeyValueRow } from '@/components/shared/key-value-row'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { useApiStore } from '@/stores/api-store'
import { useWalletStore } from '@/stores/wallet-store'
import { useConfigStore } from '@/stores/config-store'
import { useApiClient } from '@/hooks/use-api-client'
import { sendContractTx } from '@/stores/tx-store'
import { BtcSpvVerifierAbi } from '@/lib/abis'
import { getErrorMessage } from '@/lib/ethereum'
import { copyToClipboard } from '@/lib/clipboard'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'

type StepState = 'pending' | 'active' | 'done'

function StepHeader({
  num,
  label,
  state,
  expanded,
  onToggle,
}: {
  num: number
  label: string
  state: StepState
  expanded: boolean
  onToggle: () => void
}) {
  return (
    <button
      className={cn(
        'flex w-full items-center gap-3 px-4 py-3 text-left transition-colors',
        state === 'pending' && 'cursor-default opacity-50',
        state !== 'pending' && 'hover:bg-card/60',
      )}
      onClick={onToggle}
      disabled={state === 'pending'}
    >
      <span
        className={cn(
          'flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full text-[10px] font-bold',
          state === 'done'
            ? 'bg-emerald-500/20 text-emerald-400'
            : state === 'active'
              ? 'bg-primary/20 text-primary'
              : 'bg-muted/40 text-muted-foreground',
        )}
      >
        {state === 'done' ? <CheckCircle2 className="h-3.5 w-3.5" /> : num}
      </span>
      <span
        className={cn(
          'text-xs font-semibold flex-1',
          state === 'done' ? 'text-emerald-400/80 line-through' : 'text-foreground/90',
        )}
      >
        {label}
      </span>
      {state !== 'pending' && (
        expanded ? (
          <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
        )
      )}
    </button>
  )
}

export function ClaimSection() {
  const claimBtcAddress = useApiStore((s) => s.claimBtcAddress)
  const setClaimBtcAddress = useApiStore((s) => s.setClaimBtcAddress)
  const claimBtcSignature = useApiStore((s) => s.claimBtcSignature)
  const setClaimBtcSignature = useApiStore((s) => s.setClaimBtcSignature)
  const claimLog = useApiStore((s) => s.claimLog)
  const setClaimLog = useApiStore((s) => s.setClaimLog)
  const claimBusy = useApiStore((s) => s.claimBusy)
  const setClaimBusy = useApiStore((s) => s.setClaimBusy)
  const borrowerAddress = useApiStore((s) => s.borrowerAddress)
  const walletAccount = useWalletStore((s) => s.walletAccount)
  const spvVerifierAddress = useConfigStore((s) => s.spvVerifierAddress)

  const { apiRequest } = useApiClient()

  const borrower = borrowerAddress || walletAccount
  const claimMessage = borrower ? `HashCredit: Link BTC to ${borrower}` : ''
  const canSubmit =
    !!claimBtcAddress && !!claimBtcSignature.trim() && ethers.isAddress(borrower)

  // Step gating
  const step1Done = !!claimBtcAddress
  const step2Done = !!claimBtcSignature.trim()

  // Which step is expanded: default to first incomplete step
  const activeStep = !step1Done ? 1 : !step2Done ? 2 : 3

  function getStepState(n: number): StepState {
    if (n === 1) return step1Done ? 'done' : 'active'
    if (n === 2) return step2Done ? 'done' : step1Done ? 'active' : 'pending'
    return step2Done ? 'active' : 'pending'
  }

  // Only the current active step is expanded
  const useLocalExpanded = (n: number) => {
    return n === activeStep
  }

  async function copyClaimMessage() {
    if (!claimMessage) {
      toast.error('Connect wallet or enter borrower address first')
      return
    }
    await copyToClipboard(claimMessage)
    toast.success('Message copied')
  }

  async function verifyAndRegister() {
    if (!ethers.isAddress(borrower)) {
      toast.error('Connect wallet or enter a borrower address first')
      return
    }
    if (!claimBtcAddress) {
      toast.error('Enter your BTC address')
      return
    }
    if (!claimBtcSignature.trim()) {
      toast.error('Paste the BTC signature (base64)')
      return
    }

    setClaimBusy(true)
    setClaimLog('')
    try {
      setClaimLog('Step 1/3: Extracting signature parameters...')
      const result = await apiRequest('/claim/extract-sig-params', {
        method: 'POST',
        body: JSON.stringify({
          message: claimMessage,
          signature_b64: claimBtcSignature.trim(),
        }),
      })
      const params = result as Record<string, unknown>
      if (!params.success) {
        setClaimLog(`Error: ${params.error}`)
        toast.error(String(params.error))
        return
      }

      setClaimLog('Step 2/3: Verifying BTC signature on-chain...')
      await sendContractTx(
        'claimBtcAddress',
        spvVerifierAddress,
        BtcSpvVerifierAbi,
        (c) =>
          c.claimBtcAddress(
            params.pub_key_x,
            params.pub_key_y,
            params.btc_msg_hash,
            params.v,
            params.r,
            params.s,
          ),
      )

      setClaimLog('Step 3/3: Registering borrower & granting credit...')
      const regResult = await apiRequest('/claim/register-and-grant', {
        method: 'POST',
        body: JSON.stringify({
          borrower,
          btc_address: claimBtcAddress,
        }),
      })
      const regData = regResult as Record<string, unknown>
      if (!regData.success) {
        setClaimLog(`Error: ${regData.error}`)
        toast.error(String(regData.error))
        return
      }

      setClaimLog(
        `Done!\n` +
          `  BTC signature verified on-chain (secp256k1 ecrecover)\n` +
          `  BTC address: ${claimBtcAddress}\n` +
          `  Borrower registered with ${regData.credit_amount} credit\n` +
          `  Register tx: ${regData.register_tx}\n` +
          `  Grant tx: ${regData.grant_tx}`,
      )
      toast.success('BTC wallet linked & borrower registered!')
    } catch (e) {
      setClaimLog(`Error: ${getErrorMessage(e)}`)
      toast.error(getErrorMessage(e))
    } finally {
      setClaimBusy(false)
    }
  }

  return (
    <SectionCard
      title="Link BTC Wallet"
      description="Complete 3 steps to connect your Bitcoin identity and unlock borrowing."
    >
      <div className="divide-y divide-border/25 -mx-6 -mb-6">
        {/* Step 1: BTC Address */}
        <div>
          <StepHeader
            num={1}
            label="Enter your BTC address"
            state={getStepState(1)}
            expanded={useLocalExpanded(1)}
            onToggle={() => {}}
          />
          {useLocalExpanded(1) && (
            <div className="px-4 pb-4 space-y-2">
              <p className="text-xs text-muted-foreground">
                Copy your Bitcoin address from your wallet (e.g. MetaMask Bitcoin extension).
              </p>
              <Input
                value={claimBtcAddress}
                onChange={(e) => setClaimBtcAddress(e.target.value.trim())}
                placeholder="tb1q... or bc1q..."
                className="font-mono text-xs"
              />
            </div>
          )}
        </div>

        {/* Step 2: Sign Message */}
        <div>
          <StepHeader
            num={2}
            label="Sign message with your BTC wallet"
            state={getStepState(2)}
            expanded={useLocalExpanded(2)}
            onToggle={() => {}}
          />
          {useLocalExpanded(2) && (
            <div className="px-4 pb-4 space-y-3">
              <div className="rounded-lg border border-border/40 bg-secondary/20 p-3 text-xs text-muted-foreground">
                <p className="font-medium text-foreground mb-1">How to sign the message</p>
                <ol className="list-decimal space-y-1 pl-4">
                  <li>Open your BTC wallet&apos;s <span className="font-medium">Sign Message</span> screen.</li>
                  <li>Select the same BTC address you entered in Step 1.</li>
                  <li>Sign the exact message below — do not change any characters.</li>
                  <li>Paste the base64 signature in the field below.</li>
                </ol>
              </div>
              <div>
                <div className="flex items-center justify-between mb-1">
                  <Label className="text-[11px] uppercase tracking-wider">Message to sign (exact)</Label>
                  <Button
                    variant="secondary"
                    size="xs"
                    onClick={() => void copyClaimMessage()}
                    disabled={!claimMessage}
                  >
                    Copy
                  </Button>
                </div>
                <Textarea
                  value={
                    claimMessage || 'Connect wallet or enter borrower address to generate message'
                  }
                  readOnly
                  rows={2}
                  className="font-mono text-xs bg-secondary/30"
                />
              </div>
              <div>
                <Label className="text-[11px] uppercase tracking-wider">BTC Signature (base64)</Label>
                <Textarea
                  value={claimBtcSignature}
                  onChange={(e) => setClaimBtcSignature(e.target.value)}
                  placeholder="Paste base64 signature from your BTC wallet..."
                  rows={2}
                  className="mt-1 font-mono text-xs"
                />
              </div>
            </div>
          )}
        </div>

        {/* Step 3: Verify & Register */}
        <div>
          <StepHeader
            num={3}
            label="Verify on-chain & unlock credit"
            state={getStepState(3)}
            expanded={useLocalExpanded(3)}
            onToggle={() => {}}
          />
          {useLocalExpanded(3) && (
            <div className="px-4 pb-4 space-y-3">
              <p className="text-xs text-muted-foreground">
                Your BTC signature is verified on-chain via secp256k1 ecrecover. You&apos;ll receive
                1,000 mUSDT testnet credit upon success.
              </p>
              <Button
                size="sm"
                onClick={() => void verifyAndRegister()}
                disabled={claimBusy || !canSubmit}
              >
                {claimBusy ? 'Processing...' : 'Verify & Register'}
              </Button>
            </div>
          )}
        </div>

        {/* Log output */}
        {claimLog && (
          <div className="px-4 py-3">
            <KeyValueList>
              <KeyValueRow label="Status" value={claimLog} mono pre />
            </KeyValueList>
          </div>
        )}
      </div>
    </SectionCard>
  )
}
