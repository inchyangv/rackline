import { create } from 'zustand'
import { BrowserProvider } from 'ethers'
import { getEthereum } from '@/lib/ethereum'
import type { TxState } from '@/types'

type WalletState = {
  walletAccount: string
  walletChainId: number | null
  txState: TxState
  setWalletAccount: (v: string) => void
  setWalletChainId: (v: number | null) => void
  setTxState: (v: TxState) => void
  connectWallet: () => Promise<void>
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
    const provider = new BrowserProvider(ethereum)
    const accounts = (await provider.send('eth_requestAccounts', [])) as string[]
    const signer = await provider.getSigner()
    const network = await provider.getNetwork()

    set({
      walletAccount: accounts[0] ?? signer.address,
      walletChainId: Number(network.chainId),
      txState: { status: 'idle' },
    })
  },
}))
