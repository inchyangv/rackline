import { SectionCard } from '@/components/shared/section-card'
import { KeyValueList } from '@/components/shared/key-value-list'
import { KeyValueRow } from '@/components/shared/key-value-row'
import { useManagerReads } from '@/hooks/use-manager-reads'
import { useCheckpointReads } from '@/hooks/use-checkpoint-reads'
import { useSpvReads } from '@/hooks/use-spv-reads'
import { useApiStore } from '@/stores/api-store'

export function ProtocolStatusCard() {
  const { owner, verifier, stablecoin, vault } = useManagerReads()
  const { latestCheckpointHeight, latestCheckpoint } = useCheckpointReads()
  const spvBorrower = useApiStore((s) => s.spvBorrower)
  const { spvOwner, spvCheckpointManagerOnchain, spvBorrowerOnchainPubkeyHash } =
    useSpvReads(spvBorrower)

  return (
    <SectionCard
      title="Protocol Status"
      description="Manager, Checkpoint, and SPV Verifier on-chain state."
    >
      <div className="space-y-3">
        <div>
          <h3 className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold mb-1">Manager</h3>
          <KeyValueList>
            <KeyValueRow label="owner" value={owner || '—'} mono />
            <KeyValueRow label="verifier" value={verifier || '—'} mono />
            <KeyValueRow label="stablecoin" value={stablecoin || '—'} mono />
            <KeyValueRow label="vault" value={vault || '—'} mono />
          </KeyValueList>
        </div>
        <div>
          <h3 className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold mb-1">Checkpoint</h3>
          <KeyValueList>
            <KeyValueRow label="latestCheckpointHeight" value={latestCheckpointHeight ?? '—'} mono />
            <KeyValueRow
              label="latestCheckpoint"
              value={latestCheckpoint ? JSON.stringify(latestCheckpoint, null, 2) : '—'}
              mono
              pre
            />
          </KeyValueList>
        </div>
        <div>
          <h3 className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold mb-1">SPV Verifier</h3>
          <KeyValueList>
            <KeyValueRow label="owner" value={spvOwner || '—'} mono />
            <KeyValueRow label="checkpointManager" value={spvCheckpointManagerOnchain || '—'} mono />
            <KeyValueRow label="borrowerPubkeyHash" value={spvBorrowerOnchainPubkeyHash || '—'} mono />
          </KeyValueList>
        </div>
      </div>
    </SectionCard>
  )
}
