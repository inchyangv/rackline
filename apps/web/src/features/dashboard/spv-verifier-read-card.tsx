import { SectionCard } from '@/components/shared/section-card'
import { KeyValueList } from '@/components/shared/key-value-list'
import { KeyValueRow } from '@/components/shared/key-value-row'
import { useSpvReads } from '@/hooks/use-spv-reads'
import { useApiStore } from '@/stores/api-store'

export function SpvVerifierReadCard() {
  const spvBorrower = useApiStore((s) => s.spvBorrower)
  const { spvOwner, spvCheckpointManagerOnchain, spvBorrowerOnchainPubkeyHash } =
    useSpvReads(spvBorrower)

  return (
    <SectionCard title="SPV Verifier (Read)">
      <KeyValueList>
        <KeyValueRow label="owner" value={spvOwner || '—'} mono />
        <KeyValueRow label="checkpointManager" value={spvCheckpointManagerOnchain || '—'} mono />
        <KeyValueRow label="borrowerPubkeyHash" value={spvBorrowerOnchainPubkeyHash || '—'} mono />
      </KeyValueList>
    </SectionCard>
  )
}
