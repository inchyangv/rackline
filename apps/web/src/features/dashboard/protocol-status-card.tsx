import { ethers } from 'ethers'
import { SectionCard } from '@/components/shared/section-card'
import { KeyValueList } from '@/components/shared/key-value-list'
import { KeyValueRow } from '@/components/shared/key-value-row'
import { useManagerReads } from '@/hooks/use-manager-reads'
import { useCheckpointReads } from '@/hooks/use-checkpoint-reads'
import { useSpvReads } from '@/hooks/use-spv-reads'
import { useApiStore } from '@/stores/api-store'
import { useWalletStore } from '@/stores/wallet-store'

export function ProtocolStatusCard() {
  const { owner, verifier, stablecoin, vault } = useManagerReads()
  const { latestCheckpointHeight, latestCheckpoint } = useCheckpointReads()
  const borrowerAddress = useApiStore((s) => s.borrowerAddress)
  const spvBorrower = useApiStore((s) => s.spvBorrower)
  const walletAccount = useWalletStore((s) => s.walletAccount)

  const lookupBorrower = ethers.isAddress(spvBorrower)
    ? spvBorrower
    : ethers.isAddress(borrowerAddress)
      ? borrowerAddress
      : ethers.isAddress(walletAccount)
        ? walletAccount
        : ''

  const { spvOwner, spvCheckpointManagerOnchain, spvBorrowerOnchainPubkeyHash } =
    useSpvReads(lookupBorrower)

  const ZERO_BYTES20 = '0x0000000000000000000000000000000000000000'
  const pubkeyHashDisplay = !lookupBorrower
    ? 'Borrower address required'
    : spvBorrowerOnchainPubkeyHash === ZERO_BYTES20
      ? 'Not registered yet'
      : (spvBorrowerOnchainPubkeyHash || '—')

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
            <KeyValueRow label="Borrower (lookup)" value={lookupBorrower || '—'} mono />
            <KeyValueRow label="Pubkey Hash" value={pubkeyHashDisplay} mono />
          </KeyValueList>
        </div>
      </div>
    </SectionCard>
  )
}
