import { create } from 'zustand'
import { BrowserProvider } from 'ethers'
import { describeTxError, getEthereum, subscribeWalletEvents } from '@/lib/ethereum'
import type { TxState } from '@/types'

type WalletState = {
  walletAccount: string
  walletChainId: number | null
  txState: TxState
  /** Incremented after every confirmed transaction so read hooks refetch. */
  refreshKey: number
  /** 0..1 ratio shown by the mark's bottom rule; published by the active page. */
  gauge: number | null
  setGauge: (v: number | null) => void
  setWalletAccount: (v: string) => void
  setWalletChainId: (v: number | null) => void
  setTxState: (v: TxState) => void
  bumpRefresh: () => void
  connectWallet: () => Promise<void>
  disconnectWallet: () => void
  /** Subscribe to wallet chain/account changes. Returns an unsubscribe function. */
  initWalletListeners: () => () => void
}

export const useWalletStore = create<WalletState>((set, get) => ({
  walletAccount: '',
  walletChainId: null,
  txState: { status: 'idle' },
  refreshKey: 0,
  gauge: null,
  setGauge: (v) => set((s) => (s.gauge === v ? s : { gauge: v })),
  setWalletAccount: (v) => set({ walletAccount: v }),
  setWalletChainId: (v) => set({ walletChainId: v }),
  setTxState: (v) => set({ txState: v }),
  bumpRefresh: () => set((s) => ({ refreshKey: s.refreshKey + 1 })),
  connectWallet: async () => {
    const ethereum = getEthereum()
    if (!ethereum) {
      set({ txState: { status: 'error', label: 'Connect wallet', message: 'No browser wallet found.' } })
      return
    }

    set({ txState: { status: 'signing', label: 'Connect wallet' } })
    try {
      const provider = new BrowserProvider(ethereum)
      const accounts = (await provider.send('eth_requestAccounts', [])) as string[]
      const signer = await provider.getSigner()
      const network = await provider.getNetwork()

      set({
        walletAccount: accounts[0] ?? signer.address,
        walletChainId: Number(network.chainId),
        txState: { status: 'idle' },
      })
    } catch (err) {
      set({ txState: { status: 'error', label: 'Connect wallet', message: describeTxError(err) } })
    }
  },
  disconnectWallet: () => {
    set({
      walletAccount: '',
      walletChainId: null,
      txState: { status: 'idle' },
    })
  },
  initWalletListeners: () =>
    subscribeWalletEvents({
      onChainChanged: (chainId) => {
        set({ walletChainId: chainId, txState: { status: 'idle' } })
      },
      onAccountsChanged: (accounts) => {
        const next = accounts[0] ?? ''
        if (!next) {
          get().disconnectWallet()
          return
        }
        set({ walletAccount: next, txState: { status: 'idle' } })
      },
    }),
}))
