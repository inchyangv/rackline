import { useEffect, useMemo, useState } from 'react'
import { BrowserProvider, Contract, ethers, JsonRpcProvider, Wallet } from 'ethers'
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

function getLocalStorageString(key: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback
  try {
    const v = window.localStorage.getItem(key)
    return v === null ? fallback : v
  } catch {
    return fallback
  }
}

function setLocalStorageString(key: string, value: string): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(key, value)
  } catch {
    // ignore
  }
}

async function copyToClipboard(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
    return
  } catch {
    // ignore; fallback below
  }

  // Fallback for older/locked-down contexts
  const el = document.createElement('textarea')
  el.value = text
  el.style.position = 'fixed'
  el.style.left = '-9999px'
  el.style.top = '0'
  document.body.appendChild(el)
  el.focus()
  el.select()
  try {
    document.execCommand('copy')
  } finally {
    document.body.removeChild(el)
  }
}

function normalizeBaseUrl(url: string): string {
  return url.trim().replace(/\/+$/, '')
}

type TabId = 'dashboard' | 'ops' | 'proof' | 'admin' | 'config'

type DemoWallet = {
  name: string
  address: string
  privateKey: string
  createdAt: number
}

function parseDemoWallets(raw: string): DemoWallet[] {
  try {
    const v = JSON.parse(raw) as unknown
    if (!Array.isArray(v)) return []
    return v
      .filter((x) => isRecord(x))
      .map((x) => ({
        name: typeof x.name === 'string' ? x.name : '데모 지갑',
        address: typeof x.address === 'string' ? x.address : '',
        privateKey: typeof x.privateKey === 'string' ? x.privateKey : '',
        createdAt: typeof x.createdAt === 'number' ? x.createdAt : Date.now(),
      }))
      .filter((w) => ethers.isAddress(w.address) && /^0x[0-9a-fA-F]{64}$/.test(w.privateKey))
  } catch {
    return []
  }
}

