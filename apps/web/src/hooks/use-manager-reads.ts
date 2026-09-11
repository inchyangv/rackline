import { useEffect, useState } from 'react'
import { useManagerRead } from './use-contracts'

export function useManagerReads() {
  const managerRead = useManagerRead()
  const [owner, setOwner] = useState('')
  const [verifier, setVerifier] = useState('')
  const [stablecoin, setStablecoin] = useState('')
  const [vault, setVault] = useState('')

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

  return { owner, verifier, stablecoin, vault }
}
