import { beforeEach, describe, expect, it, vi } from 'vitest'

const ADDR_MANAGER = '0x2222222222222222222222222222222222222222'

type TxMockState = {
  ensureWalletChainOk: boolean
  ethereumEnabled: boolean
}

function getTxMockState(): TxMockState {
  const g = globalThis as unknown as { __txMockState?: TxMockState }
  if (!g.__txMockState) {
    g.__txMockState = { ensureWalletChainOk: true, ethereumEnabled: true }
  }
  return g.__txMockState
}

vi.mock('@/lib/ethereum', () => ({
  getEthereum: () => (getTxMockState().ethereumEnabled ? { request: vi.fn() } : null),
  ensureWalletChain: vi.fn(async () => getTxMockState().ensureWalletChainOk),
  getErrorMessage: (err: unknown) => (err instanceof Error ? err.message : String(err)),
}))

vi.mock('ethers', () => {
  class MockBrowserProvider {
    constructor() {}
    async getSigner() {
      return { address: '0x1111111111111111111111111111111111111111' }
    }
  }

  class MockContract {
    constructor() {}
  }

  return {
    BrowserProvider: MockBrowserProvider,
    Contract: MockContract,
    ethers: {
      isAddress: (value: string) => /^0x[0-9a-fA-F]{40}$/.test(value),
    },
  }
})

import { useWalletStore } from '@/stores/wallet-store'
import { useConfigStore } from '@/stores/config-store'
import { sendContractTx } from '@/stores/tx-store'

beforeEach(() => {
  const state = getTxMockState()
  state.ensureWalletChainOk = true
  state.ethereumEnabled = true

  useWalletStore.setState({
    walletAccount: '',
    walletChainId: 133,
    txState: { status: 'idle' },
  })

  useConfigStore.setState({
    rpcUrl: 'https://testnet.hsk.xyz',
    chainId: 133,
    managerAddress: ADDR_MANAGER,
    spvVerifierAddress: '0x5555555555555555555555555555555555555555',
    checkpointManagerAddress: '0x6666666666666666666666666666666666666666',
    vaultAddress: '0x4444444444444444444444444444444444444444',
    stablecoinAddress: '0x3333333333333333333333333333333333333333',
  })
})

describe('TX state harness', () => {
  it('A-4 follows signing -> pending -> confirmed for successful tx', async () => {
    const seen: string[] = []
    const unsub = useWalletStore.subscribe((state, prev) => {
      if (state.txState.status !== prev.txState.status) {
        seen.push(state.txState.status)
      }
    })

    await sendContractTx('borrow', ADDR_MANAGER, [], async () => ({
      hash: '0xabc123',
      wait: async () => undefined,
    }) as never)

    unsub()

    expect(seen).toEqual(['signing', 'pending', 'confirmed'])
    expect(useWalletStore.getState().txState).toEqual({
      status: 'confirmed',
      label: 'borrow',
      hash: '0xabc123',
    })
  })

  it('A-4 goes to error when tx wait fails with network error (I-1)', async () => {
    await expect(
      sendContractTx('borrow', ADDR_MANAGER, [], async () => ({
        hash: '0xdeadbeef',
        wait: async () => {
          throw new Error('network error')
        },
      }) as never),
    ).rejects.toThrow('network error')

    const txState = useWalletStore.getState().txState
    expect(txState.status).toBe('error')
    if (txState.status === 'error') {
      expect(txState.label).toBe('borrow')
      expect(txState.message).toContain('network error')
    }
  })

  it('A-4 goes to error when wallet chain switch fails', async () => {
    getTxMockState().ensureWalletChainOk = false

    await expect(
      sendContractTx('borrow', ADDR_MANAGER, [], async () => ({
        hash: '0x123',
        wait: async () => undefined,
      }) as never),
    ).rejects.toThrow('Failed to switch network')

    const txState = useWalletStore.getState().txState
    expect(txState.status).toBe('error')
    if (txState.status === 'error') {
      expect(txState.label).toBe('borrow')
      expect(txState.message).toContain('Failed to switch network')
    }
  })

  it('sets error state for invalid contract address without sending tx', async () => {
    const action = vi.fn(async () => ({
      hash: '0x123',
      wait: async () => undefined,
    }))

    await sendContractTx('borrow', 'invalid-address', [], action as never)

    expect(action).not.toHaveBeenCalled()
    expect(useWalletStore.getState().txState).toEqual({
      status: 'error',
      label: 'borrow',
      message: 'Invalid contract address.',
    })
  })

  it('goes to error when browser wallet is missing', async () => {
    getTxMockState().ethereumEnabled = false

    await expect(
      sendContractTx('borrow', ADDR_MANAGER, [], async () => ({
        hash: '0x123',
        wait: async () => undefined,
      }) as never),
    ).rejects.toThrow('Browser wallet not found')

    const txState = useWalletStore.getState().txState
    expect(txState.status).toBe('error')
    if (txState.status === 'error') {
      expect(txState.label).toBe('borrow')
      expect(txState.message).toContain('Browser wallet not found')
    }
  })
})
