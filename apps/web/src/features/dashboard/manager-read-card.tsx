import { SectionCard } from '@/components/shared/section-card'
import { KeyValueList } from '@/components/shared/key-value-list'
import { KeyValueRow } from '@/components/shared/key-value-row'
import { useManagerReads } from '@/hooks/use-manager-reads'

export function ManagerReadCard() {
  const { owner, verifier, stablecoin, vault } = useManagerReads()

  return (
    <SectionCard
      title="Manager (Read)"
      description="Operational flow: set checkpoint, set pubkeyHash, registerBorrower, then build/submit proof."
    >
      <KeyValueList>
        <KeyValueRow label="owner" value={owner || '—'} mono />
        <KeyValueRow label="verifier" value={verifier || '—'} mono />
        <KeyValueRow label="stablecoin" value={stablecoin || '—'} mono />
        <KeyValueRow label="vault" value={vault || '—'} mono />
      </KeyValueList>
    </SectionCard>
  )
}
