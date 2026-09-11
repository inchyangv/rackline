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