import { describe, it, beforeEach, expect, vi } from 'vitest'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const ADDR_WALLET = '0x1111111111111111111111111111111111111111'
const ADDR_MANAGER = '0x2222222222222222222222222222222222222222'
const ADDR_STABLE = '0x3333333333333333333333333333333333333333'
const ADDR_VAULT = '0x4444444444444444444444444444444444444444'
const ADDR_SPV = '0x5555555555555555555555555555555555555555'

const mockEnsureWalletChain = vi.fn<(...args: unknown[]) => Promise<boolean>>()
const mockCopyToClipboard = vi.fn<(text: string) => Promise<void>>()
const mockSendContractTx = vi.fn<(...args: unknown[]) => Promise<void>>()
const mockApiRequest = vi.fn<(path: string, init?: RequestInit) => Promise<unknown>>()
const mockToastError = vi.fn<(msg: string) => void>()
const mockToastSuccess = vi.fn<(msg: string) => void>()
const mockToastPromise = vi.fn((p: Promise<unknown>) => {
  p.catch(() => undefined)
  return p
})

type BorrowerHookState = {
  availableCredit: bigint | null
  borrowerInfo: Record<string, unknown> | null
  stablecoinDecimals: number
  stablecoinBalance: bigint | null
  currentDebt: bigint | null
  accruedInterest: bigint | null
  isLoading: boolean
}

type VaultHookState = {
  totalAssets: bigint | null
  totalBorrowed: bigint | null
  availableLiquidity: bigint | null
  totalShares: bigint | null
  utilizationRate: bigint | null
  borrowAPR: bigint | null
  myShares: bigint | null
  myShareValue: bigint | null
  isLoading: boolean
}

let borrowerHookState: BorrowerHookState
let vaultHookState: VaultHookState

type StablecoinReadMock = {
  balanceOf: (addr: string) => Promise<bigint>
}

type VaultReadMock = {
  convertToShares: (assets: bigint) => Promise<bigint>
}

let stablecoinReadMock: StablecoinReadMock | null = null
let vaultReadMock: VaultReadMock | null = null

vi.mock('@/lib/ethereum', () => ({
  getEthereum: () => {
    const state = (
      globalThis as unknown as {
        __testEthereum?: { request: ReturnType<typeof vi.fn> } | null
      }
    ).__testEthereum
    return state === undefined ? { request: vi.fn() } : state
  },
  ensureWalletChain: (...args: unknown[]) => mockEnsureWalletChain(...args),
  getErrorMessage: (err: unknown) => (err instanceof Error ? err.message : String(err)),
}))

vi.mock('@/lib/clipboard', () => ({
  copyToClipboard: (text: string) => mockCopyToClipboard(text),
}))

vi.mock('@/stores/tx-store', () => ({
  sendContractTx: (...args: unknown[]) => mockSendContractTx(...args),
}))

vi.mock('@/hooks/use-api-client', () => ({
  useApiClient: () => ({
    apiRequest: (path: string, init?: RequestInit) => mockApiRequest(path, init),
    apiRun: vi.fn(),
  }),
}))

vi.mock('@/hooks/use-manager-reads', () => ({
  useManagerReads: () => ({
    owner: ADDR_MANAGER,
    verifier: ADDR_SPV,
    stablecoin: ADDR_STABLE,
    vault: ADDR_VAULT,
  }),
}))

vi.mock('@/hooks/use-borrower-info', () => ({
  useBorrowerInfo: () => borrowerHookState,
}))

vi.mock('@/hooks/use-vault-info', () => ({
  useVaultInfo: () => vaultHookState,
}))

vi.mock('@/hooks/use-contracts', () => ({
  useVaultRead: () => vaultReadMock,
  useStablecoinRead: () => stablecoinReadMock,
}))

vi.mock('sonner', () => ({
  toast: {
    error: (msg: string) => mockToastError(msg),
    success: (msg: string) => mockToastSuccess(msg),
    promise: (p: Promise<unknown>) => mockToastPromise(p),
  },
}))

