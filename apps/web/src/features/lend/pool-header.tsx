import { AddressDisplay } from '@/components/shared/address-display'
import { Section } from '@/components/shared/section'
import { Tag } from '@/components/shared/tag'
import { BRAND } from '@/lib/brand'
import { useConfigStore } from '@/stores/config-store'

/** Which pool this page is about: the vault contract, on the record. */
export function PoolHeader() {
  const vaultAddress = useConfigStore((s) => s.vaultAddress)

  return (
    <Section eyebrow="Pool" aside={<Tag tone="neutral">{BRAND.network}</Tag>}>
      <AddressDisplay address={vaultAddress} explorer label="vault" />
    </Section>
  )
}
