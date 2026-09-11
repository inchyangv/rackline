import { ethers } from 'ethers'
import { SectionCard } from '@/components/shared/section-card'
import { KeyValueList } from '@/components/shared/key-value-list'
import { KeyValueRow } from '@/components/shared/key-value-row'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Separator } from '@/components/ui/separator'
import { useApiStore } from '@/stores/api-store'
import { useDemoStore } from '@/stores/demo-store'
import { useApiClient } from '@/hooks/use-api-client'
import { isHexBytes } from '@/lib/format'
import { toast } from 'sonner'

export function OperationsTab() {
  const apiUrl = useApiStore((s) => s.apiUrl)
  const setApiUrl = useApiStore((s) => s.setApiUrl)
  const apiToken = useApiStore((s) => s.apiToken)
  const setApiToken = useApiStore((s) => s.setApiToken)
  const apiDryRun = useApiStore((s) => s.apiDryRun)
  const setApiDryRun = useApiStore((s) => s.setApiDryRun)
  const apiBusy = useApiStore((s) => s.apiBusy)
  const apiLog = useApiStore((s) => s.apiLog)
  const apiCheckpointHeight = useApiStore((s) => s.apiCheckpointHeight)
  const setApiCheckpointHeight = useApiStore((s) => s.setApiCheckpointHeight)
  const spvBorrower = useApiStore((s) => s.spvBorrower)
  const setSpvBorrower = useApiStore((s) => s.setSpvBorrower)
  const adminBtcAddr = useApiStore((s) => s.adminBtcAddr)
  const setAdminBtcAddr = useApiStore((s) => s.setAdminBtcAddr)
  const adminBorrower = useApiStore((s) => s.adminBorrower)
  const setAdminBorrower = useApiStore((s) => s.setAdminBorrower)
  const setAdminBtcKeyHash = useApiStore((s) => s.setAdminBtcKeyHash)
  const apiTxid = useApiStore((s) => s.apiTxid)
  const setApiTxid = useApiStore((s) => s.setApiTxid)
  const apiVout = useApiStore((s) => s.apiVout)
  const setApiVout = useApiStore((s) => s.setApiVout)
  const apiProofCheckpointHeight = useApiStore((s) => s.apiProofCheckpointHeight)
  const setApiProofCheckpointHeight = useApiStore((s) => s.setApiProofCheckpointHeight)
  const apiTargetHeight = useApiStore((s) => s.apiTargetHeight)
  const setApiTargetHeight = useApiStore((s) => s.setApiTargetHeight)
  const proofHex = useApiStore((s) => s.proofHex)
  const setProofHex = useApiStore((s) => s.setProofHex)
  const borrowerBtcMap = useDemoStore((s) => s.borrowerBtcMap)
  const rememberBorrowerBtcAddress = useDemoStore((s) => s.rememberBorrowerBtcAddress)
  const recordDemoBtcPayout = useDemoStore((s) => s.recordDemoBtcPayout)

  const { apiRequest, apiRun } = useApiClient()

  async function apiHealth() {
    await apiRun('GET /health', async () => apiRequest('/health', { method: 'GET' }))
  }

  async function apiSetCheckpoint() {
    const height = Number(apiCheckpointHeight)
    if (!Number.isFinite(height) || height <= 0) {
      toast.error('Invalid checkpoint height')
      return
    }
    await apiRun('POST /checkpoint/set', async () =>
      apiRequest('/checkpoint/set', {
        method: 'POST',
        body: JSON.stringify({ height, dry_run: apiDryRun }),
      }),
    )
  }

  async function apiSetBorrowerPubkeyHash() {
    if (!ethers.isAddress(spvBorrower)) {
      toast.error('Invalid borrower EVM address')
      return
    }
    if (!adminBtcAddr) {
      toast.error('BTC address is empty')
      return
    }
    await apiRun('POST /borrower/set-pubkey-hash', async () => {
      const result = await apiRequest('/borrower/set-pubkey-hash', {
        method: 'POST',
        body: JSON.stringify({ borrower: spvBorrower, btc_address: adminBtcAddr, dry_run: apiDryRun }),
      })
      if (typeof result === 'object' && result !== null && (result as Record<string, unknown>).success) {
        rememberBorrowerBtcAddress(spvBorrower, adminBtcAddr)
      }
      return result
    })
  }

  async function apiRegisterBorrower() {
    if (!ethers.isAddress(adminBorrower)) {
      toast.error('Invalid borrower EVM address')
      return
    }
    if (!adminBtcAddr) {
      toast.error('BTC address is empty')
      return
    }
    await apiRun('POST /manager/register-borrower', async () => {
      const result = await apiRequest('/manager/register-borrower', {
        method: 'POST',
        body: JSON.stringify({ borrower: adminBorrower, btc_address: adminBtcAddr, dry_run: apiDryRun }),
      })
      if (typeof result === 'object' && result !== null) {
        const r = result as Record<string, unknown>
        if (typeof r.btc_payout_key_hash === 'string') setAdminBtcKeyHash(r.btc_payout_key_hash)
        if (r.success) rememberBorrowerBtcAddress(adminBorrower, adminBtcAddr)
      }
      return result
    })
  }

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
          txid: apiTxid,
          output_index: outputIndex,
          checkpoint_height: checkpointHeight,
          target_height: targetHeight,
          borrower: spvBorrower,
        }),
      })
      if (typeof result === 'object' && result !== null) {
        const r = result as Record<string, unknown>
        if (r.success && typeof r.proof_hex === 'string') {
          setProofHex(r.proof_hex)
          const linkedBtcAddress = borrowerBtcMap[spvBorrower.toLowerCase()] ?? adminBtcAddr.trim()
          const amountSats = typeof r.amount_sats === 'number' ? r.amount_sats : null
          recordDemoBtcPayout({
            borrower: spvBorrower,
            btcAddress: linkedBtcAddress,
            txid: apiTxid.trim(),
            vout: outputIndex,
            amountSats,
            checkpointHeight,
            targetHeight,
            source: 'build',
          })
        }
      }
      return result
    })
  }

  async function apiSubmitProof() {
    if (!proofHex || !isHexBytes(proofHex) || proofHex === '0x') {
      toast.error('Invalid proof_hex')
      return
    }
    await apiRun('POST /spv/submit', async () =>
      apiRequest('/spv/submit', {
        method: 'POST',
        body: JSON.stringify({ proof_hex: proofHex, dry_run: apiDryRun }),
      }),
    )
  }

  async function apiBuildAndSubmit() {
    const outputIndex = Number(apiVout)
    const checkpointHeight = Number(apiProofCheckpointHeight)
    const targetHeight = Number(apiTargetHeight)
    if (!apiTxid || !Number.isFinite(outputIndex) || outputIndex < 0) { toast.error('txid/vout required'); return }
    if (!Number.isFinite(checkpointHeight) || checkpointHeight <= 0 || !Number.isFinite(targetHeight) || targetHeight <= 0) { toast.error('checkpoint/target required'); return }
    if (!ethers.isAddress(spvBorrower)) { toast.error('invalid borrower EVM address'); return }

    await apiRun('One-click: build-proof -> submit', async () => {
      const built = await apiRequest('/spv/build-proof', {
        method: 'POST',
        body: JSON.stringify({
          txid: apiTxid,
          output_index: outputIndex,
          checkpoint_height: checkpointHeight,
          target_height: targetHeight,
          borrower: spvBorrower,
        }),
      })
      if (!(typeof built === 'object' && built !== null && (built as Record<string, unknown>).success && typeof (built as Record<string, unknown>).proof_hex === 'string')) {
        return { build: built, submit: null }
      }
      const builtProofHex = (built as Record<string, unknown>).proof_hex as string
      setProofHex(builtProofHex)
      const submitted = await apiRequest('/spv/submit', {
        method: 'POST',
        body: JSON.stringify({ proof_hex: builtProofHex, dry_run: apiDryRun }),
      })
      const linkedBtcAddress = borrowerBtcMap[spvBorrower.toLowerCase()] ?? adminBtcAddr.trim()
      const amountSats = typeof (built as Record<string, unknown>).amount_sats === 'number' ? (built as Record<string, unknown>).amount_sats as number : null
      const submitTxHash =
        typeof submitted === 'object' && submitted !== null && typeof (submitted as Record<string, unknown>).tx_hash === 'string'
          ? (submitted as Record<string, unknown>).tx_hash as string
          : null
      recordDemoBtcPayout({
        borrower: spvBorrower,
        btcAddress: linkedBtcAddress,
        txid: apiTxid.trim(),
        vout: outputIndex,
        amountSats,
        checkpointHeight,
        targetHeight,
        source: 'build+submit',
        submitTxHash,
      })
      return { build: built, submit: submitted }
    })
  }

  return (
    <SectionCard title="SPV Demo Automation (API)" description="Calls Railway-deployed hashcredit-api. Rotate API tokens after demos." full>
      <div className="space-y-4">
        {/* API Config */}
        <div className="space-y-2">
          <div>
            <Label className="text-[10px] uppercase tracking-widest">API URL</Label>
            <Input value={apiUrl} onChange={(e) => setApiUrl(e.target.value)} placeholder="https://api-hashcredit...." className="mt-1 font-mono text-xs" />
          </div>
          <div>
            <Label className="text-[10px] uppercase tracking-widest">API Token (X-API-Key)</Label>
            <Input value={apiToken} onChange={(e) => setApiToken(e.target.value)} placeholder="(demo token)" type="password" className="mt-1 font-mono text-xs" />
          </div>
          <div className="flex items-center gap-2">
            <Checkbox id="dry-run" checked={apiDryRun} onCheckedChange={(v) => setApiDryRun(v === true)} />
            <Label htmlFor="dry-run" className="text-xs text-muted-foreground cursor-pointer">dry_run</Label>
          </div>
          <Button variant="secondary" size="sm" onClick={() => void apiHealth()} disabled={apiBusy}>Health Check</Button>
        </div>

        <Separator />

        {/* Checkpoint */}
        <div className="space-y-2">
          <div>
            <Label className="text-[10px] uppercase tracking-widest">Checkpoint height</Label>
            <Input value={apiCheckpointHeight} onChange={(e) => setApiCheckpointHeight(e.target.value)} placeholder="e.g. 4842343" className="mt-1 font-mono text-xs" />
          </div>
          <Button variant="secondary" size="sm" onClick={() => void apiSetCheckpoint()} disabled={apiBusy}>Set checkpoint (API)</Button>
        </div>

        <Separator />

        {/* Borrower Registration */}
        <div className="space-y-2">
          <div>
            <Label className="text-[10px] uppercase tracking-widest">Borrower (EVM)</Label>
            <Input value={spvBorrower} onChange={(e) => setSpvBorrower(e.target.value)} placeholder="0x..." className="mt-1 font-mono text-xs" />
          </div>
          <div>
            <Label className="text-[10px] uppercase tracking-widest">Borrower BTC Address</Label>
            <Input value={adminBtcAddr} onChange={(e) => setAdminBtcAddr(e.target.value)} placeholder="tb1..." className="mt-1 font-mono text-xs" />
          </div>
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" onClick={() => void apiSetBorrowerPubkeyHash()} disabled={apiBusy}>Set pubkeyHash (API)</Button>
          </div>
        </div>

        <Separator />

        {/* Register Borrower */}
        <div className="space-y-2">
          <div>
            <Label className="text-[10px] uppercase tracking-widest">registerBorrower: borrower</Label>
            <Input value={adminBorrower} onChange={(e) => setAdminBorrower(e.target.value)} placeholder="0x..." className="mt-1 font-mono text-xs" />
          </div>
          <Button variant="secondary" size="sm" onClick={() => void apiRegisterBorrower()} disabled={apiBusy}>registerBorrower (API)</Button>
          <p className="text-xs text-muted-foreground">API computes keccak of BTC address string.</p>
        </div>

        <Separator />

        {/* Proof Build/Submit */}
        <div className="space-y-2">
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
        </div>

        {/* API Result */}
        <KeyValueList>
          <KeyValueRow label="API Result" value={apiLog || '—'} mono pre />
        </KeyValueList>
      </div>
    </SectionCard>
  )
}
