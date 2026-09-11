import { create } from 'zustand'
import { env } from '@/lib/env'
import { getLocalStorageString, setLocalStorageString } from '@/lib/storage'

type ApiState = {
  apiUrl: string
  apiToken: string
  apiBusy: boolean
  apiLog: string
  apiDryRun: boolean
  apiCheckpointHeight: string
  apiTxid: string
  apiVout: string
  apiProofCheckpointHeight: string
  apiTargetHeight: string
  borrowerAddress: string
  adminBorrower: string
  adminBtcAddr: string
  adminBtcKeyHash: string
  adminNewVerifier: string
  spvBorrower: string
  spvPubkeyHash: string
  proofHex: string
  borrowAmount: string
  repayAmount: string
  approveAmount: string
  setApiUrl: (v: string) => void
  setApiToken: (v: string) => void
  setApiBusy: (v: boolean) => void
  setApiLog: (v: string) => void
  setApiDryRun: (v: boolean) => void
  setApiCheckpointHeight: (v: string) => void
  setApiTxid: (v: string) => void
  setApiVout: (v: string) => void
  setApiProofCheckpointHeight: (v: string) => void
  setApiTargetHeight: (v: string) => void
  setBorrowerAddress: (v: string) => void
  setAdminBorrower: (v: string) => void
  setAdminBtcAddr: (v: string) => void
  setAdminBtcKeyHash: (v: string) => void
  setAdminNewVerifier: (v: string) => void
  setSpvBorrower: (v: string) => void
  setSpvPubkeyHash: (v: string) => void
  setProofHex: (v: string) => void
  setBorrowAmount: (v: string) => void
  setRepayAmount: (v: string) => void
  setApproveAmount: (v: string) => void
  applyAsBorrower: (address: string) => void
}

export const useApiStore = create<ApiState>((set) => ({
  apiUrl: getLocalStorageString('hashcredit_api_url', env.apiUrl),
  apiToken: getLocalStorageString('hashcredit_api_token', ''),
  apiBusy: false,
  apiLog: '',
  apiDryRun: false,
  apiCheckpointHeight: '',
  apiTxid: '',
  apiVout: '0',
  apiProofCheckpointHeight: '',
  apiTargetHeight: '',
  borrowerAddress: '',
  adminBorrower: '',
  adminBtcAddr: '',
  adminBtcKeyHash: '',
  adminNewVerifier: '',
  spvBorrower: '',
  spvPubkeyHash: '',
  proofHex: '0x',
  borrowAmount: '1000',
  repayAmount: '1000',
  approveAmount: '1000',
  setApiUrl: (v) => {
    setLocalStorageString('hashcredit_api_url', v)
    set({ apiUrl: v })
  },
  setApiToken: (v) => {
    setLocalStorageString('hashcredit_api_token', v)
    set({ apiToken: v })
  },
  setApiBusy: (v) => set({ apiBusy: v }),
  setApiLog: (v) => set({ apiLog: v }),
  setApiDryRun: (v) => set({ apiDryRun: v }),
  setApiCheckpointHeight: (v) => set({ apiCheckpointHeight: v }),
  setApiTxid: (v) => set({ apiTxid: v }),
  setApiVout: (v) => set({ apiVout: v }),
  setApiProofCheckpointHeight: (v) => set({ apiProofCheckpointHeight: v }),
  setApiTargetHeight: (v) => set({ apiTargetHeight: v }),
  setBorrowerAddress: (v) => set({ borrowerAddress: v }),
  setAdminBorrower: (v) => set({ adminBorrower: v }),
  setAdminBtcAddr: (v) => set({ adminBtcAddr: v }),
  setAdminBtcKeyHash: (v) => set({ adminBtcKeyHash: v }),
  setAdminNewVerifier: (v) => set({ adminNewVerifier: v }),
  setSpvBorrower: (v) => set({ spvBorrower: v }),
  setSpvPubkeyHash: (v) => set({ spvPubkeyHash: v }),
  setProofHex: (v) => set({ proofHex: v }),
  setBorrowAmount: (v) => set({ borrowAmount: v }),
  setRepayAmount: (v) => set({ repayAmount: v }),
  setApproveAmount: (v) => set({ approveAmount: v }),
  applyAsBorrower: (address) =>
    set({
      borrowerAddress: address,
      adminBorrower: address,
      spvBorrower: address,
    }),
}))
