import { create } from 'zustand'

type ApiState = {
  apiBusy: boolean
  apiLog: string
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
  claimBtcAddress: string
  claimToken: string
  claimMessage: string
  claimBtcSignature: string
  claimLog: string
  claimBusy: boolean
  borrowAmount: string
  repayAmount: string
  approveAmount: string
  setApiBusy: (v: boolean) => void
  setApiLog: (v: string) => void
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
  setClaimBtcAddress: (v: string) => void
  setClaimToken: (v: string) => void
  setClaimMessage: (v: string) => void
  setClaimBtcSignature: (v: string) => void
  setClaimLog: (v: string) => void
  setClaimBusy: (v: boolean) => void
  setBorrowAmount: (v: string) => void
  setRepayAmount: (v: string) => void
  setApproveAmount: (v: string) => void
}

export const useApiStore = create<ApiState>((set) => ({
  apiBusy: false,
  apiLog: '',
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
  claimBtcAddress: '',
  claimToken: '',
  claimMessage: '',
  claimBtcSignature: '',
  claimLog: '',
  claimBusy: false,
  borrowAmount: '1000',
  repayAmount: '1000',
  approveAmount: '1000',
  setApiBusy: (v) => set({ apiBusy: v }),
  setApiLog: (v) => set({ apiLog: v }),
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
  setClaimBtcAddress: (v) => set({ claimBtcAddress: v }),
  setClaimToken: (v) => set({ claimToken: v }),
  setClaimMessage: (v) => set({ claimMessage: v }),
  setClaimBtcSignature: (v) => set({ claimBtcSignature: v }),
  setClaimLog: (v) => set({ claimLog: v }),
  setClaimBusy: (v) => set({ claimBusy: v }),
  setBorrowAmount: (v) => set({ borrowAmount: v }),
  setRepayAmount: (v) => set({ repayAmount: v }),
  setApproveAmount: (v) => set({ approveAmount: v }),
}))
