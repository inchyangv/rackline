import { create } from 'zustand'
import { ethers, Wallet } from 'ethers'
import type {
  DemoWallet,
  BorrowerBtcMap,
  DemoBtcPayoutRecord,
  BtcAddressHistorySnapshot,
} from '@/types'
import { getLocalStorageString, setLocalStorageString } from '@/lib/storage'
import { parseDemoWallets, parseBorrowerBtcMap, parseDemoBtcPayoutHistory } from '@/lib/parsers'

type DemoState = {
  demoWallets: DemoWallet[]
  borrowerBtcMap: BorrowerBtcMap
  demoBtcPayoutHistory: DemoBtcPayoutRecord[]
  btcChainHistoryByAddress: Record<string, BtcAddressHistorySnapshot>
  btcChainHistoryLoading: Record<string, boolean>
  btcChainHistoryError: Record<string, string>
  btcHistoryMiningOnly: boolean
  btcHistoryAutoRefreshEnabled: boolean
  setDemoWallets: (v: DemoWallet[]) => void
  setBorrowerBtcMap: (v: BorrowerBtcMap) => void
  setDemoBtcPayoutHistory: (v: DemoBtcPayoutRecord[]) => void
  setBtcChainHistoryByAddress: (v: Record<string, BtcAddressHistorySnapshot>) => void
  setBtcChainHistoryLoading: (v: Record<string, boolean>) => void
  setBtcChainHistoryError: (v: Record<string, string>) => void
  setBtcHistoryMiningOnly: (v: boolean) => void
  setBtcHistoryAutoRefreshEnabled: (v: boolean) => void
  createDemoWallet: (count: number) => void
  removeDemoWallet: (address: string) => void
  rememberBorrowerBtcAddress: (borrower: string, btcAddress: string) => void
  recordDemoBtcPayout: (params: {
    borrower: string
    btcAddress: string
    txid: string
    vout: number
    amountSats: number | null
    checkpointHeight: number
    targetHeight: number
    source: 'build' | 'build+submit'
    submitTxHash?: string | null
  }) => void
}

function persistWallets(wallets: DemoWallet[]): void {
  setLocalStorageString('hashcredit_demo_wallets', JSON.stringify(wallets))
}

function persistBtcMap(map: BorrowerBtcMap): void {
  setLocalStorageString('hashcredit_borrower_btc_map', JSON.stringify(map))
}

function persistPayoutHistory(history: DemoBtcPayoutRecord[]): void {
  setLocalStorageString('hashcredit_demo_btc_payout_history', JSON.stringify(history))
}

export const useDemoStore = create<DemoState>((set, get) => ({
  demoWallets: parseDemoWallets(getLocalStorageString('hashcredit_demo_wallets', '[]')),
  borrowerBtcMap: parseBorrowerBtcMap(getLocalStorageString('hashcredit_borrower_btc_map', '{}')),
  demoBtcPayoutHistory: parseDemoBtcPayoutHistory(
    getLocalStorageString('hashcredit_demo_btc_payout_history', '[]'),
  ),
  btcChainHistoryByAddress: {},
  btcChainHistoryLoading: {},
  btcChainHistoryError: {},
  btcHistoryMiningOnly: false,
  btcHistoryAutoRefreshEnabled: false,
  setDemoWallets: (v) => {
    persistWallets(v)
    set({ demoWallets: v })
  },
  setBorrowerBtcMap: (v) => {
    persistBtcMap(v)
    set({ borrowerBtcMap: v })
  },
  setDemoBtcPayoutHistory: (v) => {
    persistPayoutHistory(v)
    set({ demoBtcPayoutHistory: v })
  },
  setBtcChainHistoryByAddress: (v) => set({ btcChainHistoryByAddress: v }),
  setBtcChainHistoryLoading: (v) => set({ btcChainHistoryLoading: v }),
  setBtcChainHistoryError: (v) => set({ btcChainHistoryError: v }),
  setBtcHistoryMiningOnly: (v) => set({ btcHistoryMiningOnly: v }),
  setBtcHistoryAutoRefreshEnabled: (v) => set({ btcHistoryAutoRefreshEnabled: v }),
  createDemoWallet: (count) => {
    const { demoWallets } = get()
    const n = Math.max(1, Math.min(5, Math.floor(count)))
    const now = Date.now()
    const next: DemoWallet[] = []
    for (let i = 0; i < n; i++) {
      const w = Wallet.createRandom()
      next.push({
        name: `Demo Wallet #${demoWallets.length + i + 1}`,
        address: w.address,
        privateKey: w.privateKey,
        createdAt: now,
      })
    }
    const updated = [...next, ...demoWallets].slice(0, 10)
    persistWallets(updated)
    set({ demoWallets: updated })
  },
  removeDemoWallet: (address) => {
    const { demoWallets } = get()
    const updated = demoWallets.filter((w) => w.address !== address)
    persistWallets(updated)
    set({ demoWallets: updated })
  },
  rememberBorrowerBtcAddress: (borrower, btcAddress) => {
    if (!ethers.isAddress(borrower)) return
    const nextBtcAddress = btcAddress.trim()
    if (!nextBtcAddress) return
    const { borrowerBtcMap } = get()
    const updated = { ...borrowerBtcMap, [borrower.toLowerCase()]: nextBtcAddress }
    persistBtcMap(updated)
    set({ borrowerBtcMap: updated })
  },
  recordDemoBtcPayout: (params) => {
    const { demoBtcPayoutHistory } = get()
    const id = `${Date.now()}-${Math.random().toString(16).slice(2, 10)}`
    const item: DemoBtcPayoutRecord = {
      id,
      createdAt: Date.now(),
      borrower: params.borrower,
      btcAddress: params.btcAddress,
      txid: params.txid,
      vout: params.vout,
      amountSats: params.amountSats,
      checkpointHeight: params.checkpointHeight,
      targetHeight: params.targetHeight,
      source: params.source,
      submitTxHash: params.submitTxHash ?? null,
    }
    const updated = [item, ...demoBtcPayoutHistory].slice(0, 200)
    persistPayoutHistory(updated)
    set({ demoBtcPayoutHistory: updated })
  },
}))
