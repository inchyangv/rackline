import { create } from 'zustand'
import { BrowserProvider } from 'ethers'
import { getEthereum, getErrorMessage } from '@/lib/ethereum'
import type { TxState } from '@/types'

type WalletState = {
  walletAccount: string
  walletChainId: number | null
  txState: TxState
  setWalletAccount: (v: string) => void
  setWalletChainId: (v: number | null) => void
  setTxState: (v: TxState) => void
  connectWallet: () => Promise<void>
  refreshWalletState: () => Promise<void>
  disconnectWallet: () => void
}

let activeEthereum = getEthereum()
let activeAccountsListener: ((accounts: unknown) => void) | null = null
let activeChainListener: ((chainIdHex: unknown) => void) | null = null

function cleanupWalletListeners() {
  if (!activeEthereum) return
  if (activeAccountsListener && activeEthereum.removeListener) {
    activeEthereum.removeListener('accountsChanged', activeAccountsListener)
  }
  if (activeChainListener && activeEthereum.removeListener) {
    activeEthereum.removeListener('chainChanged', activeChainListener)
  }
  activeAccountsListener = null
  activeChainListener = null
}

export const useWalletStore = create<WalletState>((set) => ({
  walletAccount: '',
  walletChainId: null,
  txState: { status: 'idle' },
  setWalletAccount: (v) => set({ walletAccount: v }),
  setWalletChainId: (v) => set({ walletChainId: v }),
  setTxState: (v) => set({ txState: v }),
  connectWallet: async () => {
    const ethereum = getEthereum()
    if (!ethereum) {
      set({ txState: { status: 'error', label: 'wallet', message: 'Browser wallet not found. (e.g. MetaMask)' } })
      return
    }

    set({ txState: { status: 'signing', label: 'wallet: connect' } })
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

      if (activeEthereum !== ethereum) {
        cleanupWalletListeners()
        activeEthereum = ethereum
      }

      if (ethereum.on) {
        cleanupWalletListeners()

        activeAccountsListener = (accountsRaw: unknown) => {
          const next =
            Array.isArray(accountsRaw) && typeof accountsRaw[0] === 'string'
              ? String(accountsRaw[0])
              : ''
          set({ walletAccount: next })
        }

        activeChainListener = (chainIdHex: unknown) => {
          if (typeof chainIdHex !== 'string') return
          const parsed = Number.parseInt(chainIdHex, 16)
          set({ walletChainId: Number.isFinite(parsed) ? parsed : null })
        }

        ethereum.on('accountsChanged', activeAccountsListener)
        ethereum.on('chainChanged', activeChainListener)
      }
    } catch (err: unknown) {
      set({
        txState: {
          status: 'error',
          label: 'wallet: connect',
          message: getErrorMessage(err),
        },
      })
    }
  },
  refreshWalletState: async () => {
    const ethereum = getEthereum()
    if (!ethereum) {
      set({ walletAccount: '', walletChainId: null })
      return
    }

    try {
      const provider = new BrowserProvider(ethereum)
      const accounts = (await provider.send('eth_accounts', [])) as string[]
      const network = await provider.getNetwork()
      set({
        walletAccount: accounts[0] ?? '',
        walletChainId: Number(network.chainId),
      })
    } catch {
      // Keep current state if refresh fails.
    }
  },
  disconnectWallet: () => {
    cleanupWalletListeners()
    set({
      walletAccount: '',
      walletChainId: null,
      txState: { status: 'idle' },
    })
  },
}))
