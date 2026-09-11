export type TxState =
  | { status: 'idle' }
  | { status: 'signing'; label: string }
  | { status: 'pending'; label: string; hash: string }
  | { status: 'confirmed'; label: string; hash: string }
  | { status: 'error'; label: string; message: string }

export type TabId = 'dashboard' | 'ops' | 'proof' | 'admin' | 'config'

export type DemoWallet = {
  name: string
  address: string
  privateKey: string
  createdAt: number
}

export type BorrowerBtcMap = Record<string, string>

export type DemoBtcPayoutRecord = {
  id: string
  createdAt: number
  borrower: string
  btcAddress: string
  txid: string
  vout: number
  amountSats: number | null
  checkpointHeight: number
  targetHeight: number
  source: 'build' | 'build+submit'
  submitTxHash: string | null
}

export type BtcAddressHistoryItem = {
  txid: string
  confirmed: boolean
  block_time: number | null
  block_height: number | null
  confirmations: number | null
  sent_sats: number
  received_sats: number
  net_sats: number
  direction: 'in' | 'out' | 'self' | 'mining' | string
  has_coinbase_input: boolean
  is_mining_reward: boolean
}

export type BtcAddressHistorySnapshot = {
  fetchedAt: number
  address: string
  miningOnly: boolean
  balanceChainSats: number | null
  balanceMempoolDeltaSats: number | null
  txCountChain: number | null
  txCountMempool: number | null
  items: BtcAddressHistoryItem[]
}

export type Eip1193Provider = {
  request: (args: { method: string; params?: unknown[] | Record<string, unknown> }) => Promise<unknown>
}
