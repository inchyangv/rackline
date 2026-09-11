import { useCallback } from 'react'
import { normalizeBaseUrl } from '@/lib/explorer'
import { getErrorMessage } from '@/lib/ethereum'
import { useApiStore } from '@/stores/api-store'

export function useApiClient() {
  const apiUrl = useApiStore((s) => s.apiUrl)
  const apiToken = useApiStore((s) => s.apiToken)
  const setApiBusy = useApiStore((s) => s.setApiBusy)
  const setApiLog = useApiStore((s) => s.setApiLog)

  const apiRequest = useCallback(
    async (path: string, init?: RequestInit): Promise<unknown> => {
      const base = normalizeBaseUrl(apiUrl)
      if (!base) throw new Error('API URL is empty. (VITE_API_URL or input value)')

      const headers = new Headers(init?.headers)
      if (!headers.has('content-type')) headers.set('content-type', 'application/json')
      if (apiToken) headers.set('X-API-Key', apiToken)

      const res = await fetch(`${base}${path}`, { ...init, headers })
      const text = await res.text()
      let json: unknown = null
      try {
        json = text ? JSON.parse(text) : null
      } catch {
        json = { raw: text }
      }
      if (!res.ok) {
        const msg =
          typeof json === 'object' && json !== null && 'detail' in json
            ? String((json as Record<string, unknown>).detail)
            : text
        throw new Error(`API ${res.status}: ${msg}`)
      }
      return json
    },
    [apiUrl, apiToken],
  )

  const apiRun = useCallback(
    async (label: string, fn: () => Promise<unknown>): Promise<void> => {
      setApiBusy(true)
      setApiLog('')
      try {
        const result = await fn()
        setApiLog(`${label}\n${JSON.stringify(result, null, 2)}`)
      } catch (e) {
        setApiLog(`${label}\nERROR: ${getErrorMessage(e)}`)
      } finally {
        setApiBusy(false)
      }
    },
    [setApiBusy, setApiLog],
  )

  return { apiRequest, apiRun }
}
