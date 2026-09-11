import { useEffect, useMemo, useState } from 'react'
import { BrowserProvider, Contract, ethers, JsonRpcProvider } from 'ethers'
import type { ContractTransactionResponse, InterfaceAbi } from 'ethers'
import './App.css'

import { HashCreditManagerAbi, BtcSpvVerifierAbi, CheckpointManagerAbi, Erc20Abi } from './lib/abis'
import { env } from './lib/env'

type TxState =
  | { status: 'idle' }
  | { status: 'signing'; label: string }
  | { status: 'pending'; label: string; hash: string }
  | { status: 'confirmed'; label: string; hash: string }
  | { status: 'error'; label: string; message: string }

function isHexBytes(value: string): boolean {
  return /^0x[0-9a-fA-F]*$/.test(value) && value.length % 2 === 0
}

function shortAddr(addr: string): string {
  if (!addr) return ''
  return `${addr.slice(0, 6)}…${addr.slice(-4)}`
}

type Eip1193Provider = {
  request: (args: { method: string; params?: unknown[] | Record<string, unknown> }) => Promise<unknown>
}

function isEip1193Provider(value: unknown): value is Eip1193Provider {
  if (typeof value !== 'object' || value === null) return false
  if (!('request' in value)) return false
  const request = (value as { request?: unknown }).request
  return typeof request === 'function'
}

