import { useMemo } from 'react'
import { Contract, ethers, JsonRpcProvider } from 'ethers'
import { HashCreditManagerAbi, BtcSpvVerifierAbi, CheckpointManagerAbi, Erc20Abi } from '@/lib/abis'
import { useConfigStore } from '@/stores/config-store'

export function useReadonlyProvider(): JsonRpcProvider | null {
  const rpcUrl = useConfigStore((s) => s.rpcUrl)
  return useMemo(() => {
    if (!rpcUrl) return null
    try {
      return new JsonRpcProvider(rpcUrl)
    } catch {
      return null
    }
  }, [rpcUrl])
}

export function useManagerRead(): Contract | null {
  const provider = useReadonlyProvider()
  const managerAddress = useConfigStore((s) => s.managerAddress)
  return useMemo(() => {
    if (!provider || !ethers.isAddress(managerAddress)) return null
    return new Contract(managerAddress, HashCreditManagerAbi, provider)
  }, [provider, managerAddress])
}

export function useSpvVerifierRead(): Contract | null {
  const provider = useReadonlyProvider()
  const spvVerifierAddress = useConfigStore((s) => s.spvVerifierAddress)
  return useMemo(() => {
    if (!provider || !ethers.isAddress(spvVerifierAddress)) return null
    return new Contract(spvVerifierAddress, BtcSpvVerifierAbi, provider)
  }, [provider, spvVerifierAddress])
}

export function useCheckpointRead(): Contract | null {
  const provider = useReadonlyProvider()
  const checkpointManagerAddress = useConfigStore((s) => s.checkpointManagerAddress)
  return useMemo(() => {
    if (!provider || !ethers.isAddress(checkpointManagerAddress)) return null
    return new Contract(checkpointManagerAddress, CheckpointManagerAbi, provider)
  }, [provider, checkpointManagerAddress])
}

export function useStablecoinRead(stablecoinAddress: string): Contract | null {
  const provider = useReadonlyProvider()
  return useMemo(() => {
    if (!provider || !ethers.isAddress(stablecoinAddress)) return null
    return new Contract(stablecoinAddress, Erc20Abi, provider)
  }, [provider, stablecoinAddress])
}
