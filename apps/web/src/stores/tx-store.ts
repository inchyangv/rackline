import { BrowserProvider, Contract, ethers } from 'ethers'
import type { ContractTransactionResponse, InterfaceAbi } from 'ethers'
import { getEthereum, getErrorMessage, ensureWalletChain } from '@/lib/ethereum'
import { useWalletStore } from './wallet-store'
import { useConfigStore } from './config-store'

export async function sendContractTx(
  label: string,
  address: string,
  abi: InterfaceAbi,
  action: (contract: Contract) => Promise<ContractTransactionResponse>,
): Promise<void> {
  const { setTxState } = useWalletStore.getState()
  const { chainId, rpcUrl } = useConfigStore.getState()

  if (!ethers.isAddress(address)) {
    setTxState({ status: 'error', label, message: 'Invalid contract address.' })
    return
  }

  setTxState({ status: 'signing', label })
  try {
    const ok = await ensureWalletChain(chainId, rpcUrl)
    if (!ok) throw new Error(`Failed to switch network. (chainId=${chainId})`)

    const ethereum = getEthereum()
    if (!ethereum) throw new Error('Browser wallet not found.')

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
