import { useEffect, useState } from 'react'
import { useManagerRead } from './use-contracts'
import { useWalletStore } from '@/stores/wallet-store'

/**
 * Static-ish manager reads (addresses) plus the pause flag.
 * `paused` is `null` while unknown or when the read fails — never assume false.
 */
export function useManagerReads() {
  const managerRead = useManagerRead()
  const refreshKey = useWalletStore((s) => s.refreshKey)
  const [owner, setOwner] = useState('')
  const [verifier, setVerifier] = useState('')
  const [stablecoin, setStablecoin] = useState('')
  const [vault, setVault] = useState('')
  const [paused, setPaused] = useState<boolean | null>(null)

  useEffect(() => {
    let cancelled = false
    async function run(): Promise<void> {
      if (!managerRead) return
      try {
        const [o, v, s, vl] = await Promise.all([
          managerRead.owner(),
          managerRead.verifier(),
          managerRead.stablecoin(),
          managerRead.vault(),
        ])
        if (cancelled) return
        setOwner(String(o))
        setVerifier(String(v))
        setStablecoin(String(s))
        setVault(String(vl))
      } catch {
        if (cancelled) return
        setOwner('')
        setVerifier('')
        setStablecoin('')
        setVault('')
      }
    }
    void run()
    return () => { cancelled = true }
  }, [managerRead])

  useEffect(() => {
    let cancelled = false
    async function run(): Promise<void> {
      if (!managerRead) {
        setPaused(null)
        return
      }
      try {
        const p = (await managerRead.paused()) as boolean
        if (!cancelled) setPaused(Boolean(p))
      } catch {
        if (!cancelled) setPaused(null)
      }
    }
    void run()
    return () => { cancelled = true }
  }, [managerRead, refreshKey])

  return { owner, verifier, stablecoin, vault, paused }
}