import { useWalletStore } from '@/stores/wallet-store'
import { useApiStore } from '@/stores/api-store'
import { useConfigStore } from '@/stores/config-store'
import { WalletPanel } from '@/components/layout/wallet-panel'
import { BorrowerCard } from '@/features/dashboard/borrower-card'
import { ClaimSection } from '@/features/dashboard/claim-section'
import { DepositCard } from '@/features/pool/deposit-card'
import { WithdrawCard } from '@/features/pool/withdraw-card'
import { AppShell } from '@/components/layout/app-shell'

function resetHookState() {
  borrowerHookState = {
    availableCredit: null,
    borrowerInfo: null,
    stablecoinDecimals: 6,
    stablecoinBalance: null,
    currentDebt: null,
    accruedInterest: null,
    isLoading: false,
  }

  vaultHookState = {
    totalAssets: 10_000_000_000n,
    totalBorrowed: 3_000_000_000n,
    availableLiquidity: 7_000_000_000n,
    totalShares: 10_000_000_000n,
    utilizationRate: 3000n,
    borrowAPR: 800n,
    myShares: 0n,
    myShareValue: 0n,
    isLoading: false,
  }

  stablecoinReadMock = null
  vaultReadMock = null
}

function resetStores() {
  useWalletStore.setState({
    walletAccount: '',
    walletChainId: null,
    txState: { status: 'idle' },
  })

  useApiStore.setState({
    borrowerAddress: '',
    claimBtcAddress: '',
    claimBtcSignature: '',
    claimLog: '',
    claimBusy: false,
    borrowAmount: '0',
    repayAmount: '0',
    approveAmount: '0',
  })

  useConfigStore.setState({
    rpcUrl: 'https://testnet.hsk.xyz',
    chainId: 133,
    managerAddress: ADDR_MANAGER,
    spvVerifierAddress: ADDR_SPV,
    checkpointManagerAddress: '0x6666666666666666666666666666666666666666',
    vaultAddress: ADDR_VAULT,
    stablecoinAddress: ADDR_STABLE,
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  ;(globalThis as unknown as { __testEthereum?: { request: ReturnType<typeof vi.fn> } | null }).__testEthereum = { request: vi.fn() }
  mockEnsureWalletChain.mockResolvedValue(true)
  mockCopyToClipboard.mockResolvedValue()
  mockSendContractTx.mockResolvedValue()
  mockApiRequest.mockResolvedValue({ success: true })
  resetHookState()
  resetStores()
})

describe('SCENARIO harness', () => {
  it('A-1 shows install state when wallet is not injected', () => {
    ;(globalThis as unknown as { __testEthereum?: { request: ReturnType<typeof vi.fn> } | null }).__testEthereum = null

    render(<WalletPanel />)

    const installBtn = screen.getByRole('button', { name: /install metamask/i })
    expect(installBtn).toBeDisabled()
    expect(screen.getByRole('button', { name: /switch network/i })).toBeDisabled()
  })

  it('A-2 network switch triggers chain switch and wallet refresh', async () => {
    const connectSpy = vi.fn(async () => {})
    const disconnectSpy = vi.fn()
    const refreshSpy = vi.fn(async () => {})
    useWalletStore.setState({
      walletAccount: ADDR_WALLET,
      walletChainId: 1,
      connectWallet: connectSpy,
      disconnectWallet: disconnectSpy,
      refreshWalletState: refreshSpy,
    })

    render(<WalletPanel />)
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: /switch network/i }))

    expect(mockEnsureWalletChain).toHaveBeenCalledWith(133, 'https://testnet.hsk.xyz')
    await waitFor(() => expect(refreshSpy).toHaveBeenCalled())
  })

  it('A-1 disconnected wallet disables borrow actions', () => {
    render(<BorrowerCard />)

    expect(screen.getByText(/wallet not connected/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Borrow' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Repay' })).toBeDisabled()
  })

  it('C/D borrower max and tx actions work with active borrower', async () => {
    borrowerHookState = {
      availableCredit: 1_000_000_000n,
      stablecoinBalance: 500_000_000n,
      currentDebt: 500_000_000n,
      accruedInterest: 0n,
      stablecoinDecimals: 6,
      isLoading: false,
      borrowerInfo: {
        status: 1n,
        creditLimit: 1_000_000_000n,
        btcPayoutKeyHash: '0x1234000000000000000000000000000000000000000000000000000000000000',
      },
    }

    useWalletStore.setState({ walletAccount: ADDR_WALLET, walletChainId: 133 })

    render(<BorrowerCard />)
    const user = userEvent.setup()

    const maxButtons = screen.getAllByRole('button', { name: 'Max' })
    await user.click(maxButtons[0])
    const amountInputs = screen.getAllByPlaceholderText('0.00')
    expect((amountInputs[0] as HTMLInputElement).value).toContain('1000')

    await user.clear(amountInputs[0])
    await user.type(amountInputs[0], '2000')
    await user.click(screen.getAllByRole('button', { name: 'Borrow' })[0])
    expect(mockToastError).toHaveBeenCalledWith('Amount exceeds available credit')

    await user.clear(amountInputs[0])
    await user.type(amountInputs[0], '500')
    await user.click(screen.getAllByRole('button', { name: 'Borrow' })[0])
    await waitFor(() => expect(mockSendContractTx).toHaveBeenCalled())
    expect(mockSendContractTx).toHaveBeenCalledWith(
      'borrow',
      ADDR_MANAGER,
      expect.any(Array),
      expect.any(Function),
    )

    await user.click(maxButtons[1])
    const repayInput = screen.getAllByPlaceholderText('0.00')[2] as HTMLInputElement
    expect(repayInput.value).toContain('500')
  })

  it('B-1 claim flow executes 3-step verify/register pipeline', async () => {
    useWalletStore.setState({ walletAccount: ADDR_WALLET, walletChainId: 133 })
    useApiStore.setState({
      borrowerAddress: ADDR_WALLET,
      claimBtcAddress: 'tb1qtestborrower00000000000000000000000000',
      claimBtcSignature: 'base64-signature',
    })
    borrowerHookState.borrowerInfo = {
      status: 1n,
      creditLimit: 1_000_000_000n,
      btcPayoutKeyHash: '0x0000000000000000000000000000000000000000000000000000000000000000',
    }

    mockApiRequest
      .mockResolvedValueOnce({
        success: true,
        pub_key_x: '0x01',
        pub_key_y: '0x02',
        btc_msg_hash: '0x03',
        v: 27,
        r: '0x04',
        s: '0x05',
      })
      .mockResolvedValueOnce({
        success: true,
        credit_amount: '1000000000',
        register_tx: '0xabc',
        grant_tx: '0xdef',
      })

    render(<ClaimSection />)
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: /verify & register/i }))

    await waitFor(() => expect(mockApiRequest).toHaveBeenCalledTimes(2))
    expect(mockApiRequest).toHaveBeenNthCalledWith(
      1,
      '/claim/extract-sig-params',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(mockSendContractTx).toHaveBeenCalledWith(
      'claimBtcAddress',
      ADDR_SPV,
      expect.any(Array),
      expect.any(Function),
    )
    expect(mockApiRequest).toHaveBeenNthCalledWith(
      2,
      '/claim/register-and-grant',
      expect.objectContaining({ method: 'POST' }),
    )
    await waitFor(() => expect(mockToastSuccess).toHaveBeenCalled())
    expect(screen.getByText(/borrower registered with 1000000000 credit/i)).toBeInTheDocument()
  })

  it('E/F deposit and withdraw flows enforce liquidity and call tx actions', async () => {
    useWalletStore.setState({ walletAccount: ADDR_WALLET, walletChainId: 133 })

    stablecoinReadMock = {
      balanceOf: vi.fn(async () => 5_000_000_000n),
    }
    vaultReadMock = {
      convertToShares: vi.fn(async (assets: bigint) => assets),
    }

    const user = userEvent.setup()

    const depositView = render(<DepositCard embedded />)

    await waitFor(() => {
      expect(screen.getByText(/5000.*mUSDT/i)).toBeInTheDocument()
    })

    await user.click(within(depositView.container).getByRole('button', { name: 'Max' }))
    const depositInput = within(depositView.container).getByPlaceholderText('0.00') as HTMLInputElement
    expect(depositInput.value).toContain('5000')

    await user.click(within(depositView.container).getByRole('button', { name: 'Approve' }))
    await user.click(within(depositView.container).getByRole('button', { name: 'Deposit' }))
    expect(mockSendContractTx).toHaveBeenCalledWith(
      'approve',
      ADDR_STABLE,
      expect.any(Array),
      expect.any(Function),
    )
    expect(mockSendContractTx).toHaveBeenCalledWith(
      'deposit',
      ADDR_VAULT,
      expect.any(Array),
      expect.any(Function),
    )

    depositView.unmount()

    const withdrawView = render(
      <WithdrawCard
        embedded
        vault={{
          ...vaultHookState,
          myShares: 1_000_000_000n,
          myShareValue: 1_000_000_000n,
          availableLiquidity: 200_000_000n,
        }}
      />,
    )

    const withdrawInput = within(withdrawView.container).getByPlaceholderText('0.00') as HTMLInputElement
    await user.clear(withdrawInput)
    await user.type(withdrawInput, '500')

    await waitFor(() => {
      expect(screen.getByText(/withdrawal amount exceeds available liquidity/i)).toBeInTheDocument()
    })
    expect(within(withdrawView.container).getByRole('button', { name: 'Withdraw' })).toBeDisabled()

    await user.clear(withdrawInput)
    await user.type(withdrawInput, '100')
    await waitFor(() => {
      expect(screen.queryByText(/withdrawal amount exceeds available liquidity/i)).toBeNull()
    })

    await user.click(within(withdrawView.container).getByRole('button', { name: 'Withdraw' }))
    expect(mockSendContractTx).toHaveBeenCalledWith(
      'withdraw',
      ADDR_VAULT,
      expect.any(Array),
      expect.any(Function),
    )
  })

  it('A-3 disconnect resets borrower/claim local state through AppShell effect', async () => {
    useWalletStore.setState({ walletAccount: ADDR_WALLET, walletChainId: 133 })
    useApiStore.setState({
      borrowerAddress: ADDR_WALLET,
      claimBtcAddress: 'tb1qabc',
      claimBtcSignature: 'sig',
      claimLog: 'running',
      borrowAmount: '123',
      repayAmount: '456',
      approveAmount: '789',
    })

    render(<AppShell />)

    await act(async () => {
      useWalletStore.setState({ walletAccount: '', walletChainId: null })
    })

    await waitFor(() => {
      const s = useApiStore.getState()
      expect(s.borrowerAddress).toBe('')
      expect(s.claimBtcAddress).toBe('')
      expect(s.claimBtcSignature).toBe('')
      expect(s.claimLog).toBe('')
      expect(s.borrowAmount).toBe('0')
      expect(s.repayAmount).toBe('0')
      expect(s.approveAmount).toBe('0')
    })
  })

  it('I-3 frozen borrower blocks borrow but keeps repay action enabled', () => {
    borrowerHookState = {
      availableCredit: 1_000_000_000n,
      stablecoinBalance: 200_000_000n,
      currentDebt: 300_000_000n,
      accruedInterest: 1_000n,
      stablecoinDecimals: 6,
      isLoading: false,
      borrowerInfo: {
        status: 2n,
        creditLimit: 1_000_000_000n,
        btcPayoutKeyHash: '0x1234000000000000000000000000000000000000000000000000000000000000',
      },
    }
    useWalletStore.setState({ walletAccount: ADDR_WALLET, walletChainId: 133 })

    render(<BorrowerCard />)

    expect(screen.getByText(/borrower is frozen/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Borrow' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Repay' })).toBeEnabled()
  })

  it('I-2 already linked BTC wallet prevents re-claim flow', () => {
    useWalletStore.setState({ walletAccount: ADDR_WALLET, walletChainId: 133 })
    useApiStore.setState({
      borrowerAddress: ADDR_WALLET,
      claimBtcAddress: 'tb1qalreadylinked',
      claimBtcSignature: 'already',
    })
    borrowerHookState.borrowerInfo = {
      status: 1n,
      creditLimit: 1_000_000_000n,
      btcPayoutKeyHash: '0x9999000000000000000000000000000000000000000000000000000000000000',
    }

    render(<ClaimSection />)

    expect(screen.getByText(/already linked/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /verify & register/i })).toBeNull()
  })

  it('A-4/I-8 pending tx locks write actions to avoid conflicting submissions', () => {
    borrowerHookState = {
      availableCredit: 1_000_000_000n,
      stablecoinBalance: 500_000_000n,
      currentDebt: 500_000_000n,
      accruedInterest: 0n,
      stablecoinDecimals: 6,
      isLoading: false,
      borrowerInfo: {
        status: 1n,
        creditLimit: 1_000_000_000n,
        btcPayoutKeyHash: '0x1234000000000000000000000000000000000000000000000000000000000000',
      },
    }
    useWalletStore.setState({
      walletAccount: ADDR_WALLET,
      walletChainId: 133,
      txState: { status: 'pending', label: 'borrow', hash: '0xabc' },
    })
    stablecoinReadMock = {
      balanceOf: vi.fn(async () => 5_000_000_000n),
    }
    vaultReadMock = {
      convertToShares: vi.fn(async (assets: bigint) => assets),
    }

    const borrowerView = render(<BorrowerCard />)
    expect(within(borrowerView.container).getByRole('button', { name: 'Borrow' })).toBeDisabled()
    expect(within(borrowerView.container).getByRole('button', { name: 'Approve' })).toBeDisabled()
    expect(within(borrowerView.container).getByRole('button', { name: 'Repay' })).toBeDisabled()
    borrowerView.unmount()

    const depositView = render(<DepositCard embedded />)
    expect(within(depositView.container).getByRole('button', { name: 'Deposit' })).toBeDisabled()
    expect(within(depositView.container).getByRole('button', { name: 'Approve' })).toBeDisabled()
    depositView.unmount()

    const withdrawView = render(
      <WithdrawCard
        embedded
        vault={{
          ...vaultHookState,
          myShares: 100n,
          myShareValue: 100n,
          availableLiquidity: 100n,
        }}
      />,
    )
    expect(within(withdrawView.container).getByRole('button', { name: 'Withdraw' })).toBeDisabled()
  })

  it('I-4 paused manager path: borrow/repay tx can revert and still follows tx flow', async () => {
    borrowerHookState = {
      availableCredit: 1_000_000_000n,
      stablecoinBalance: 500_000_000n,
      currentDebt: 500_000_000n,
      accruedInterest: 0n,
      stablecoinDecimals: 6,
      isLoading: false,
      borrowerInfo: {
        status: 1n,
        creditLimit: 1_000_000_000n,
        btcPayoutKeyHash: '0x1234000000000000000000000000000000000000000000000000000000000000',
      },
    }
    useWalletStore.setState({ walletAccount: ADDR_WALLET, walletChainId: 133 })
    mockSendContractTx
      .mockRejectedValueOnce(new Error('Pausable: paused'))
      .mockRejectedValueOnce(new Error('Pausable: paused'))

    const user = userEvent.setup()
    const view = render(<BorrowerCard />)
    const inputs = within(view.container).getAllByPlaceholderText('0.00')

    await user.clear(inputs[0])
    await user.type(inputs[0], '100')
    await user.click(within(view.container).getByRole('button', { name: 'Borrow' }))

    await user.clear(inputs[2])
    await user.type(inputs[2], '50')
    await user.click(within(view.container).getByRole('button', { name: 'Repay' }))

    await waitFor(() => expect(mockSendContractTx).toHaveBeenCalledTimes(2))
    expect(mockSendContractTx).toHaveBeenNthCalledWith(
      1,
      'borrow',
      ADDR_MANAGER,
      expect.any(Array),
      expect.any(Function),
    )
    expect(mockSendContractTx).toHaveBeenNthCalledWith(
      2,
      'repay',
      ADDR_MANAGER,
      expect.any(Array),
      expect.any(Function),
    )
  })

  it('I-5 repay with zero mUSDT balance still triggers repay tx attempt', async () => {
    borrowerHookState = {
      availableCredit: 500_000_000n,
      stablecoinBalance: 0n,
      currentDebt: 300_000_000n,
      accruedInterest: 0n,
      stablecoinDecimals: 6,
      isLoading: false,
      borrowerInfo: {
        status: 1n,
        creditLimit: 1_000_000_000n,
        btcPayoutKeyHash: '0x1234000000000000000000000000000000000000000000000000000000000000',
      },
    }
    useWalletStore.setState({ walletAccount: ADDR_WALLET, walletChainId: 133 })
    mockSendContractTx.mockRejectedValueOnce(new Error('ERC20: transfer amount exceeds balance'))

    const user = userEvent.setup()
    const view = render(<BorrowerCard />)
    const repayInput = within(view.container).getAllByPlaceholderText('0.00')[2] as HTMLInputElement

    await user.clear(repayInput)
    await user.type(repayInput, '100')
    await user.click(within(view.container).getByRole('button', { name: 'Repay' }))

    await waitFor(() => expect(mockSendContractTx).toHaveBeenCalled())
    expect(mockSendContractTx).toHaveBeenCalledWith(
      'repay',
      ADDR_MANAGER,
      expect.any(Array),
      expect.any(Function),
    )
  })

  it('I-6 borrow with credit but empty pool liquidity still follows revert path', async () => {
    borrowerHookState = {
      availableCredit: 1_000_000_000n,
      stablecoinBalance: 0n,
      currentDebt: 0n,
      accruedInterest: 0n,
      stablecoinDecimals: 6,
      isLoading: false,
      borrowerInfo: {
        status: 1n,
        creditLimit: 1_000_000_000n,
        btcPayoutKeyHash: '0x1234000000000000000000000000000000000000000000000000000000000000',
      },
    }
    vaultHookState.availableLiquidity = 0n
    useWalletStore.setState({ walletAccount: ADDR_WALLET, walletChainId: 133 })
    mockSendContractTx.mockRejectedValueOnce(new Error('InsufficientLiquidity'))

    const user = userEvent.setup()
    const view = render(<BorrowerCard />)
    const borrowInput = within(view.container).getAllByPlaceholderText('0.00')[0] as HTMLInputElement

    await user.clear(borrowInput)
    await user.type(borrowInput, '100')
    await user.click(within(view.container).getByRole('button', { name: 'Borrow' }))

    await waitFor(() => expect(mockSendContractTx).toHaveBeenCalled())
    expect(mockSendContractTx).toHaveBeenCalledWith(
      'borrow',
      ADDR_MANAGER,
      expect.any(Array),
      expect.any(Function),
    )
  })

  it('I-7 dust borrow amount is allowed and submits tx', async () => {
    borrowerHookState = {
      availableCredit: 1_000_000_000n,
      stablecoinBalance: 0n,
      currentDebt: 0n,
      accruedInterest: 0n,
      stablecoinDecimals: 6,
      isLoading: false,
      borrowerInfo: {
        status: 1n,
        creditLimit: 1_000_000_000n,
        btcPayoutKeyHash: '0x1234000000000000000000000000000000000000000000000000000000000000',
      },
    }
    useWalletStore.setState({ walletAccount: ADDR_WALLET, walletChainId: 133 })

    const user = userEvent.setup()
    const view = render(<BorrowerCard />)
    const borrowInput = within(view.container).getAllByPlaceholderText('0.00')[0] as HTMLInputElement

    await user.clear(borrowInput)
    await user.type(borrowInput, '0.000001')
    await user.click(within(view.container).getByRole('button', { name: 'Borrow' }))

    await waitFor(() => expect(mockSendContractTx).toHaveBeenCalled())
    expect(mockSendContractTx).toHaveBeenCalledWith(
      'borrow',
      ADDR_MANAGER,
      expect.any(Array),
      expect.any(Function),
    )
  })
})
