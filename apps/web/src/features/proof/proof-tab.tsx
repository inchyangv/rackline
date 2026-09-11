import { ethers } from 'ethers'
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
import { HashCreditManagerAbi } from '@/lib/abis'
import { isHexBytes } from '@/lib/format'
import { toast } from 'sonner'

export function ProofTab() {
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
      <SectionCard title="Proof Build (API)" description="Build proof from API, then submit with wallet." full>
        <div className="space-y-3">
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