function App() {
  const [tab, setTab] = useState<TabId>(() => {
    const v = getLocalStorageString('hashcredit_tab', 'dashboard')
    return v === 'dashboard' || v === 'ops' || v === 'proof' || v === 'admin' || v === 'config' ? v : 'dashboard'
  })

  // Config (read-only provider)
  const [rpcUrl, setRpcUrl] = useState(env.rpcUrl)
  const [chainId, setChainId] = useState(env.chainId)
  const [managerAddress, setManagerAddress] = useState(env.hashCreditManager)
  const [spvVerifierAddress, setSpvVerifierAddress] = useState(env.btcSpvVerifier)
  const [checkpointManagerAddress, setCheckpointManagerAddress] = useState(env.checkpointManager)

  // Operator API (demo-only; do not use production tokens here)
  const [apiUrl, setApiUrl] = useState(() => getLocalStorageString('hashcredit_api_url', env.apiUrl))
  const [apiToken, setApiToken] = useState(() => getLocalStorageString('hashcredit_api_token', ''))
  const [apiBusy, setApiBusy] = useState<boolean>(false)
  const [apiLog, setApiLog] = useState<string>('')
  const [apiDryRun, setApiDryRun] = useState<boolean>(false)
  const [apiCheckpointHeight, setApiCheckpointHeight] = useState<string>('')
  const [apiTxid, setApiTxid] = useState<string>('')
  const [apiVout, setApiVout] = useState<string>('0')
  const [apiProofCheckpointHeight, setApiProofCheckpointHeight] = useState<string>('')
  const [apiTargetHeight, setApiTargetHeight] = useState<string>('')

  // Demo wallets (demo-only; never use this pattern for production keys)
  const [demoWallets, setDemoWallets] = useState<DemoWallet[]>(() =>
    parseDemoWallets(getLocalStorageString('hashcredit_demo_wallets', '[]')),
  )

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
      setTxState({ status: 'error', label: 'wallet', message: '브라우저 지갑을 찾지 못했습니다. (MetaMask 등)' })
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
      setTxState({ status: 'error', label, message: '컨트랙트 주소가 올바르지 않습니다.' })
      return
    }

    setTxState({ status: 'signing', label })
    try {
      const ok = await ensureWalletChain(chainId)
      if (!ok) throw new Error(`네트워크 전환에 실패했습니다. (chainId=${chainId})`)

      const ethereum = getEthereum()
      if (!ethereum) throw new Error('브라우저 지갑을 찾지 못했습니다.')

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

  useEffect(() => {
    setLocalStorageString('hashcredit_api_url', apiUrl)
  }, [apiUrl])

  useEffect(() => {
    setLocalStorageString('hashcredit_api_token', apiToken)
  }, [apiToken])

  useEffect(() => {
    setLocalStorageString('hashcredit_tab', tab)
  }, [tab])

  useEffect(() => {
    setLocalStorageString('hashcredit_demo_wallets', JSON.stringify(demoWallets))
  }, [demoWallets])

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

  function createDemoWallet(count: number): void {
    const n = Math.max(1, Math.min(5, Math.floor(count)))
    const now = Date.now()
    const next: DemoWallet[] = []
    for (let i = 0; i < n; i++) {
      const w = Wallet.createRandom()
      next.push({
        name: `데모 지갑 #${demoWallets.length + i + 1}`,
        address: w.address,
        privateKey: w.privateKey,
        createdAt: now,
      })
    }
    setDemoWallets((prev) => [...next, ...prev].slice(0, 10))
  }

  function removeDemoWallet(address: string): void {
    setDemoWallets((prev) => prev.filter((w) => w.address !== address))
  }

  function applyAsBorrower(address: string): void {
    setBorrowerAddress(address)
    setAdminBorrower(address)
    setSpvBorrower(address)
  }

  async function apiRequest(path: string, init?: RequestInit): Promise<unknown> {
    const base = normalizeBaseUrl(apiUrl)
    if (!base) throw new Error('API URL이 비어 있습니다. (VITE_API_URL 또는 입력값)')

    const headers = new Headers(init?.headers)
    if (!headers.has('content-type')) headers.set('content-type', 'application/json')
    if (apiToken) headers.set('X-API-Key', apiToken)

    const res = await fetch(`${base}${path}`, { ...init, headers })
    const text = await res.text()
    let json: unknown = null
    try {
      json = text ? JSON.parse(text) : null
    } catch {
      json = { raw: text }
    }
    if (!res.ok) {
      const msg = typeof json === 'object' && json !== null && 'detail' in json ? String((json as any).detail) : text
      throw new Error(`API ${res.status}: ${msg}`)
    }
    return json
  }

  async function apiRun(label: string, fn: () => Promise<unknown>): Promise<void> {
    setApiBusy(true)
    setApiLog('')
    try {
      const result = await fn()
      setApiLog(`${label}\n${JSON.stringify(result, null, 2)}`)
    } catch (e) {
      setApiLog(`${label}\nERROR: ${getErrorMessage(e)}`)
    } finally {
      setApiBusy(false)
    }
  }

  async function apiHealth(): Promise<void> {
    await apiRun('GET /health', async () => apiRequest('/health', { method: 'GET' }))
  }

  async function apiSetCheckpoint(): Promise<void> {
    const height = Number(apiCheckpointHeight)
    if (!Number.isFinite(height) || height <= 0) {
      setApiLog('POST /checkpoint/set\nERROR: height가 올바르지 않습니다.')
      return
    }
    await apiRun('POST /checkpoint/set', async () =>
      apiRequest('/checkpoint/set', {
        method: 'POST',
        body: JSON.stringify({ height, dry_run: apiDryRun }),
      }),
    )
  }

  async function apiSetBorrowerPubkeyHash(): Promise<void> {
    if (!ethers.isAddress(spvBorrower)) {
      setApiLog('POST /borrower/set-pubkey-hash\nERROR: borrower EVM 주소가 올바르지 않습니다.')
      return
    }
    if (!adminBtcAddr) {
      setApiLog('POST /borrower/set-pubkey-hash\nERROR: BTC 주소가 비어 있습니다.')
      return
    }
    await apiRun('POST /borrower/set-pubkey-hash', async () =>
      apiRequest('/borrower/set-pubkey-hash', {
        method: 'POST',
        body: JSON.stringify({ borrower: spvBorrower, btc_address: adminBtcAddr, dry_run: apiDryRun }),
      }),
    )
  }

  async function apiRegisterBorrower(): Promise<void> {
    if (!ethers.isAddress(adminBorrower)) {
      setApiLog('POST /manager/register-borrower\nERROR: borrower EVM 주소가 올바르지 않습니다.')
      return
    }
    if (!adminBtcAddr) {
      setApiLog('POST /manager/register-borrower\nERROR: BTC 주소가 비어 있습니다.')
      return
    }
    await apiRun('POST /manager/register-borrower', async () => {
      const result = await apiRequest('/manager/register-borrower', {
        method: 'POST',
        body: JSON.stringify({ borrower: adminBorrower, btc_address: adminBtcAddr, dry_run: apiDryRun }),
      })
      if (typeof result === 'object' && result !== null && 'btc_payout_key_hash' in (result as any)) {
        const keyHash = (result as any).btc_payout_key_hash
        if (typeof keyHash === 'string') setAdminBtcKeyHash(keyHash)
      }
      return result
    })
  }

  async function apiBuildProof(): Promise<void> {
    const outputIndex = Number(apiVout)
    const checkpointHeight = Number(apiProofCheckpointHeight)
    const targetHeight = Number(apiTargetHeight)
    if (!apiTxid) {
      setApiLog('POST /spv/build-proof\nERROR: txid가 비어 있습니다.')
      return
    }
    if (!Number.isFinite(outputIndex) || outputIndex < 0) {
      setApiLog('POST /spv/build-proof\nERROR: vout이 올바르지 않습니다.')
      return
    }
    if (!Number.isFinite(checkpointHeight) || checkpointHeight <= 0) {
      setApiLog('POST /spv/build-proof\nERROR: checkpoint_height가 올바르지 않습니다.')
      return
    }
    if (!Number.isFinite(targetHeight) || targetHeight <= 0) {
      setApiLog('POST /spv/build-proof\nERROR: target_height가 올바르지 않습니다.')
      return
    }
    if (!ethers.isAddress(spvBorrower)) {
      setApiLog('POST /spv/build-proof\nERROR: borrower EVM 주소가 올바르지 않습니다.')
      return
    }

    await apiRun('POST /spv/build-proof', async () => {
      const result = await apiRequest('/spv/build-proof', {
        method: 'POST',
        body: JSON.stringify({
          txid: apiTxid,
          output_index: outputIndex,
          checkpoint_height: checkpointHeight,
          target_height: targetHeight,
          borrower: spvBorrower,
        }),
      })
      if (typeof result === 'object' && result !== null && (result as any).success && typeof (result as any).proof_hex === 'string') {
        setProofHex((result as any).proof_hex)
      }
      return result
    })
  }

  async function apiSubmitProof(): Promise<void> {
    if (!proofHex || !isHexBytes(proofHex) || proofHex === '0x') {
      setApiLog('POST /spv/submit\nERROR: proof_hex가 올바르지 않습니다.')
      return
    }
    await apiRun('POST /spv/submit', async () =>
      apiRequest('/spv/submit', {
        method: 'POST',
        body: JSON.stringify({ proof_hex: proofHex, dry_run: apiDryRun }),
      }),
    )
  }

  async function apiBuildAndSubmit(): Promise<void> {
    const outputIndex = Number(apiVout)
    const checkpointHeight = Number(apiProofCheckpointHeight)
    const targetHeight = Number(apiTargetHeight)
    if (!apiTxid || !Number.isFinite(outputIndex) || outputIndex < 0) {
      setApiLog('원클릭\nERROR: txid/vout 입력이 필요합니다.')
      return
    }
    if (!Number.isFinite(checkpointHeight) || checkpointHeight <= 0 || !Number.isFinite(targetHeight) || targetHeight <= 0) {
      setApiLog('원클릭\nERROR: checkpoint_height/target_height 입력이 필요합니다.')
      return
    }
    if (!ethers.isAddress(spvBorrower)) {
      setApiLog('원클릭\nERROR: borrower EVM 주소가 올바르지 않습니다.')
      return
    }

    await apiRun('원클릭: build-proof -> submit', async () => {
      const built = await apiRequest('/spv/build-proof', {
        method: 'POST',
        body: JSON.stringify({
          txid: apiTxid,
          output_index: outputIndex,
          checkpoint_height: checkpointHeight,
          target_height: targetHeight,
          borrower: spvBorrower,
        }),
      })
      if (!(typeof built === 'object' && built !== null && (built as any).success && typeof (built as any).proof_hex === 'string')) {
        return { build: built, submit: null }
      }
      const builtProofHex = (built as any).proof_hex as string
      setProofHex(builtProofHex)
      const submitted = await apiRequest('/spv/submit', {
        method: 'POST',
        body: JSON.stringify({ proof_hex: builtProofHex, dry_run: apiDryRun }),
      })
      return { build: built, submit: submitted }
    })
  }

  async function submitProof(): Promise<void> {
    if (!ethers.isAddress(managerAddress)) {
      setTxState({ status: 'error', label: 'submitPayout', message: 'Manager 주소가 올바르지 않습니다.' })
      return
    }
    if (!proofHex || !isHexBytes(proofHex) || proofHex === '0x') {
      setTxState({ status: 'error', label: 'submitPayout', message: 'proofHex가 올바르지 않습니다. (0x...)' })
      return
    }
    await sendContractTx('submitPayout', managerAddress, HashCreditManagerAbi, (c) => c.submitPayout(proofHex))
  }

  async function doBorrow(): Promise<void> {
    if (!ethers.isAddress(managerAddress)) {
      setTxState({ status: 'error', label: 'borrow', message: 'Manager 주소가 올바르지 않습니다.' })
      return
    }
    const amount = ethers.parseUnits(borrowAmount || '0', stablecoinDecimals)
    await sendContractTx('borrow', managerAddress, HashCreditManagerAbi, (c) => c.borrow(amount))
  }

  async function approveStablecoin(): Promise<void> {
    if (!ethers.isAddress(managerStablecoin) || !ethers.isAddress(managerAddress)) {
      setTxState({ status: 'error', label: 'approve', message: 'Stablecoin 또는 Manager 주소가 비어 있거나 올바르지 않습니다.' })
      return
    }
    const amount = ethers.parseUnits(approveAmount || '0', stablecoinDecimals)
    await sendContractTx('approve', managerStablecoin, Erc20Abi, (c) => c.approve(managerAddress, amount))
  }

  async function doRepay(): Promise<void> {
    if (!ethers.isAddress(managerAddress)) {
      setTxState({ status: 'error', label: 'repay', message: 'Manager 주소가 올바르지 않습니다.' })
      return
    }
    const amount = ethers.parseUnits(repayAmount || '0', stablecoinDecimals)
    await sendContractTx('repay', managerAddress, HashCreditManagerAbi, (c) => c.repay(amount))
  }

  async function registerBorrower(): Promise<void> {
    if (!ethers.isAddress(managerAddress)) {
      setTxState({ status: 'error', label: 'registerBorrower', message: 'Manager 주소가 올바르지 않습니다.' })
      return
    }
    if (!ethers.isAddress(adminBorrower)) {
      setTxState({ status: 'error', label: 'registerBorrower', message: 'Borrower(EVM) 주소가 올바르지 않습니다.' })
      return
    }
    if (!adminBtcKeyHash || !isHexBytes(adminBtcKeyHash) || adminBtcKeyHash.length !== 66) {
      setTxState({ status: 'error', label: 'registerBorrower', message: 'btcPayoutKeyHash가 올바르지 않습니다. (bytes32)' })
      return
    }

    await sendContractTx('registerBorrower', managerAddress, HashCreditManagerAbi, (c) =>
      c.registerBorrower(adminBorrower, adminBtcKeyHash),
    )
  }

  async function setVerifier(): Promise<void> {
    if (!ethers.isAddress(managerAddress) || !ethers.isAddress(adminNewVerifier)) {
      setTxState({ status: 'error', label: 'setVerifier', message: 'Manager 또는 Verifier 주소가 올바르지 않습니다.' })
      return
    }

    await sendContractTx('setVerifier', managerAddress, HashCreditManagerAbi, (c) => c.setVerifier(adminNewVerifier))
  }

  async function setBorrowerPubkeyHash(): Promise<void> {
    if (!ethers.isAddress(spvVerifierAddress)) {
      setTxState({ status: 'error', label: 'setBorrowerPubkeyHash', message: 'SPV Verifier 주소가 올바르지 않습니다.' })
      return
    }
    if (!ethers.isAddress(spvBorrower)) {
      setTxState({ status: 'error', label: 'setBorrowerPubkeyHash', message: 'Borrower(EVM) 주소가 올바르지 않습니다.' })
      return
    }
    if (!spvPubkeyHash || !isHexBytes(spvPubkeyHash) || spvPubkeyHash.length !== 42) {
      setTxState({ status: 'error', label: 'setBorrowerPubkeyHash', message: 'pubkeyHash는 bytes20이어야 합니다. (0x + 40 hex)' })
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
      ? '아직 트랜잭션 없음'
      : txState.status === 'signing'
        ? `서명 대기: ${txState.label}`
        : txState.status === 'pending'
          ? `전송됨(대기): ${txState.label}`
          : txState.status === 'confirmed'
            ? `확정됨: ${txState.label}`
            : `오류: ${txState.label}`
  const txOverviewTone =
    txState.status === 'confirmed' ? 'ok' : txState.status === 'error' ? 'err' : txState.status === 'pending' ? 'warn' : ''

  return (
    <div className="layout">
      <div className="chrome">
        <header className="header">
          <div className="brand">
            <div className="brand-mark" aria-hidden="true">
              <span>HC</span>
            </div>
            <div className="brand-copy">
              <div className="brand-title">HashCredit</div>
              <div className="brand-subtitle">Creditcoin 테스트넷 SPV 데모 대시보드</div>
            </div>
            <nav className="brand-nav" aria-label="Sections">
              <button type="button" className={`nav-pill ${tab === 'dashboard' ? 'active' : ''}`} onClick={() => setTab('dashboard')}>
                대시보드
              </button>
              <button type="button" className={`nav-pill ${tab === 'ops' ? 'active' : ''}`} onClick={() => setTab('ops')}>
                운영(API)
              </button>
              <button type="button" className={`nav-pill ${tab === 'proof' ? 'active' : ''}`} onClick={() => setTab('proof')}>
                증명/제출
              </button>
              <button type="button" className={`nav-pill ${tab === 'admin' ? 'active' : ''}`} onClick={() => setTab('admin')}>
                관리자
              </button>
              <button type="button" className={`nav-pill ${tab === 'config' ? 'active' : ''}`} onClick={() => setTab('config')}>
                설정
              </button>
            </nav>
          </div>

          <div className="wallet">
            <div className="wallet-meta">
              <div className="wallet-line">
                <span className="label">지갑</span>
                <span className="mono">{walletAccount ? shortAddr(walletAccount) : '미연결'}</span>
              </div>
              <div className="wallet-line">
                <span className="label">체인</span>
                <span className="mono">{walletChainId ?? '—'}</span>
                {walletChainId !== null && walletChainId !== chainId ? (
                  <span className="pill warn">예상: {chainId}</span>
                ) : null}
              </div>
            </div>

            <div className="wallet-actions">
              <button className="btn" onClick={connectWallet} disabled={!hasInjectedWallet}>
                {hasInjectedWallet ? '지갑 연결' : '지갑 없음'}
              </button>
              <button className="btn secondary" onClick={() => void ensureWalletChain(chainId)} disabled={!hasInjectedWallet}>
                체인 전환({chainId})
              </button>
            </div>
          </div>
        </header>

        <div className="search-strip">
          <input
            className="quick-input"
            value={borrowerAddress}
            onChange={(e) => setBorrowerAddress(e.target.value)}
            placeholder="차입자 주소(EVM) / 지갑 / payout 대상"
          />
          <button className="btn ghost" onClick={() => setBorrowerAddress(walletAccount)} disabled={!walletAccount}>
            연결 지갑 사용
          </button>
        </div>

        <section className="metrics">
          <article className="metric-card">
            <div className="metric-k">네트워크</div>
            <div className="metric-v">Chain {chainId}</div>
            <div className="metric-h">Creditcoin 테스트넷</div>
          </article>
          <article className="metric-card">
            <div className="metric-k">가용 크레딧</div>
            <div className="metric-v">{availableCreditDisplay}</div>
            <div className="metric-h">decimals: {stablecoinDecimals}</div>
          </article>
          <article className="metric-card">
            <div className="metric-k">스테이블코인 잔고</div>
            <div className="metric-v">{stablecoinBalanceDisplay}</div>
            <div className="metric-h">차입자 기준 조회</div>
          </article>
          <article className="metric-card">
            <div className="metric-k">트랜잭션 상태</div>
            <div className={`metric-v metric-v-small ${txOverviewTone}`}>{txOverview}</div>
            <div className="metric-h">지갑 서명 상태</div>
          </article>
        </section>
      </div>

      <main className="grid">
        {tab === 'dashboard' ? (
          <>
            <section className="card">
              <h2>차입자</h2>
              <div className="form">
                <label>
                  <div className="label">차입자 주소(EVM)</div>
                  <input value={borrowerAddress} onChange={(e) => setBorrowerAddress(e.target.value)} placeholder="0x..." />
                </label>
              </div>

              <div className="kv">
                <div className="row">
                  <div className="k">availableCredit</div>
                  <div className="v mono">
                    {availableCredit === null
                      ? '—'
                      : `${ethers.formatUnits(availableCredit, stablecoinDecimals)} (decimals=${stablecoinDecimals})`}
                  </div>
                </div>
                <div className="row">
                  <div className="k">stablecoinBalance</div>
                  <div className="v mono">
                    {stablecoinBalance === null ? '—' : ethers.formatUnits(stablecoinBalance, stablecoinDecimals)}
                  </div>
                </div>
                <div className="row">
                  <div className="k">borrowerInfo</div>
                  <div className="v mono pre">{borrowerInfo ? JSON.stringify(borrowerInfo, null, 2) : '—'}</div>
                </div>
              </div>

              <div className="split">
                <div className="action">
                  <div className="label">Borrow (대출 실행)</div>
                  <div className="inline">
                    <input value={borrowAmount} onChange={(e) => setBorrowAmount(e.target.value)} placeholder="예: 1000" />
                    <button className="btn" onClick={() => void doBorrow()} disabled={!walletAccount}>
                      대출
                    </button>
                  </div>
                </div>
                <div className="action">
                  <div className="label">Approve (스테이블코인 승인)</div>
                  <div className="inline">
                    <input value={approveAmount} onChange={(e) => setApproveAmount(e.target.value)} placeholder="예: 1000000" />
                    <button className="btn secondary" onClick={() => void approveStablecoin()} disabled={!walletAccount}>
                      승인
                    </button>
                  </div>
                </div>
                <div className="action">
                  <div className="label">Repay (상환)</div>
                  <div className="inline">
                    <input value={repayAmount} onChange={(e) => setRepayAmount(e.target.value)} placeholder="예: 100" />
                    <button className="btn" onClick={() => void doRepay()} disabled={!walletAccount}>
                      상환
                    </button>
                  </div>
                </div>
              </div>

              <div className="hint">금액 입력은 사람이 보는 단위로 입력합니다. (예: `1000` = 1000 USDC)</div>
            </section>

            <section className="card">
              <h2>매니저(조회)</h2>
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
              <div className="hint">
                운영 흐름: `CheckpointManager`에 체크포인트 등록 → `BtcSpvVerifier`에 borrower `pubkeyHash` 등록 → `registerBorrower` →
                proof 생성/제출.
              </div>
            </section>

            <section className="card">
              <h2>체크포인트(조회)</h2>
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
              <h2>SPV Verifier(조회)</h2>
              <div className="kv">
                <div className="row">
                  <div className="k">owner</div>
                  <div className="v mono">{spvOwner || '—'}</div>
                </div>
                <div className="row">
                  <div className="k">checkpointManager</div>
                  <div className="v mono">{spvCheckpointManagerOnchain || '—'}</div>
                </div>
                <div className="row">
                  <div className="k">borrowerPubkeyHash</div>
                  <div className="v mono">{spvBorrowerOnchainPubkeyHash || '—'}</div>
                </div>
              </div>
            </section>

            <section className="card full">
              <h2>데모 지갑(생성)</h2>
              <div className="hint">
                데모 전용입니다. 여기서 생성한 개인키는 브라우저 로컬스토리지에 저장됩니다. 절대 메인넷/실자산에 사용하지 마세요.
              </div>
              <div className="actions">
                <button className="btn secondary" onClick={() => createDemoWallet(1)}>
                  지갑 1개 생성
                </button>
                <button className="btn" onClick={() => createDemoWallet(3)}>
                  지갑 3개 생성
                </button>
              </div>

              {demoWallets.length === 0 ? (
                <div className="hint">아직 생성된 데모 지갑이 없습니다.</div>
              ) : (
                <div className="list" aria-label="demo wallets">
                  {demoWallets.map((w) => (
                    <div className="list-item" key={w.address}>
                      <div className="list-head">
                        <div style={{ minWidth: 0 }}>
                          <div className="list-title">{w.name}</div>
                          <div className="list-meta mono">{w.address}</div>
                        </div>
                        <div className="mini-actions">
                          <button className="btn tiny secondary" onClick={() => applyAsBorrower(w.address)}>
                            borrower로 적용
                          </button>
                          <button className="btn tiny ghost" onClick={() => void copyToClipboard(w.address)}>
                            주소 복사
                          </button>
                          <button className="btn tiny ghost" onClick={() => void copyToClipboard(w.privateKey)}>
                            개인키 복사
                          </button>
                          <button className="btn tiny" onClick={() => removeDemoWallet(w.address)}>
                            삭제
                          </button>
                        </div>
                      </div>
                      <div className="sep" />
                      <div className="hint">
                        생성 시각: {new Date(w.createdAt).toLocaleString()} | 개인키: <span className="mono">{shortAddr(w.privateKey)}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </>
        ) : null}

        {tab === 'ops' ? (
          <section className="card full">
            <h2>SPV 데모 자동화(API)</h2>
            <div className="hint">
              Railway에 배포한 `hashcredit-api`를 호출해서, SPV 체크포인트/borrower 등록/증명 생성/제출을 버튼으로 수행합니다. (데모 목적:
              브라우저에 API 토큰을 입력하므로, 데모 후 토큰을 반드시 교체하세요.)
            </div>

            <div className="form">
              <label>
                <div className="label">API URL</div>
                <input value={apiUrl} onChange={(e) => setApiUrl(e.target.value)} placeholder="https://api-hashcredit...." />
              </label>
              <label>
                <div className="label">API 토큰 (X-API-Key)</div>
                <input value={apiToken} onChange={(e) => setApiToken(e.target.value)} placeholder="(demo token)" type="password" />
              </label>
              <label className="checkRow">
                <input type="checkbox" checked={apiDryRun} onChange={(e) => setApiDryRun(e.target.checked)} />
                <span className="label">dry_run</span>
              </label>
              <div className="actions">
                <button className="btn secondary" onClick={() => void apiHealth()} disabled={apiBusy}>
                  헬스체크
                </button>
              </div>
            </div>

            <div className="form">
              <label>
                <div className="label">체크포인트 높이(height)</div>
                <input value={apiCheckpointHeight} onChange={(e) => setApiCheckpointHeight(e.target.value)} placeholder="예: 4842343" />
              </label>
              <div className="actions">
                <button className="btn secondary" onClick={() => void apiSetCheckpoint()} disabled={apiBusy}>
                  체크포인트 등록(API)
                </button>
              </div>
            </div>

            <div className="form">
              <label>
                <div className="label">차입자 (EVM)</div>
                <input value={spvBorrower} onChange={(e) => setSpvBorrower(e.target.value)} placeholder="0x..." />
              </label>
              <label>
                <div className="label">Borrower BTC 주소</div>
                <input value={adminBtcAddr} onChange={(e) => setAdminBtcAddr(e.target.value)} placeholder="tb1..." />
              </label>
              <div className="actions">
                <button className="btn secondary" onClick={() => void apiSetBorrowerPubkeyHash()} disabled={apiBusy}>
                  pubkeyHash 등록(API)
                </button>
              </div>
            </div>

            <div className="form">
              <label>
                <div className="label">registerBorrower: borrower</div>
                <input value={adminBorrower} onChange={(e) => setAdminBorrower(e.target.value)} placeholder="0x..." />
              </label>
              <div className="actions">
                <button className="btn secondary" onClick={() => void apiRegisterBorrower()} disabled={apiBusy}>
                  registerBorrower(API)
                </button>
              </div>
              <div className="hint">BTC 주소 문자열 keccak은 API에서 계산합니다. (응답의 btc_payout_key_hash로 아래 input도 자동 채움)</div>
            </div>

            <div className="form">
              <label>
                <div className="label">txid</div>
                <input value={apiTxid} onChange={(e) => setApiTxid(e.target.value.trim())} placeholder="예: e4c6..." />
              </label>
              <label>
                <div className="label">vout</div>
                <input value={apiVout} onChange={(e) => setApiVout(e.target.value)} placeholder="0" />
              </label>
              <label>
                <div className="label">checkpoint_height</div>
                <input
                  value={apiProofCheckpointHeight}
                  onChange={(e) => setApiProofCheckpointHeight(e.target.value)}
                  placeholder="예: 4842333"
                />
              </label>
              <label>
                <div className="label">target_height</div>
                <input value={apiTargetHeight} onChange={(e) => setApiTargetHeight(e.target.value)} placeholder="예: 4842343" />
              </label>
              <div className="actions">
                <button className="btn secondary" onClick={() => void apiBuildProof()} disabled={apiBusy}>
                  proof 생성(API) → proofHex 채우기
                </button>
                <button className="btn secondary" onClick={() => void apiSubmitProof()} disabled={apiBusy}>
                  proof 제출(API)
                </button>
                <button className="btn" onClick={() => void apiBuildAndSubmit()} disabled={apiBusy}>
                  원클릭(생성+제출)
                </button>
              </div>
            </div>

            <div className="kv">
              <div className="row">
                <div className="k">API 결과</div>
                <div className="v mono pre">{apiLog || '—'}</div>
              </div>
            </div>
          </section>
        ) : null}

        {tab === 'proof' ? (
          <>
            <section className="card full">
              <h2>증명 생성/제출(API)</h2>
              <div className="hint">
                Proof 생성/제출은 Railway의 API를 통해 수행합니다. (API URL/TOKEN이 비어 있으면 먼저 운영(API) 탭에서 설정하세요.)
              </div>
              <div className="form">
                <label>
                  <div className="label">API URL</div>
                  <input value={apiUrl} onChange={(e) => setApiUrl(e.target.value)} placeholder="https://api-hashcredit...." />
                </label>
                <label>
                  <div className="label">API 토큰 (X-API-Key)</div>
                  <input value={apiToken} onChange={(e) => setApiToken(e.target.value)} placeholder="(demo token)" type="password" />
                </label>
              </div>
              <div className="form">
                <label>
                  <div className="label">txid</div>
                  <input value={apiTxid} onChange={(e) => setApiTxid(e.target.value.trim())} placeholder="예: e4c6..." />
                </label>
                <label>
                  <div className="label">vout</div>
                  <input value={apiVout} onChange={(e) => setApiVout(e.target.value)} placeholder="0" />
                </label>
                <label>
                  <div className="label">checkpoint_height</div>
                  <input
                    value={apiProofCheckpointHeight}
                    onChange={(e) => setApiProofCheckpointHeight(e.target.value)}
                    placeholder="예: 4842333"
                  />
                </label>
                <label>
                  <div className="label">target_height</div>
                  <input value={apiTargetHeight} onChange={(e) => setApiTargetHeight(e.target.value)} placeholder="예: 4842343" />
                </label>
                <div className="actions">
                  <button className="btn secondary" onClick={() => void apiBuildProof()} disabled={apiBusy}>
                    proof 생성(API) → proofHex 채우기
                  </button>
                  <button className="btn secondary" onClick={() => void apiSubmitProof()} disabled={apiBusy}>
                    proof 제출(API)
                  </button>
                  <button className="btn" onClick={() => void apiBuildAndSubmit()} disabled={apiBusy}>
                    원클릭(생성+제출)
                  </button>
                </div>
              </div>
              <div className="kv">
                <div className="row">
                  <div className="k">API 결과</div>
                  <div className="v mono pre">{apiLog || '—'}</div>
                </div>
              </div>
            </section>

            <section className="card full">
              <h2>submitPayout (지갑)</h2>
              <div className="hint">API에서 proof를 만들었으면 위 버튼이 `proofHex`를 자동으로 채웁니다.</div>
              <textarea value={proofHex} onChange={(e) => setProofHex(e.target.value.trim())} placeholder="0x..." rows={6} />
              <div className="actions">
                <button className="btn" onClick={() => void submitProof()} disabled={!walletAccount}>
                  submitPayout
                </button>
              </div>
            </section>
          </>
        ) : null}

        {tab === 'admin' ? (
          <>
            <section className="card">
              <h2>관리자(Manager, 지갑)</h2>
              <div className="hint">owner만 성공합니다. 실패 시 revert 이유를 Tx 상태에서 확인하세요.</div>
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
                  <input value={adminBtcKeyHash} onChange={(e) => setAdminBtcKeyHash(e.target.value)} placeholder="0x..." />
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
                  <input value={adminNewVerifier} onChange={(e) => setAdminNewVerifier(e.target.value)} placeholder="0x..." />
                </label>
                <div className="actions">
                  <button className="btn secondary" onClick={() => void setVerifier()} disabled={!walletAccount}>
                    setVerifier
                  </button>
                </div>
              </div>
            </section>

            <section className="card">
              <h2>관리자(SPV Verifier, 지갑)</h2>
              <div className="hint">`setBorrowerPubkeyHash`는 SPV 경로에서 필수입니다.</div>
              <div className="form">
                <label>
                  <div className="label">borrower</div>
                  <input value={spvBorrower} onChange={(e) => setSpvBorrower(e.target.value)} placeholder="0x..." />
                </label>
                <label>
                  <div className="label">pubkeyHash (bytes20)</div>
                  <input value={spvPubkeyHash} onChange={(e) => setSpvPubkeyHash(e.target.value)} placeholder="0x + 40 hex" />
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
          </>
        ) : null}

        {tab === 'config' ? (
          <section className="card full">
            <h2>설정</h2>
            <div className="form">
              <label>
                <div className="label">RPC URL (조회용)</div>
                <input value={rpcUrl} onChange={(e) => setRpcUrl(e.target.value)} placeholder="https://..." />
              </label>
              <label>
                <div className="label">체인 ID</div>
                <input
                  value={String(chainId)}
                  onChange={(e) => setChainId(Number(e.target.value))}
                  placeholder="102031"
                  inputMode="numeric"
                />
              </label>
              <label>
                <div className="label">HashCreditManager</div>
                <input value={managerAddress} onChange={(e) => setManagerAddress(e.target.value)} placeholder="0x..." />
              </label>
              <label>
                <div className="label">BtcSpvVerifier</div>
                <input value={spvVerifierAddress} onChange={(e) => setSpvVerifierAddress(e.target.value)} placeholder="0x..." />
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
            <div className="hint">`apps/web/.env.example`를 복사해서 `apps/web/.env`를 만들면 기본값을 쉽게 넣을 수 있어요.</div>
          </section>
        ) : null}

        <section className="card full">
          <h2>Tx 상태</h2>
          {txState.status === 'idle' ? (
            <div className="hint">아직 전송한 트랜잭션이 없습니다.</div>
          ) : txState.status === 'signing' ? (
            <div className="pill">서명 중: {txState.label}</div>
          ) : txState.status === 'pending' ? (
            <div className="pill warn">
              대기 중: {txState.label} <span className="mono">{txState.hash}</span>
            </div>
          ) : txState.status === 'confirmed' ? (
            <div className="pill ok">
              확정됨: {txState.label} <span className="mono">{txState.hash}</span>
            </div>
          ) : (
            <div className="pill err">
              오류: {txState.label} — {txState.message}
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
