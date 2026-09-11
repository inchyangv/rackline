import { create } from 'zustand'
import { env } from '@/lib/env'

type ConfigState = {
  rpcUrl: string
  chainId: number
  managerAddress: string
  spvVerifierAddress: string
  checkpointManagerAddress: string
  vaultAddress: string
  stablecoinAddress: string
}

export const useConfigStore = create<ConfigState>(() => ({
  rpcUrl: env.rpcUrl,
  chainId: env.chainId,
  managerAddress: env.hashCreditManager,
  spvVerifierAddress: env.btcSpvVerifier,
  checkpointManagerAddress: env.checkpointManager,
  vaultAddress: env.vaultAddress,
  stablecoinAddress: env.stablecoinAddress,
}))
