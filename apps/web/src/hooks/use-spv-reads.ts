import { useEffect, useState } from 'react'
import { ethers } from 'ethers'
import { useSpvVerifierRead } from './use-contracts'

export function useSpvReads(spvBorrower: string) {
  const spvVerifierRead = useSpvVerifierRead()
  const [spvOwner, setSpvOwner] = useState('')
  const [spvCheckpointManagerOnchain, setSpvCheckpointManagerOnchain] = useState('')
  const [spvBorrowerOnchainPubkeyHash, setSpvBorrowerOnchainPubkeyHash] = useState('')

  useEffect(() => {
    let cancelled = false
    async function run(): Promise<void> {
      if (!spvVerifierRead) {
        setSpvOwner('')
        setSpvCheckpointManagerOnchain('')
        return
      }
      try {
        const [owner, cpManager] = await Promise.all([
          spvVerifierRead.owner(),
          spvVerifierRead.checkpointManager(),
        ])
        if (cancelled) return
        setSpvOwner(String(owner))
        setSpvCheckpointManagerOnchain(String(cpManager))
      } catch {
        if (cancelled) return
        setSpvOwner('')
        setSpvCheckpointManagerOnchain('')
      }
    }
    void run()
    return () => { cancelled = true }
  }, [spvVerifierRead])

  useEffect(() => {
    let cancelled = false
    async function run(): Promise<void> {
      if (!spvVerifierRead || !ethers.isAddress(spvBorrower)) {
        setSpvBorrowerOnchainPubkeyHash('')
        return
      }
      try {
        const h = await spvVerifierRead.getBorrowerPubkeyHash(spvBorrower)
        if (cancelled) return
        setSpvBorrowerOnchainPubkeyHash(String(h))
      } catch {
        if (cancelled) return
        setSpvBorrowerOnchainPubkeyHash('')
      }
    }
    void run()
    return () => { cancelled = true }
  }, [spvVerifierRead, spvBorrower])

  return { spvOwner, spvCheckpointManagerOnchain, spvBorrowerOnchainPubkeyHash }
}
