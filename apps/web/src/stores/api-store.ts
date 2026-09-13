import { create } from 'zustand'

type ApiState = {
  borrowerAddress: string
  /** True while the viewed address should track the connected wallet. */
  following: boolean
  claimBtcAddress: string
  claimBtcSignature: string
  /** Set the viewed borrower address and whether it follows the wallet. */
  setViewed: (address: string, following: boolean) => void
  setClaimBtcAddress: (v: string) => void
  setClaimBtcSignature: (v: string) => void
}

export const useApiStore = create<ApiState>((set) => ({
  borrowerAddress: '',
  following: true,
  claimBtcAddress: '',
  claimBtcSignature: '',
  setViewed: (address, following) => set({ borrowerAddress: address, following }),
  setClaimBtcAddress: (v) => set({ claimBtcAddress: v }),
  setClaimBtcSignature: (v) => set({ claimBtcSignature: v }),
}))
