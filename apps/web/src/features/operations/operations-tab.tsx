import { SectionCard } from '@/components/shared/section-card'
import { KeyValueList } from '@/components/shared/key-value-list'
import { KeyValueRow } from '@/components/shared/key-value-row'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { useApiStore } from '@/stores/api-store'
import { useApiClient } from '@/hooks/use-api-client'
import { useConfigStore } from '@/stores/config-store'
import { sendContractTx } from '@/stores/tx-store'
import { CheckpointManagerAbi } from '@/lib/abis'
import { toast } from 'sonner'

export function OperationsTab() {
  const apiBusy = useApiStore((s) => s.apiBusy)
  const apiLog = useApiStore((s) => s.apiLog)
  const apiCheckpointHeight = useApiStore((s) => s.apiCheckpointHeight)
  const setApiCheckpointHeight = useApiStore((s) => s.setApiCheckpointHeight)
  const checkpointManagerAddress = useConfigStore((s) => s.checkpointManagerAddress)

  const { apiRequest, apiRun } = useApiClient()

  async function buildAndSetCheckpointWithWallet() {
    const height = Number(apiCheckpointHeight)
    if (!Number.isFinite(height) || height <= 0) {
      toast.error('Invalid checkpoint height')
      return
    }

    await apiRun('POST /checkpoint/build -> wallet setCheckpoint', async () => {
      const built = await apiRequest('/checkpoint/build', {
        method: 'POST',
        body: JSON.stringify({ height }),
      })

      if (!(typeof built === 'object' && built !== null)) return built
      const payload = built as Record<string, unknown>
      if (!payload.success) return built

      if (
        typeof payload.block_hash !== 'string' ||
        typeof payload.chain_work !== 'string' ||
        typeof payload.timestamp !== 'number' ||
        typeof payload.bits !== 'number'
      ) {
        throw new Error('Invalid /checkpoint/build response payload')
      }

      const chainWorkHex = payload.chain_work.startsWith('0x')
        ? payload.chain_work
        : `0x${payload.chain_work}`

      await sendContractTx('setCheckpoint', checkpointManagerAddress, CheckpointManagerAbi, (c) =>
        c.setCheckpoint(height, payload.block_hash, chainWorkHex, payload.timestamp, payload.bits),
      )
      return { build: built, wallet: 'submitted via connected wallet (check Tx Status)' }
    })
  }

  return (
    <SectionCard
      title="Operations (Wallet + API Build)"
      description="API builds checkpoint payload. Wallet submits on-chain transaction."
      full
    >
      <div className="space-y-4">
        <div className="space-y-2">
          <div>
            <Label className="text-[10px] uppercase tracking-widest">Checkpoint height</Label>
            <Input
              value={apiCheckpointHeight}
              onChange={(e) => setApiCheckpointHeight(e.target.value)}
              placeholder="e.g. 4842343"
              className="mt-1 font-mono text-xs"
            />
          </div>
          <Button variant="secondary" size="sm" onClick={() => void buildAndSetCheckpointWithWallet()} disabled={apiBusy}>
            Build + setCheckpoint (Wallet)
          </Button>
          <p className="text-xs text-muted-foreground">
            Borrower mapping and payout submission are wallet-only in Admin / Proof tabs.
          </p>
        </div>

        <KeyValueList>
          <KeyValueRow label="API Result" value={apiLog || '—'} mono pre />
        </KeyValueList>
      </div>
    </SectionCard>
  )
}
