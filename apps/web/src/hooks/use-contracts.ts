import { useMemo } from 'react'
import { Contract, ethers, JsonRpcProvider, Network } from 'ethers'
import { HashCreditManagerAbi, Erc20Abi, LendingVaultAbi } from '@/lib/abis'
import { useConfigStore } from '@/stores/config-store'

export function useReadonlyProvider(): JsonRpcProvider | null {
  const rpcUrl = useConfigStore((s) => s.rpcUrl)
  const chainId = useConfigStore((s) => s.chainId)
  return useMemo(() => {
    if (!rpcUrl) return null
    try {
      const network = Network.from(chainId)
      return new JsonRpcProvider(rpcUrl, network, { staticNetwork: true })
    } catch {
      return null
    }
  }, [rpcUrl, chainId])
}

export function useManagerRead(): Contract | null {
  const provider = useReadonlyProvider()
  const managerAddress = useConfigStore((s) => s.managerAddress)
  return useMemo(() => {
    if (!provider || !ethers.isAddress(managerAddress)) return null
    return new Contract(managerAddress, HashCreditManagerAbi, provider)
  }, [provider, managerAddress])
}

export function useVaultRead(): Contract | null {
  const provider = useReadonlyProvider()
  const vaultAddress = useConfigStore((s) => s.vaultAddress)
  return useMemo(() => {
    if (!provider || !ethers.isAddress(vaultAddress)) return null
    return new Contract(vaultAddress, LendingVaultAbi, provider)
  }, [provider, vaultAddress])
}

export function useStablecoinRead(stablecoinAddress: string): Contract | null {
  const provider = useReadonlyProvider()
  return useMemo(() => {
    if (!provider || !ethers.isAddress(stablecoinAddress)) return null
    return new Contract(stablecoinAddress, Erc20Abi, provider)
  }, [provider, stablecoinAddress])
}
