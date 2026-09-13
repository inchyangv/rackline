import { Interface } from 'ethers'
import { BtcSpvVerifierAbi, HashCreditManagerAbi, LendingVaultAbi } from '@/lib/abis'
import type { Eip1193Provider } from '@/types'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

export function isEip1193Provider(value: unknown): value is Eip1193Provider {
  if (typeof value !== 'object' || value === null) return false
  if (!('request' in value)) return false
  const request = (value as { request?: unknown }).request
  return typeof request === 'function'
}

export function getEthereum(): Eip1193Provider | null {
  if (typeof window === 'undefined') return null
  const w = window as unknown as { ethereum?: unknown }
  return isEip1193Provider(w.ethereum) ? w.ethereum : null
}

export async function ensureWalletChain(
  expectedChainId: number,
  rpcUrl: string,
): Promise<boolean> {
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

export function getErrorCode(err: unknown): number | undefined {
  if (!isRecord(err)) return undefined
  const code = err.code
  if (typeof code === 'number') return code
  if (typeof code === 'string') {
    const parsed = Number(code)
    return Number.isFinite(parsed) ? parsed : undefined
  }
  return undefined
}

export function getErrorMessage(err: unknown): string {
  if (isRecord(err)) {
    const shortMessage = err.shortMessage
    if (typeof shortMessage === 'string') return shortMessage
    const message = err.message
    if (typeof message === 'string') return message
  }
  return String(err)
}

/* ------------------------------------------------------------------ */
/* Revert / rejection → one plain sentence                             */
/* ------------------------------------------------------------------ */

/** Custom error name → the sentence shown to the user. */
const REVERT_SENTENCES: Record<string, string> = {
  ExceedsCreditLimit: 'Amount exceeds credit limit.',
  BorrowerNotActive: 'Facility is frozen or closed.',
  BorrowerNotRegistered: 'No facility for this address.',
  BorrowerAlreadyRegistered: 'This address is already registered.',
  InsufficientLiquidity: 'Pool liquidity is insufficient.',
  InsufficientShares: 'Not enough shares.',
  EnforcedPause: 'Protocol is paused.',
  InvalidBtcSignature: 'Signature does not match the payout address.',
  PubkeyHashMismatch: 'Signature does not match the payout address.',
  ZeroAmount: 'Amount must be greater than zero.',
}

let revertInterfaces: Interface[] | null = null

function getRevertInterfaces(): Interface[] {
  if (!revertInterfaces) {
    revertInterfaces = [
      new Interface(HashCreditManagerAbi),
      new Interface(LendingVaultAbi),
      new Interface(BtcSpvVerifierAbi),
    ]
  }
  return revertInterfaces
}

const NESTED_KEYS = ['data', 'error', 'info', 'cause'] as const

function collectErrorCodes(err: unknown, depth = 0): (string | number)[] {
  if (depth > 4 || !isRecord(err)) return []
  const out: (string | number)[] = []
  const code = err.code
  if (typeof code === 'string' || typeof code === 'number') out.push(code)
  for (const key of NESTED_KEYS) {
    const nested = err[key]
    if (isRecord(nested)) out.push(...collectErrorCodes(nested, depth + 1))
  }
  return out
}

/** First revert payload found on the error (wallets nest it differently). */
function findRevertData(err: unknown, depth = 0): string | null {
  if (depth > 4 || !isRecord(err)) return null
  const data = err.data
  if (typeof data === 'string' && /^0x[0-9a-fA-F]*$/.test(data) && data.length >= 10) return data
  for (const key of NESTED_KEYS) {
    const nested = err[key]
    if (isRecord(nested)) {
      const found = findRevertData(nested, depth + 1)
      if (found) return found
    }
  }
  return null
}

function findRevertName(err: unknown): string | null {
  if (!isRecord(err)) return null
  const revert = err.revert
  if (isRecord(revert) && typeof revert.name === 'string' && revert.name) return revert.name
  const data = findRevertData(err)
  if (!data) return null
  for (const iface of getRevertInterfaces()) {
    try {
      const parsed = iface.parseError(data)
      if (parsed?.name) return parsed.name
    } catch {
      // try the next ABI
    }
  }
  return null
}

function rawErrorText(err: unknown): string {
  if (isRecord(err)) {
    const parts = [err.shortMessage, err.message, err.reason]
    for (const part of parts) if (typeof part === 'string' && part) return part
  }
  return typeof err === 'string' ? err : ''
}

/** Strip provider boilerplate, make one sentence, cap at 160 chars. */
function toSentence(raw: string): string {
  let text = raw.trim()
  const context = text.indexOf(' (action=')
  if (context > -1) text = text.slice(0, context)
  text = text.replace(/execution reverted:?/gi, '')
  text = text.replace(/\(?\s*unknown custom error\s*\)?/gi, '')
  text = text.replace(/^could not coalesce error.*/i, 'The wallet could not complete the transaction')
  text = text.replace(/["']/g, '').replace(/\s+/g, ' ').trim()
  text = text.replace(/^[-–—:,.]+/, '').trim()
  if (!text) return 'Transaction failed.'
  let sentence = text.charAt(0).toUpperCase() + text.slice(1)
  if (sentence.length > 160) sentence = `${sentence.slice(0, 159).trimEnd()}…`
  return /[.?…]$/.test(sentence) ? sentence : `${sentence}.`
}

/**
 * Map any wallet / RPC / revert failure to a single plain sentence that can be
 * shown to the user as-is. Never throws.
 */
export function describeTxError(err: unknown): string {
  const codes = collectErrorCodes(err)
  const text = rawErrorText(err)

  if (
    codes.includes(4001) ||
    codes.includes('4001') ||
    codes.includes('ACTION_REJECTED') ||
    /user rejected|user denied|rejected the request/i.test(text)
  ) {
    return 'Cancelled in wallet.'
  }

  if (codes.includes('INSUFFICIENT_FUNDS')) return 'Not enough CTC for gas.'

  // A named revert is the most specific thing we know; prefer it over any
  // message heuristic (a token revert can also mention "insufficient funds").
  const name = findRevertName(err)
  if (name) return REVERT_SENTENCES[name] ?? `Transaction reverted (${name}).`

  if (/insufficient funds for/i.test(text)) return 'Not enough CTC for gas.'

  return toSentence(text)
}

/* ------------------------------------------------------------------ */
/* Wallet events                                                       */
/* ------------------------------------------------------------------ */

type EventfulProvider = Eip1193Provider & {
  on?: (event: string, listener: (payload: unknown) => void) => void
  removeListener?: (event: string, listener: (payload: unknown) => void) => void
}

function toChainId(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  if (typeof value === 'bigint') return Number(value)
  if (typeof value === 'string') {
    const n = /^0x/i.test(value) ? Number.parseInt(value, 16) : Number(value)
    return Number.isFinite(n) ? n : null
  }
  return null
}

/**
 * Subscribe to `chainChanged` / `accountsChanged` on the injected wallet.
 * Returns an unsubscribe function; a no-op when no wallet is present.
 */
export function subscribeWalletEvents(h: {
  onChainChanged: (chainId: number) => void
  onAccountsChanged: (accounts: string[]) => void
}): () => void {
  const provider = getEthereum() as EventfulProvider | null
  if (!provider || typeof provider.on !== 'function') return () => {}

  const handleChainChanged = (payload: unknown): void => {
    const chainId = toChainId(payload)
    if (chainId !== null) h.onChainChanged(chainId)
  }
  const handleAccountsChanged = (payload: unknown): void => {
    const accounts = Array.isArray(payload)
      ? payload.filter((a): a is string => typeof a === 'string')
      : []
    h.onAccountsChanged(accounts)
  }

  provider.on('chainChanged', handleChainChanged)
  provider.on('accountsChanged', handleAccountsChanged)

  return () => {
    provider.removeListener?.('chainChanged', handleChainChanged)
    provider.removeListener?.('accountsChanged', handleAccountsChanged)
  }
}
