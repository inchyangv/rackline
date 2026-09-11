import { SectionCard } from '@/components/shared/section-card'
import { KeyValueList } from '@/components/shared/key-value-list'
import { KeyValueRow } from '@/components/shared/key-value-row'
import { useCheckpointReads } from '@/hooks/use-checkpoint-reads'

export function CheckpointReadCard() {
  const { latestCheckpointHeight, latestCheckpoint } = useCheckpointReads()

  return (
    <SectionCard title="Checkpoint (Read)">
      <KeyValueList>
        <KeyValueRow label="latestCheckpointHeight" value={latestCheckpointHeight ?? '—'} mono />
        <KeyValueRow
          label="latestCheckpoint"
          value={latestCheckpoint ? JSON.stringify(latestCheckpoint, null, 2) : '—'}
          mono
          pre
        />
      </KeyValueList>
    </SectionCard>
  )
}
