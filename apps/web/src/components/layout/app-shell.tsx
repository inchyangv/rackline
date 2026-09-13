import { useEffect, useState } from 'react'
import { TxStrip } from '@/components/shared/tx-strip'
import { BorrowPage } from '@/features/borrow/borrow-page'
import { LendPage } from '@/features/lend/lend-page'
import { STORAGE_KEYS } from '@/lib/brand'
import { getEthereum } from '@/lib/ethereum'
import { getLocalStorageString, setLocalStorageString } from '@/lib/storage'
import { useApiStore } from '@/stores/api-store'
import { useWalletStore } from '@/stores/wallet-store'
import type { TabId } from '@/types'
import { ChainBanner } from './chain-banner'
import { Footer } from './footer'
import { TopBar } from './top-bar'

/** How often to look again for a wallet that injects after first paint. */
const PROVIDER_POLL_MS = 500

function readTab(): TabId {
  const stored = getLocalStorageString(STORAGE_KEYS.tab, 'borrow')
  return stored === 'lend' ? 'lend' : 'borrow'
}

export function AppShell() {
  const [tab, setTab] = useState<TabId>(readTab)

  useEffect(() => {
    setLocalStorageString(STORAGE_KEYS.tab, tab)
  }, [tab])

  // Wallet chain/account events drive the whole shell. `subscribeWalletEvents`
  // resolves the provider immediately, so subscribing before the extension has
  // injected would leave the shell deaf for the session: keep looking until a
  // provider appears, then subscribe for real.
  useEffect(() => {
    let unsub = useWalletStore.getState().initWalletListeners()
    if (getEthereum()) return unsub

    const id = window.setInterval(() => {
      if (!getEthereum()) return
      window.clearInterval(id)
      unsub = useWalletStore.getState().initWalletListeners()
    }, PROVIDER_POLL_MS)

    return () => {
      window.clearInterval(id)
      unsub()
    }
  }, [])

  const walletAccount = useWalletStore((s) => s.walletAccount)

  // The viewed address follows the wallet until the reader pins another one.
  // On disconnect `walletAccount` is '' and the view clears with it.
  useEffect(() => {
    const { following, setViewed } = useApiStore.getState()
    if (following) setViewed(walletAccount, true)
  }, [walletAccount])

  // The mark's bottom rule reports the number the current section is about.
  // The page that already holds that read publishes it, so the shell does not
  // mount a second copy of every facility and vault call.
  const gauge = useWalletStore((s) => s.gauge)

  return (
    <div className="flex min-h-screen flex-col">
      <TopBar tab={tab} onTabChange={setTab} gauge={gauge} />
      <ChainBanner />
      <TxStrip />
      <main className="mx-auto w-full max-w-[1120px] flex-1 px-4 sm:px-6">
        {tab === 'borrow' ? <BorrowPage /> : <LendPage />}
      </main>
      <Footer />
    </div>
  )
}
