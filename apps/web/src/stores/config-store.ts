import { create } from 'zustand'
import { env } from '@/lib/env'

type ConfigState = {
  rpcUrl: string
  chainId: number
  managerAddress: string
  spvVerifierAddress: string
  vaultAddress: string
  stablecoinAddress: string
}

export const useConfigStore = create<ConfigState>(() => ({
  rpcUrl: env.rpcUrl,
  chainId: env.chainId,
  managerAddress: env.hashCreditManager,
  spvVerifierAddress: env.btcSpvVerifier,
  vaultAddress: env.vaultAddress,
  stablecoinAddress: env.stablecoinAddress,
}))
