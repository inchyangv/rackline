import { BrowserProvider, Contract, ethers } from 'ethers'
import type { ContractTransactionResponse, InterfaceAbi } from 'ethers'
import { toast } from 'sonner'
import { BRAND } from '@/lib/brand'
import { describeTxError, ensureWalletChain, getEthereum } from '@/lib/ethereum'
import { useWalletStore } from './wallet-store'
import { useConfigStore } from './config-store'

/** Read nodes lag the node that mined the transaction; re-read once more. */
const LAG_REFRESH_MS = 2500

/**
 * Send a contract transaction from the connected wallet and track it in the
 * wallet store. Resolves once mined; rejects on any failure. Failures are
 * surfaced centrally: one error toast plus `txState.error`. No success toast.
 * Bumps `refreshKey` after confirmation (and again once the read node catches
 * up) so reads refetch.
 *
 * `label` is the display verb shown to the user ('Draw', 'Repay',
 * 'Approve mUSDT', 'Deposit', 'Withdraw', 'Verify payout address').
 */
export async function sendContractTx(
  label: string,
  address: string,
  abi: InterfaceAbi,
  action: (contract: Contract) => Promise<ContractTransactionResponse>,
): Promise<void> {
  const { setTxState, bumpRefresh } = useWalletStore.getState()
  const { chainId, rpcUrl } = useConfigStore.getState()

  if (!ethers.isAddress(address)) {
    const message = 'Invalid contract address.'
    setTxState({ status: 'error', label, message })
    toast.error(`${label} failed: ${message}`)
    throw new Error(message)
  }

  setTxState({ status: 'signing', label })
  try {
    const ok = await ensureWalletChain(chainId, rpcUrl)
    if (!ok) throw new Error(`Wallet is not on ${BRAND.network} (${chainId}).`)

    const ethereum = getEthereum()
    if (!ethereum) throw new Error('No browser wallet found.')

    const provider = new BrowserProvider(ethereum)
    const signer = await provider.getSigner()
    const contract = new Contract(address, abi, signer)

    const tx = await action(contract)
    setTxState({ status: 'pending', label, hash: tx.hash })
    await tx.wait()
    setTxState({ status: 'confirmed', label, hash: tx.hash })
    bumpRefresh()
    setTimeout(bumpRefresh, LAG_REFRESH_MS)
  } catch (err: unknown) {
    const message = describeTxError(err)
    setTxState({ status: 'error', label, message })
    toast.error(`${label} failed: ${message}`)
    throw err
  }
}
