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
      description="Live on-chain state overview."
    >
      <div className="space-y-3">
        <div>
          <h3 className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold mb-1">Credit Manager</h3>
          <KeyValueList>
            <KeyValueRow label="Owner" value={owner || '—'} mono />
            <KeyValueRow label="Verifier" value={verifier || '—'} mono />
            <KeyValueRow label="Stablecoin" value={stablecoin || '—'} mono />
            <KeyValueRow label="Vault" value={vault || '—'} mono />
          </KeyValueList>
        </div>
        <div>
          <h3 className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold mb-1">Checkpoint</h3>
          <KeyValueList>
            <KeyValueRow label="Latest Height" value={latestCheckpointHeight ?? '—'} mono />
            <KeyValueRow
              label="Checkpoint Data"
              value={latestCheckpoint ? JSON.stringify(latestCheckpoint, null, 2) : '—'}
              mono
              pre
            />
          </KeyValueList>
        </div>
        <div>
          <h3 className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold mb-1">SPV Verifier</h3>
          <KeyValueList>
            <KeyValueRow label="Owner" value={spvOwner || '—'} mono />
            <KeyValueRow label="Checkpoint Manager" value={spvCheckpointManagerOnchain || '—'} mono />
            <KeyValueRow label="Pubkey Hash" value={spvBorrowerOnchainPubkeyHash || '—'} mono />
          </KeyValueList>
        </div>
      </div>
    </SectionCard>
  )
}
