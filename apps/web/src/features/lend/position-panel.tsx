import { Ledger, LedgerRow } from '@/components/shared/ledger'
import { Money } from '@/components/shared/money'
import { Reason } from '@/components/shared/reason'
import { Section } from '@/components/shared/section'
import type { VaultInfo } from '@/hooks/use-vault-info'
import { useWalletStore } from '@/stores/wallet-store'

type Props = {
  vault: VaultInfo
  decimals: number
}

function lower(a: bigint | null, b: bigint | null): bigint | null {
  if (a === null || b === null) return null
  return a < b ? a : b
}

export function PositionPanel({ vault, decimals }: Props) {
  const walletAccount = useWalletStore((s) => s.walletAccount)
  const withdrawable = lower(vault.myShareValue, vault.availableLiquidity)

  return (
    <Section eyebrow="Position · connected wallet">
      {walletAccount ? (
        <Ledger>
          <LedgerRow
            label="Shares"
            value={<Money value={vault.myShares} decimals={decimals} unit={null} />}
            loading={vault.isLoading}
          />
          <LedgerRow
            label="Book value"
            value={<Money value={vault.myShareValue} decimals={decimals} />}
            loading={vault.isLoading}
          />
          <LedgerRow
            label="Withdrawable now"
            value={<Money value={withdrawable} decimals={decimals} />}
            loading={vault.isLoading}
          />
        </Ledger>
      ) : (
        <Reason>Connect a wallet to see your position.</Reason>
      )}
    </Section>
  )
}