function getEthereum(): Eip1193Provider | null {
  if (typeof window === 'undefined') return null
  const w = window as unknown as { ethereum?: unknown }
  return isEip1193Provider(w.ethereum) ? w.ethereum : null
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

function getErrorCode(err: unknown): number | undefined {
  if (!isRecord(err)) return undefined
  const code = err.code
  if (typeof code === 'number') return code
  if (typeof code === 'string') {
    const parsed = Number(code)
    return Number.isFinite(parsed) ? parsed : undefined
  }
  return undefined
}

function getErrorMessage(err: unknown): string {
  if (isRecord(err)) {
    const shortMessage = err.shortMessage
    if (typeof shortMessage === 'string') return shortMessage
    const message = err.message
    if (typeof message === 'string') return message
  }
  return String(err)
}

function App() {
  // Config (read-only provider)
  const [rpcUrl, setRpcUrl] = useState(env.rpcUrl)
  const [chainId, setChainId] = useState(env.chainId)
  const [managerAddress, setManagerAddress] = useState(env.hashCreditManager)
  const [spvVerifierAddress, setSpvVerifierAddress] = useState(env.btcSpvVerifier)
  const [checkpointManagerAddress, setCheckpointManagerAddress] = useState(env.checkpointManager)

  // Wallet connection (write txs)
  const [walletAccount, setWalletAccount] = useState<string>('')
  const [walletChainId, setWalletChainId] = useState<number | null>(null)
  const [txState, setTxState] = useState<TxState>({ status: 'idle' })

  // Borrower view
  const [borrowerAddress, setBorrowerAddress] = useState<string>('')

  // Manager read state
  const [managerOwner, setManagerOwner] = useState<string>('')
  const [managerVerifier, setManagerVerifier] = useState<string>('')
  const [managerStablecoin, setManagerStablecoin] = useState<string>('')
  const [managerVault, setManagerVault] = useState<string>('')

  const [availableCredit, setAvailableCredit] = useState<bigint | null>(null)
  const [borrowerInfo, setBorrowerInfo] = useState<Record<string, unknown> | null>(null)
  const [stablecoinDecimals, setStablecoinDecimals] = useState<number>(6)
  const [stablecoinBalance, setStablecoinBalance] = useState<bigint | null>(null)

  // Checkpoint read state
  const [latestCheckpointHeight, setLatestCheckpointHeight] = useState<number | null>(null)
  const [latestCheckpoint, setLatestCheckpoint] = useState<Record<string, unknown> | null>(null)

  // SPV verifier read state
  const [spvOwner, setSpvOwner] = useState<string>('')
  const [spvCheckpointManagerOnchain, setSpvCheckpointManagerOnchain] = useState<string>('')
  const [spvBorrowerOnchainPubkeyHash, setSpvBorrowerOnchainPubkeyHash] = useState<string>('')

  // Write inputs
  const [proofHex, setProofHex] = useState<string>('0x')
  const [borrowAmount, setBorrowAmount] = useState<string>('1000')
  const [repayAmount, setRepayAmount] = useState<string>('1000')
  const [approveAmount, setApproveAmount] = useState<string>('1000')

  // Admin inputs
  const [adminBorrower, setAdminBorrower] = useState<string>('')
  const [adminBtcAddr, setAdminBtcAddr] = useState<string>('')
  const [adminBtcKeyHash, setAdminBtcKeyHash] = useState<string>('')
  const [adminNewVerifier, setAdminNewVerifier] = useState<string>('')

  // SPV inputs
  const [spvBorrower, setSpvBorrower] = useState<string>('')
  const [spvPubkeyHash, setSpvPubkeyHash] = useState<string>('')

  const readonlyProvider = useMemo(() => {
    if (!rpcUrl) return null
    try {
      return new JsonRpcProvider(rpcUrl)
    } catch {
      return null
    }
  }, [rpcUrl])

  const managerRead = useMemo(() => {
    if (!readonlyProvider || !ethers.isAddress(managerAddress)) return null
    return new Contract(managerAddress, HashCreditManagerAbi, readonlyProvider)
  }, [readonlyProvider, managerAddress])

  const spvVerifierRead = useMemo(() => {
    if (!readonlyProvider || !ethers.isAddress(spvVerifierAddress)) return null
    return new Contract(spvVerifierAddress, BtcSpvVerifierAbi, readonlyProvider)
  }, [readonlyProvider, spvVerifierAddress])

  const checkpointRead = useMemo(() => {
    if (!readonlyProvider || !ethers.isAddress(checkpointManagerAddress)) return null
    return new Contract(checkpointManagerAddress, CheckpointManagerAbi, readonlyProvider)
  }, [readonlyProvider, checkpointManagerAddress])

  const stablecoinRead = useMemo(() => {
    if (!readonlyProvider || !ethers.isAddress(managerStablecoin)) return null
    return new Contract(managerStablecoin, Erc20Abi, readonlyProvider)
  }, [readonlyProvider, managerStablecoin])

  const hasInjectedWallet = getEthereum() !== null

  async function connectWallet(): Promise<void> {
    const ethereum = getEthereum()
    if (!ethereum) {
      setTxState({ status: 'error', label: 'wallet', message: 'No injected wallet found (MetaMask 등)' })
      return
    }

    setTxState({ status: 'signing', label: 'wallet: connect' })
    const provider = new BrowserProvider(ethereum)
    const accounts = (await provider.send('eth_requestAccounts', [])) as string[]
    const signer = await provider.getSigner()
    const network = await provider.getNetwork()

    setWalletAccount(accounts[0] ?? signer.address)
    setWalletChainId(Number(network.chainId))
    setTxState({ status: 'idle' })
  }

  async function ensureWalletChain(expectedChainId: number): Promise<boolean> {
    const ethereum = getEthereum()
    if (!ethereum) return false
    const hexChainId = `0x${expectedChainId.toString(16)}`
    try {
      await ethereum.request({
        method: 'wallet_switchEthereumChain',
        params: [{ chainId: hexChainId }],
      })
      return true
    } catch (err: unknown) {
      // 4902: unknown chain
      if (getErrorCode(err) === 4902) {
        try {
          await ethereum.request({
            method: 'wallet_addEthereumChain',
            params: [
              {
                chainId: hexChainId,
                chainName: 'Creditcoin Testnet',
                nativeCurrency: { name: 'Creditcoin', symbol: 'CTC', decimals: 18 },
                rpcUrls: [rpcUrl].filter(Boolean),
              },
            ],
          })
          return true
        } catch {
          return false
        }
      }
      return false
    }
  }

  async function sendContractTx(
    label: string,
    address: string,
    abi: InterfaceAbi,
    action: (contract: Contract) => Promise<ContractTransactionResponse>,
  ): Promise<void> {
    if (!ethers.isAddress(address)) {
      setTxState({ status: 'error', label, message: 'Invalid contract address' })
      return
    }

    setTxState({ status: 'signing', label })
    try {
      const ok = await ensureWalletChain(chainId)
      if (!ok) throw new Error(`Failed to switch network to chainId=${chainId}`)

      const ethereum = getEthereum()
      if (!ethereum) throw new Error('No injected wallet found')

      const provider = new BrowserProvider(ethereum)
      const signer = await provider.getSigner()
      const contract = new Contract(address, abi, signer)

      const tx = await action(contract)
      setTxState({ status: 'pending', label, hash: tx.hash })
      await tx.wait()
      setTxState({ status: 'confirmed', label, hash: tx.hash })
    } catch (err: unknown) {
      setTxState({ status: 'error', label, message: getErrorMessage(err) })
    }
  }

  // Default borrower: connected wallet
  useEffect(() => {
    if (walletAccount && !borrowerAddress) setBorrowerAddress(walletAccount)
  }, [walletAccount, borrowerAddress])

  // Manager static reads
  useEffect(() => {
    let cancelled = false
    async function run(): Promise<void> {
      if (!managerRead) return
      try {
        const [owner, verifier, stablecoin, vault] = await Promise.all([
          managerRead.owner(),
          managerRead.verifier(),
          managerRead.stablecoin(),
          managerRead.vault(),
        ])
        if (cancelled) return
        setManagerOwner(String(owner))
        setManagerVerifier(String(verifier))
        setManagerStablecoin(String(stablecoin))
        setManagerVault(String(vault))
      } catch {
        if (cancelled) return
        setManagerOwner('')
        setManagerVerifier('')
        setManagerStablecoin('')
        setManagerVault('')
      }
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [managerRead])

  // Borrower reads (credit + borrowerInfo + balance)
  useEffect(() => {
    let cancelled = false
    async function run(): Promise<void> {
      if (!managerRead || !ethers.isAddress(borrowerAddress)) {
        setBorrowerInfo(null)
        setAvailableCredit(null)
        setStablecoinBalance(null)
        return
      }

      try {
        const credit = (await managerRead.getAvailableCredit(borrowerAddress)) as bigint
        const infoRaw = (await managerRead.getBorrowerInfo(borrowerAddress)) as unknown

        if (cancelled) return
        setAvailableCredit(credit)

        if (isRecord(infoRaw)) {
          const nested = infoRaw.info
          setBorrowerInfo(isRecord(nested) ? nested : infoRaw)
        } else {
          setBorrowerInfo(null)
        }
      } catch {
        if (cancelled) return
        setBorrowerInfo(null)
        setAvailableCredit(null)
      }

      try {
        if (!stablecoinRead) return
        const [decimals, balance] = await Promise.all([
          stablecoinRead.decimals() as Promise<number>,
          stablecoinRead.balanceOf(borrowerAddress) as Promise<bigint>,
        ])
        if (cancelled) return
        setStablecoinDecimals(Number(decimals))
        setStablecoinBalance(balance)
      } catch {
        if (cancelled) return
        // Default 6 decimals if we can't fetch
        setStablecoinDecimals(6)
        setStablecoinBalance(null)
      }
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [managerRead, stablecoinRead, borrowerAddress])

  // Checkpoint reads
  useEffect(() => {
    let cancelled = false
    async function run(): Promise<void> {
      if (!checkpointRead) {
        setLatestCheckpointHeight(null)
        setLatestCheckpoint(null)
        return
      }
      try {
        const height = await checkpointRead.latestCheckpointHeight()
        if (cancelled) return
        setLatestCheckpointHeight(Number(height))

        // latestCheckpoint() reverts if none; use try/catch
        try {
          const cp = await checkpointRead.latestCheckpoint()
          if (cancelled) return
          setLatestCheckpoint(cp as Record<string, unknown>)
        } catch {
          if (cancelled) return
          setLatestCheckpoint(null)
        }
      } catch {
        if (cancelled) return
        setLatestCheckpointHeight(null)
        setLatestCheckpoint(null)
      }
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [checkpointRead])

  // SPV verifier reads
  useEffect(() => {
    let cancelled = false
    async function run(): Promise<void> {
      if (!spvVerifierRead) {
        setSpvOwner('')
        setSpvCheckpointManagerOnchain('')
        return
      }
      try {
        const [owner, cpManager] = await Promise.all([spvVerifierRead.owner(), spvVerifierRead.checkpointManager()])
        if (cancelled) return
        setSpvOwner(String(owner))
        setSpvCheckpointManagerOnchain(String(cpManager))
      } catch {
        if (cancelled) return
        setSpvOwner('')
        setSpvCheckpointManagerOnchain('')
      }
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [spvVerifierRead])

  useEffect(() => {
    let cancelled = false
    async function run(): Promise<void> {
      if (!spvVerifierRead || !ethers.isAddress(spvBorrower)) {
        setSpvBorrowerOnchainPubkeyHash('')
        return
      }
      try {
        const h = await spvVerifierRead.getBorrowerPubkeyHash(spvBorrower)
        if (cancelled) return
        setSpvBorrowerOnchainPubkeyHash(String(h))
      } catch {
        if (cancelled) return
        setSpvBorrowerOnchainPubkeyHash('')
      }
    }
    void run()
    return () => {
      cancelled = true
    }
  }, [spvVerifierRead, spvBorrower])

  // Convenience: compute keccak256(btcAddressString) for registerBorrower
  useEffect(() => {
    if (!adminBtcAddr) return
    try {
      const hash = ethers.keccak256(ethers.toUtf8Bytes(adminBtcAddr))
      setAdminBtcKeyHash(hash)
    } catch {
      // ignore
    }
  }, [adminBtcAddr])

  async function submitProof(): Promise<void> {
    if (!ethers.isAddress(managerAddress)) {
      setTxState({ status: 'error', label: 'submitPayout', message: 'Invalid manager address' })
      return
    }
    if (!proofHex || !isHexBytes(proofHex) || proofHex === '0x') {
      setTxState({ status: 'error', label: 'submitPayout', message: 'Invalid proof hex (0x...)' })
      return
    }
    await sendContractTx('submitPayout', managerAddress, HashCreditManagerAbi, (c) => c.submitPayout(proofHex))
  }

  async function doBorrow(): Promise<void> {
    if (!ethers.isAddress(managerAddress)) {
      setTxState({ status: 'error', label: 'borrow', message: 'Invalid manager address' })
      return
    }
    const amount = ethers.parseUnits(borrowAmount || '0', stablecoinDecimals)
    await sendContractTx('borrow', managerAddress, HashCreditManagerAbi, (c) => c.borrow(amount))
  }

  async function approveStablecoin(): Promise<void> {
    if (!ethers.isAddress(managerStablecoin) || !ethers.isAddress(managerAddress)) {
      setTxState({ status: 'error', label: 'approve', message: 'Missing stablecoin/manager address' })
      return
    }
    const amount = ethers.parseUnits(approveAmount || '0', stablecoinDecimals)
    await sendContractTx('approve', managerStablecoin, Erc20Abi, (c) => c.approve(managerAddress, amount))
  }

  async function doRepay(): Promise<void> {
    if (!ethers.isAddress(managerAddress)) {
      setTxState({ status: 'error', label: 'repay', message: 'Invalid manager address' })
      return
    }
    const amount = ethers.parseUnits(repayAmount || '0', stablecoinDecimals)
    await sendContractTx('repay', managerAddress, HashCreditManagerAbi, (c) => c.repay(amount))
  }

  async function registerBorrower(): Promise<void> {
    if (!ethers.isAddress(managerAddress)) {
      setTxState({ status: 'error', label: 'registerBorrower', message: 'Invalid manager address' })
      return
    }
    if (!ethers.isAddress(adminBorrower)) {
      setTxState({ status: 'error', label: 'registerBorrower', message: 'Invalid borrower EVM address' })
      return
    }
    if (!adminBtcKeyHash || !isHexBytes(adminBtcKeyHash) || adminBtcKeyHash.length !== 66) {
      setTxState({ status: 'error', label: 'registerBorrower', message: 'Invalid btcPayoutKeyHash (bytes32)' })
      return
    }

    await sendContractTx('registerBorrower', managerAddress, HashCreditManagerAbi, (c) =>
      c.registerBorrower(adminBorrower, adminBtcKeyHash),
    )
  }

  async function setVerifier(): Promise<void> {
    if (!ethers.isAddress(managerAddress) || !ethers.isAddress(adminNewVerifier)) {
      setTxState({ status: 'error', label: 'setVerifier', message: 'Invalid manager/verifier address' })
      return
    }

    await sendContractTx('setVerifier', managerAddress, HashCreditManagerAbi, (c) => c.setVerifier(adminNewVerifier))
  }

  async function setBorrowerPubkeyHash(): Promise<void> {
    if (!ethers.isAddress(spvVerifierAddress)) {
      setTxState({ status: 'error', label: 'setBorrowerPubkeyHash', message: 'Invalid SPV verifier address' })
      return
    }
    if (!ethers.isAddress(spvBorrower)) {
      setTxState({ status: 'error', label: 'setBorrowerPubkeyHash', message: 'Invalid borrower address' })
      return
    }
    if (!spvPubkeyHash || !isHexBytes(spvPubkeyHash) || spvPubkeyHash.length !== 42) {
      setTxState({ status: 'error', label: 'setBorrowerPubkeyHash', message: 'pubkeyHash must be bytes20 (0x + 40 hex)' })
      return
    }

    await sendContractTx('setBorrowerPubkeyHash', spvVerifierAddress, BtcSpvVerifierAbi, (c) =>
      c.setBorrowerPubkeyHash(spvBorrower, spvPubkeyHash),
    )
  }

  const availableCreditDisplay =
    availableCredit === null ? '—' : `${ethers.formatUnits(availableCredit, stablecoinDecimals)} cUSD`
  const stablecoinBalanceDisplay =
    stablecoinBalance === null ? '—' : `${ethers.formatUnits(stablecoinBalance, stablecoinDecimals)} cUSD`
  const txOverview =
    txState.status === 'idle'
      ? 'No tx yet'
      : txState.status === 'signing'
        ? `Signing ${txState.label}`
        : txState.status === 'pending'
          ? `Pending ${txState.label}`
          : txState.status === 'confirmed'
            ? `Confirmed ${txState.label}`
            : `Error ${txState.label}`
  const txOverviewTone =
    txState.status === 'confirmed' ? 'ok' : txState.status === 'error' ? 'err' : txState.status === 'pending' ? 'warn' : ''

  return (
    <div className="layout">
      <div className="chrome">
        <header className="header">
          <div className="brand">
            <div className="brand-mark" aria-hidden="true">
              <span>K</span>
            </div>
            <div className="brand-copy">
              <div className="brand-title">HashCredit.stream</div>
              <div className="brand-subtitle">Creditcoin testnet SPV operations dashboard</div>
            </div>
            <nav className="brand-nav" aria-label="Sections">
              <button type="button" className="nav-pill active">
                Overview
              </button>
              <button type="button" className="nav-pill">
                Credit
              </button>
              <button type="button" className="nav-pill">
                Proofs
              </button>
              <button type="button" className="nav-pill">
                Admin
              </button>
            </nav>
          </div>

          <div className="wallet">
            <div className="wallet-meta">
              <div className="wallet-line">
                <span className="label">Wallet</span>
                <span className="mono">{walletAccount ? shortAddr(walletAccount) : 'Not connected'}</span>
              </div>
              <div className="wallet-line">
                <span className="label">Chain</span>
                <span className="mono">{walletChainId ?? '—'}</span>
                {walletChainId !== null && walletChainId !== chainId ? (
                  <span className="pill warn">expected {chainId}</span>
                ) : null}
              </div>
            </div>

            <div className="wallet-actions">
              <button className="btn" onClick={connectWallet} disabled={!hasInjectedWallet}>
                {hasInjectedWallet ? 'Connect wallet' : 'No wallet'}
              </button>
              <button className="btn secondary" onClick={() => void ensureWalletChain(chainId)} disabled={!hasInjectedWallet}>
                Switch to {chainId}
              </button>
            </div>
          </div>
        </header>

        <div className="search-strip">
          <input
            className="quick-input"
            value={borrowerAddress}
            onChange={(e) => setBorrowerAddress(e.target.value)}
            placeholder="Borrower address / wallet / payout target"
          />
          <button className="btn ghost" onClick={() => setBorrowerAddress(walletAccount)} disabled={!walletAccount}>
            Use connected wallet
          </button>
        </div>

        <section className="metrics">
          <article className="metric-card">
            <div className="metric-k">Network</div>
            <div className="metric-v">Chain {chainId}</div>
            <div className="metric-h">Creditcoin testnet</div>
          </article>
          <article className="metric-card">
            <div className="metric-k">Borrower Credit</div>
            <div className="metric-v">{availableCreditDisplay}</div>
            <div className="metric-h">Decimals {stablecoinDecimals}</div>
          </article>
          <article className="metric-card">
            <div className="metric-k">Stablecoin Balance</div>
            <div className="metric-v">{stablecoinBalanceDisplay}</div>
            <div className="metric-h">Borrower wallet view</div>
          </article>
          <article className="metric-card">
            <div className="metric-k">Transaction Status</div>
            <div className={`metric-v metric-v-small ${txOverviewTone}`}>{txOverview}</div>
            <div className="metric-h">Live signer feedback</div>
          </article>
        </section>
      </div>

      <main className="grid">
        <section className="card">
          <h2>Config</h2>
          <div className="form">
            <label>
              <div className="label">RPC URL (read-only)</div>
              <input value={rpcUrl} onChange={(e) => setRpcUrl(e.target.value)} placeholder="https://..." />
            </label>
            <label>
              <div className="label">Chain ID</div>
              <input
                value={String(chainId)}
                onChange={(e) => setChainId(Number(e.target.value))}
                placeholder="102031"
                inputMode="numeric"
              />
            </label>
            <label>
              <div className="label">HashCreditManager</div>
              <input
                value={managerAddress}
                onChange={(e) => setManagerAddress(e.target.value)}
                placeholder="0x..."
              />
            </label>
            <label>
              <div className="label">BtcSpvVerifier</div>
              <input
                value={spvVerifierAddress}
                onChange={(e) => setSpvVerifierAddress(e.target.value)}
                placeholder="0x..."
              />
            </label>
            <label>
              <div className="label">CheckpointManager</div>
              <input
                value={checkpointManagerAddress}
                onChange={(e) => setCheckpointManagerAddress(e.target.value)}
                placeholder="0x..."
              />
            </label>
          </div>
          <div className="hint">
            `apps/web/.env.example`를 복사해서 `apps/web/.env`를 만들면 기본값을 쉽게 넣을 수 있어요.
          </div>
        </section>

        <section className="card">
          <h2>Manager (read)</h2>
          <div className="kv">
            <div className="row">
              <div className="k">owner</div>
              <div className="v mono">{managerOwner || '—'}</div>
            </div>
            <div className="row">
              <div className="k">verifier</div>
              <div className="v mono">{managerVerifier || '—'}</div>
            </div>
            <div className="row">
              <div className="k">stablecoin</div>
              <div className="v mono">{managerStablecoin || '—'}</div>
            </div>
            <div className="row">
              <div className="k">vault</div>
              <div className="v mono">{managerVault || '—'}</div>
            </div>
          </div>
        </section>

        <section className="card">
          <h2>Borrower</h2>
          <div className="form">
            <label>
              <div className="label">Borrower address</div>
              <input
                value={borrowerAddress}
                onChange={(e) => setBorrowerAddress(e.target.value)}
                placeholder="0x..."
              />
            </label>
          </div>

          <div className="kv">
            <div className="row">
              <div className="k">availableCredit</div>
              <div className="v mono">
                {availableCredit === null ? '—' : `${ethers.formatUnits(availableCredit, stablecoinDecimals)} (decimals=${stablecoinDecimals})`}
              </div>
            </div>
            <div className="row">
              <div className="k">stablecoin balance</div>
              <div className="v mono">
                {stablecoinBalance === null ? '—' : ethers.formatUnits(stablecoinBalance, stablecoinDecimals)}
              </div>
            </div>
            <div className="row">
              <div className="k">borrowerInfo</div>
              <div className="v mono pre">
                {borrowerInfo ? JSON.stringify(borrowerInfo, null, 2) : '—'}
              </div>
            </div>
          </div>

          <div className="split">
            <div className="action">
              <div className="label">Borrow amount</div>
              <div className="inline">
                <input value={borrowAmount} onChange={(e) => setBorrowAmount(e.target.value)} />
                <button className="btn" onClick={() => void doBorrow()} disabled={!walletAccount}>
                  Borrow
                </button>
              </div>
            </div>
            <div className="action">
              <div className="label">Approve amount</div>
              <div className="inline">
                <input value={approveAmount} onChange={(e) => setApproveAmount(e.target.value)} />
                <button className="btn secondary" onClick={() => void approveStablecoin()} disabled={!walletAccount}>
                  Approve
                </button>
              </div>
            </div>
            <div className="action">
              <div className="label">Repay amount</div>
              <div className="inline">
                <input value={repayAmount} onChange={(e) => setRepayAmount(e.target.value)} />
                <button className="btn" onClick={() => void doRepay()} disabled={!walletAccount}>
                  Repay
                </button>
              </div>
            </div>
          </div>

          <div className="hint">
            금액 입력은 “사람이 보는 단위”로 입력합니다. (예: `1000` = 1000 USDC)
          </div>
        </section>

        <section className="card">
          <h2>Submit payout proof</h2>
          <div className="hint">
            `hashcredit-prover build-proof --hex` 또는 `submit-proof`(추가 예정)로 만든 proof hex(`0x...`)를 붙여넣고 제출합니다.
          </div>
          <textarea
            value={proofHex}
            onChange={(e) => setProofHex(e.target.value.trim())}
            placeholder="0x..."
            rows={6}
          />
          <div className="actions">
            <button className="btn" onClick={() => void submitProof()} disabled={!walletAccount}>
              submitPayout
            </button>
          </div>
        </section>

        <section className="card">
          <h2>Checkpoint (read)</h2>
          <div className="kv">
            <div className="row">
              <div className="k">latestCheckpointHeight</div>
              <div className="v mono">{latestCheckpointHeight ?? '—'}</div>
            </div>
            <div className="row">
              <div className="k">latestCheckpoint</div>
              <div className="v mono pre">{latestCheckpoint ? JSON.stringify(latestCheckpoint, null, 2) : '—'}</div>
            </div>
          </div>
        </section>

        <section className="card">
          <h2>SPV verifier (read)</h2>
          <div className="kv">
            <div className="row">
              <div className="k">owner</div>
              <div className="v mono">{spvOwner || '—'}</div>
            </div>
            <div className="row">
              <div className="k">checkpointManager</div>
              <div className="v mono">{spvCheckpointManagerOnchain || '—'}</div>
            </div>
          </div>
        </section>

        <section className="card">
          <h2>Admin (Manager)</h2>
          <div className="hint">owner만 성공합니다. 실패 시 revert 이유를 아래 상태에서 확인하세요.</div>
          <div className="form">
            <label>
              <div className="label">registerBorrower: borrower</div>
              <input value={adminBorrower} onChange={(e) => setAdminBorrower(e.target.value)} placeholder="0x..." />
            </label>
            <label>
              <div className="label">BTC address (string → keccak)</div>
              <input value={adminBtcAddr} onChange={(e) => setAdminBtcAddr(e.target.value)} placeholder="tb1..." />
            </label>
            <label>
              <div className="label">btcPayoutKeyHash (bytes32)</div>
              <input
                value={adminBtcKeyHash}
                onChange={(e) => setAdminBtcKeyHash(e.target.value)}
                placeholder="0x..."
              />
            </label>
            <div className="actions">
              <button className="btn secondary" onClick={() => void registerBorrower()} disabled={!walletAccount}>
                registerBorrower
              </button>
            </div>
          </div>

          <div className="form">
            <label>
              <div className="label">setVerifier: newVerifier</div>
              <input
                value={adminNewVerifier}
                onChange={(e) => setAdminNewVerifier(e.target.value)}
                placeholder="0x..."
              />
            </label>
            <div className="actions">
              <button className="btn secondary" onClick={() => void setVerifier()} disabled={!walletAccount}>
                setVerifier
              </button>
            </div>
          </div>
        </section>

        <section className="card">
          <h2>Admin (SPV verifier)</h2>
          <div className="hint">
            `setBorrowerPubkeyHash`는 SPV 경로에서 필수입니다. (주소 디코딩 자동화는 prover/툴링 티켓에서 진행)
          </div>
          <div className="form">
            <label>
              <div className="label">borrower</div>
              <input value={spvBorrower} onChange={(e) => setSpvBorrower(e.target.value)} placeholder="0x..." />
            </label>
            <label>
              <div className="label">pubkeyHash (bytes20)</div>
              <input
                value={spvPubkeyHash}
                onChange={(e) => setSpvPubkeyHash(e.target.value)}
                placeholder="0x + 40 hex"
              />
            </label>
            <div className="kv">
              <div className="row">
                <div className="k">on-chain pubkeyHash</div>
                <div className="v mono">{spvBorrowerOnchainPubkeyHash || '—'}</div>
              </div>
            </div>
            <div className="actions">
              <button className="btn secondary" onClick={() => void setBorrowerPubkeyHash()} disabled={!walletAccount}>
                setBorrowerPubkeyHash
              </button>
            </div>
          </div>
        </section>

        <section className="card full">
          <h2>Tx status</h2>
          {txState.status === 'idle' ? (
            <div className="hint">아직 전송한 트랜잭션이 없습니다.</div>
          ) : txState.status === 'signing' ? (
            <div className="pill">Signing: {txState.label}</div>
          ) : txState.status === 'pending' ? (
            <div className="pill warn">
              Pending: {txState.label} <span className="mono">{txState.hash}</span>
            </div>
          ) : txState.status === 'confirmed' ? (
            <div className="pill ok">
              Confirmed: {txState.label} <span className="mono">{txState.hash}</span>
            </div>
          ) : (
            <div className="pill err">
              Error: {txState.label} — {txState.message}
            </div>
          )}
        </section>
      </main>

      <footer className="footer">
        <div className="hint">
          이 UI는 “얇은 운영 대시보드”입니다. SPV proof 생성/체크포인트 등록 자동화는 prover/브리지 API 티켓(T1.7~T1.14)에서
          진행합니다.
        </div>
      </footer>
    </div>
  )
}

export default App
