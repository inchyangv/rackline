import { Logo } from '@/components/shared/logo'
import { Button } from '@/components/ui/button'
import { BRAND } from '@/lib/brand'
import { getEthereum } from '@/lib/ethereum'
import { shortAddr } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useConfigStore } from '@/stores/config-store'
import { useWalletStore } from '@/stores/wallet-store'
import type { TabId } from '@/types'

const TABS: { id: TabId; label: string }[] = [
  { id: 'borrow', label: 'Borrow' },
  { id: 'lend', label: 'Lend' },
]

// The section nav is navigation, not a tab widget: plain buttons in a <nav>,
// carrying the same `data-state` the Tabs triggers used so the visual is
// unchanged. The classes below are the TabsTrigger `line` / `segmented`
// strings with the group selectors resolved for this one context.
const NAV_ITEM =
  'relative inline-flex items-center justify-center rounded-none text-[13px] font-medium whitespace-nowrap text-bone-2 transition-colors hover:text-bone data-[state=active]:text-bone'

/** Desktop: plain text, 2px signal rule under the active section. */
const NAV_LINE = cn(
  NAV_ITEM,
  'py-2 after:absolute after:inset-x-0 after:bottom-0 after:h-0.5 after:bg-signal after:opacity-0 data-[state=active]:after:opacity-100',
)

/** <640px: flush cells inside the full-width segmented control. */
const NAV_SEGMENT = cn(NAV_ITEM, 'h-full px-3 data-[state=active]:bg-ink-2')

const NAV_SEGMENT_LIST =
  'inline-grid h-9 w-full auto-cols-fr grid-flow-col overflow-hidden rounded-md border border-rule-strong'

type Props = {
  tab: TabId
  onTabChange: (tab: TabId) => void
  /** Drives the bottom rule of the mark: drawn share, or pool utilization. */
  gauge?: number | null
}

/**
 * The one piece of persistent chrome: mark, section nav, network, wallet.
 * 48px, not sticky — the page scrolls past it.
 */
export function TopBar({ tab, onTabChange, gauge = null }: Props) {
  const walletAccount = useWalletStore((s) => s.walletAccount)
  const walletChainId = useWalletStore((s) => s.walletChainId)
  const connectWallet = useWalletStore((s) => s.connectWallet)
  const disconnectWallet = useWalletStore((s) => s.disconnectWallet)
  const chainId = useConfigStore((s) => s.chainId)

  const hasWallet = getEthereum() !== null
  const wrongNetwork = walletChainId !== null && walletChainId !== chainId
  const networkLabel = wrongNetwork
    ? `Wrong network · ${walletChainId}`
    : `${BRAND.network} · ${chainId}`

  return (
    <>
      <header className="h-12 border-b border-rule bg-ink-0">
        <div className="mx-auto flex h-full w-full max-w-[1120px] items-center gap-4 px-4 sm:gap-6 sm:px-6">
          <Logo gauge={gauge} />

          <nav aria-label="Sections" className="hidden w-fit items-center gap-4 sm:flex">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                aria-current={tab === t.id ? 'page' : undefined}
                data-state={tab === t.id ? 'active' : 'inactive'}
                className={NAV_LINE}
                onClick={() => onTabChange(t.id)}
              >
                {t.label}
              </button>
            ))}
          </nav>

          <div className="ml-auto flex min-w-0 items-center gap-3 sm:gap-4">
            {/* <640px: the network reads as a dot; the label stays available to
                screen readers and as a tooltip. */}
            <span title={networkLabel} className="flex shrink-0 items-center sm:hidden">
              <span
                aria-hidden="true"
                className={cn('size-2 rounded-full', wrongNetwork ? 'bg-warn' : 'bg-bone-3')}
              />
              <span className="sr-only">{networkLabel}</span>
            </span>

            <span
              className={cn(
                'hidden shrink-0 text-xs sm:inline',
                wrongNetwork ? 'text-warn' : 'text-bone-2',
              )}
            >
              {networkLabel}
            </span>

            {walletAccount ? (
              <>
                <span title={walletAccount} className="num hidden text-[13px] sm:inline">
                  {shortAddr(walletAccount)}
                </span>
                <Button type="button" variant="outline" size="sm" onClick={disconnectWallet}>
                  Disconnect
                </Button>
              </>
            ) : (
              <>
                {/* The control stays focusable and says why it cannot be used;
                    below 640px the reason is read out rather than shown. */}
                {hasWallet ? null : (
                  <span
                    id="no-wallet-reason"
                    className="shrink-0 text-xs text-bone-3 max-sm:sr-only"
                  >
                    No browser wallet found.
                  </span>
                )}
                <Button
                  type="button"
                  variant="default"
                  size="sm"
                  aria-disabled={!hasWallet || undefined}
                  aria-describedby={hasWallet ? undefined : 'no-wallet-reason'}
                  onClick={() => {
                    if (hasWallet) void connectWallet()
                  }}
                >
                  Connect wallet
                </Button>
              </>
            )}
          </div>
        </div>
      </header>

      {/* <640px: the nav leaves the bar and becomes a full-width control. */}
      <div className="border-b border-rule px-4 py-2 sm:hidden">
        <nav aria-label="Sections" className={NAV_SEGMENT_LIST}>
          {TABS.map((t, i) => (
            <button
              key={t.id}
              type="button"
              aria-current={tab === t.id ? 'page' : undefined}
              data-state={tab === t.id ? 'active' : 'inactive'}
              className={cn(NAV_SEGMENT, i > 0 && 'border-l border-rule')}
              onClick={() => onTabChange(t.id)}
            >
              {t.label}
            </button>
          ))}
        </nav>
      </div>
    </>
  )
}
