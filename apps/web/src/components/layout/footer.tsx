import type { ReactNode } from 'react'
import { AddressDisplay } from '@/components/shared/address-display'
import { BRAND } from '@/lib/brand'
import { getRpcHost } from '@/lib/explorer'
import { useConfigStore } from '@/stores/config-store'

function Column({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <p className="eyebrow">{title}</p>
      <div className="mt-3 grid gap-2">{children}</div>
    </div>
  )
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-h-6 flex-wrap items-center justify-between gap-x-3 gap-y-0.5">
      <span className="shrink-0 text-bone-3">{label}</span>
      <span className="min-w-0 text-right text-bone-2">{children}</span>
    </div>
  )
}

/** `[&>span]:text-xs` steps the address down to footer size (12px). */
const footerAddress = 'text-xs [&>span]:text-xs'

export function Footer() {
  const managerAddress = useConfigStore((s) => s.managerAddress)
  const vaultAddress = useConfigStore((s) => s.vaultAddress)
  const stablecoinAddress = useConfigStore((s) => s.stablecoinAddress)
  const chainId = useConfigStore((s) => s.chainId)

  return (
    <footer className="mx-auto w-full max-w-[1120px] px-4 sm:px-6">
      <div className="border-t border-rule pt-8 pb-10 text-xs">
        <div className="grid gap-8 sm:grid-cols-3">
          <Column title="Contracts">
            <Row label="Manager">
              <AddressDisplay
                address={managerAddress}
                explorer
                label="Manager"
                className={footerAddress}
              />
            </Row>
            <Row label="Vault">
              <AddressDisplay
                address={vaultAddress}
                explorer
                label="Vault"
                className={footerAddress}
              />
            </Row>
            <Row label="Token">
              <AddressDisplay
                address={stablecoinAddress}
                explorer
                label="Token"
                className={footerAddress}
              />
            </Row>
          </Column>

          <Column title="Network">
            <Row label="Chain id">
              <span className="num">{chainId}</span>
            </Row>
            <Row label="RPC host">
              <span className="num break-words">{getRpcHost()}</span>
            </Row>
            <Row label="Build">
              <span className="num">{__APP_COMMIT__}</span>
            </Row>
          </Column>

          <Column title="Legal">
            <p className="leading-relaxed text-bone-3">{BRAND.legal}</p>
            <p className="leading-relaxed text-bone-3">
              Contracts shown are the Bitcoin-payout testnet deployment; GPU settlement integration
              is not live.
            </p>
          </Column>
        </div>

        <p className="mt-8 text-bone-3">
          © <span className="num">{new Date().getFullYear()}</span> {BRAND.name}
        </p>
      </div>
    </footer>
  )
}
