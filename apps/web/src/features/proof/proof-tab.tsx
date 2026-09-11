import { ethers } from 'ethers'
import { SectionCard } from '@/components/shared/section-card'
import { KeyValueList } from '@/components/shared/key-value-list'
import { KeyValueRow } from '@/components/shared/key-value-row'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Separator } from '@/components/ui/separator'
import { useApiStore } from '@/stores/api-store'
import { useWalletStore } from '@/stores/wallet-store'
import { useConfigStore } from '@/stores/config-store'
import { useApiClient } from '@/hooks/use-api-client'
import { sendContractTx } from '@/stores/tx-store'
import { HashCreditManagerAbi } from '@/lib/abis'
import { isHexBytes } from '@/lib/format'
import { toast } from 'sonner'

export function ProofTab() {
  const apiUrl = useApiStore((s) => s.apiUrl)
  const setApiUrl = useApiStore((s) => s.setApiUrl)
  const apiToken = useApiStore((s) => s.apiToken)
  const setApiToken = useApiStore((s) => s.setApiToken)
  const apiDryRun = useApiStore((s) => s.apiDryRun)
  const setApiDryRun = useApiStore((s) => s.setApiDryRun)
  const apiBusy = useApiStore((s) => s.apiBusy)
  const apiLog = useApiStore((s) => s.apiLog)
  const apiTxid = useApiStore((s) => s.apiTxid)
  const setApiTxid = useApiStore((s) => s.setApiTxid)
  const apiVout = useApiStore((s) => s.apiVout)
  const setApiVout = useApiStore((s) => s.setApiVout)
  const apiProofCheckpointHeight = useApiStore((s) => s.apiProofCheckpointHeight)
  const setApiProofCheckpointHeight = useApiStore((s) => s.setApiProofCheckpointHeight)
  const apiTargetHeight = useApiStore((s) => s.apiTargetHeight)
  const setApiTargetHeight = useApiStore((s) => s.setApiTargetHeight)
  const spvBorrower = useApiStore((s) => s.spvBorrower)
  const proofHex = useApiStore((s) => s.proofHex)
  const setProofHex = useApiStore((s) => s.setProofHex)
  const walletAccount = useWalletStore((s) => s.walletAccount)
  const managerAddress = useConfigStore((s) => s.managerAddress)

  const { apiRequest, apiRun } = useApiClient()

  async function apiBuildProof() {
    const outputIndex = Number(apiVout)
    const checkpointHeight = Number(apiProofCheckpointHeight)
    const targetHeight = Number(apiTargetHeight)
    if (!apiTxid) { toast.error('txid is empty'); return }
    if (!Number.isFinite(outputIndex) || outputIndex < 0) { toast.error('invalid vout'); return }
    if (!Number.isFinite(checkpointHeight) || checkpointHeight <= 0) { toast.error('invalid checkpoint_height'); return }
    if (!Number.isFinite(targetHeight) || targetHeight <= 0) { toast.error('invalid target_height'); return }
    if (!ethers.isAddress(spvBorrower)) { toast.error('invalid borrower EVM address'); return }

    await apiRun('POST /spv/build-proof', async () => {
      const result = await apiRequest('/spv/build-proof', {
        method: 'POST',
        body: JSON.stringify({
          txid: apiTxid, output_index: outputIndex,
          checkpoint_height: checkpointHeight, target_height: targetHeight, borrower: spvBorrower,
        }),
      })
      if (typeof result === 'object' && result !== null) {
        const r = result as Record<string, unknown>
        if (r.success && typeof r.proof_hex === 'string') {
          setProofHex(r.proof_hex)
        }
      }
      return result
    })
  }

  async function apiSubmitProof() {
    if (!proofHex || !isHexBytes(proofHex) || proofHex === '0x') { toast.error('Invalid proof_hex'); return }
    await apiRun('POST /spv/submit', async () =>
      apiRequest('/spv/submit', { method: 'POST', body: JSON.stringify({ proof_hex: proofHex, dry_run: apiDryRun }) }),
    )
  }

  async function apiBuildAndSubmit() {
    const outputIndex = Number(apiVout)
    const checkpointHeight = Number(apiProofCheckpointHeight)
    const targetHeight = Number(apiTargetHeight)
    if (!apiTxid || !Number.isFinite(outputIndex) || outputIndex < 0) { toast.error('txid/vout required'); return }
    if (!Number.isFinite(checkpointHeight) || checkpointHeight <= 0 || !Number.isFinite(targetHeight) || targetHeight <= 0) { toast.error('checkpoint/target required'); return }
    if (!ethers.isAddress(spvBorrower)) { toast.error('invalid borrower'); return }

    await apiRun('One-click: build-proof -> submit', async () => {
      const built = await apiRequest('/spv/build-proof', {
        method: 'POST',
        body: JSON.stringify({ txid: apiTxid, output_index: outputIndex, checkpoint_height: checkpointHeight, target_height: targetHeight, borrower: spvBorrower }),
      })
      if (!(typeof built === 'object' && built !== null && (built as Record<string, unknown>).success && typeof (built as Record<string, unknown>).proof_hex === 'string')) {
        return { build: built, submit: null }
      }
      const builtProofHex = (built as Record<string, unknown>).proof_hex as string
      setProofHex(builtProofHex)
      const submitted = await apiRequest('/spv/submit', { method: 'POST', body: JSON.stringify({ proof_hex: builtProofHex, dry_run: apiDryRun }) })
      return { build: built, submit: submitted }
    })
  }

  async function submitProof() {
    if (!proofHex || !isHexBytes(proofHex) || proofHex === '0x') {
      toast.error('Invalid proofHex. (0x...)')
      return
    }
    toast.promise(
      sendContractTx('submitPayout', managerAddress, HashCreditManagerAbi, (c) => c.submitPayout(proofHex)),
      { loading: 'Submitting payout...', success: 'Payout submitted!', error: 'Submit failed' },
    )
  }

  return (
    <>
      <SectionCard title="Proof Build/Submit (API)" description="If API URL/TOKEN is empty, configure in Operations tab." full>
        <div className="space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <div>
              <Label className="text-[10px] uppercase tracking-widest">API URL</Label>
              <Input value={apiUrl} onChange={(e) => setApiUrl(e.target.value)} placeholder="https://api-hashcredit...." className="mt-1 font-mono text-xs" />
            </div>
            <div>
              <Label className="text-[10px] uppercase tracking-widest">API Token</Label>
              <Input value={apiToken} onChange={(e) => setApiToken(e.target.value)} placeholder="(demo token)" type="password" className="mt-1 font-mono text-xs" />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Checkbox id="dry-run-proof" checked={apiDryRun} onCheckedChange={(v) => setApiDryRun(v === true)} />
            <Label htmlFor="dry-run-proof" className="text-xs text-muted-foreground cursor-pointer">dry_run</Label>
          </div>

          <Separator />

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <div>
              <Label className="text-[10px] uppercase tracking-widest">txid</Label>
              <Input value={apiTxid} onChange={(e) => setApiTxid(e.target.value.trim())} placeholder="e.g. e4c6..." className="mt-1 font-mono text-xs" />
            </div>
            <div>
              <Label className="text-[10px] uppercase tracking-widest">vout</Label>
              <Input value={apiVout} onChange={(e) => setApiVout(e.target.value)} placeholder="0" className="mt-1 font-mono text-xs" />
            </div>
            <div>
              <Label className="text-[10px] uppercase tracking-widest">checkpoint_height</Label>
              <Input value={apiProofCheckpointHeight} onChange={(e) => setApiProofCheckpointHeight(e.target.value)} placeholder="e.g. 4842333" className="mt-1 font-mono text-xs" />
            </div>
            <div>
              <Label className="text-[10px] uppercase tracking-widest">target_height</Label>
              <Input value={apiTargetHeight} onChange={(e) => setApiTargetHeight(e.target.value)} placeholder="e.g. 4842343" className="mt-1 font-mono text-xs" />
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" size="sm" onClick={() => void apiBuildProof()} disabled={apiBusy}>Build proof (API)</Button>
            <Button variant="secondary" size="sm" onClick={() => void apiSubmitProof()} disabled={apiBusy}>Submit proof (API)</Button>
            <Button size="sm" onClick={() => void apiBuildAndSubmit()} disabled={apiBusy}>One-click (build + submit)</Button>
          </div>
          <KeyValueList>
            <KeyValueRow label="API Result" value={apiLog || '—'} mono pre />
          </KeyValueList>
        </div>
      </SectionCard>

      <SectionCard title="submitPayout (Wallet)" description="If proof is built via API, buttons above auto-fill proofHex." full>
        <div className="space-y-3">
          <Textarea
            value={proofHex}
            onChange={(e) => setProofHex(e.target.value.trim())}
            placeholder="0x..."
            rows={6}
            className="font-mono text-xs"
          />
          <Button size="sm" onClick={() => void submitProof()} disabled={!walletAccount}>
            submitPayout
          </Button>
        </div>
      </SectionCard>
    </>
  )
}
