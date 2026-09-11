import { create } from 'zustand'
import { env } from '@/lib/env'

type ConfigState = {
  rpcUrl: string
  chainId: number
  managerAddress: string
  spvVerifierAddress: string
  checkpointManagerAddress: string
  setRpcUrl: (v: string) => void
  setChainId: (v: number) => void
  setManagerAddress: (v: string) => void
  setSpvVerifierAddress: (v: string) => void
  setCheckpointManagerAddress: (v: string) => void
}

export const useConfigStore = create<ConfigState>((set) => ({
  rpcUrl: env.rpcUrl,
  chainId: env.chainId,
  managerAddress: env.hashCreditManager,
  spvVerifierAddress: env.btcSpvVerifier,
  checkpointManagerAddress: env.checkpointManager,
  setRpcUrl: (v) => set({ rpcUrl: v }),
  setChainId: (v) => set({ chainId: v }),
  setManagerAddress: (v) => set({ managerAddress: v }),
  setSpvVerifierAddress: (v) => set({ spvVerifierAddress: v }),
  setCheckpointManagerAddress: (v) => set({ checkpointManagerAddress: v }),
}))
