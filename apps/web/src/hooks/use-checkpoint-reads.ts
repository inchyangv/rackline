import { useEffect, useState } from 'react'
import { useCheckpointRead } from './use-contracts'

export function useCheckpointReads() {
  const checkpointRead = useCheckpointRead()
  const [latestCheckpointHeight, setLatestCheckpointHeight] = useState<number | null>(null)
  const [latestCheckpoint, setLatestCheckpoint] = useState<Record<string, unknown> | null>(null)

  useEffect(() => {
    let cancelled = false
    async function run(): Promise<void> {
      if (!checkpointRead) {
        setLatestCheckpointHeight(null)
        setLatestCheckpoint(null)
        return
      }
      try {
        const height = await checkpointRead.latestCheckpointHeight()
        if (cancelled) return
        setLatestCheckpointHeight(Number(height))

        try {
          const cp = await checkpointRead.latestCheckpoint()
          if (cancelled) return
          setLatestCheckpoint(cp as Record<string, unknown>)
        } catch {
          if (cancelled) return
          setLatestCheckpoint(null)
        }
      } catch {
        if (cancelled) return
        setLatestCheckpointHeight(null)
        setLatestCheckpoint(null)
      }
    }
    void run()
    return () => { cancelled = true }
  }, [checkpointRead])

  return { latestCheckpointHeight, latestCheckpoint }
}
