import { useCallback } from 'react'
import { env } from '@/lib/env'
import { normalizeBaseUrl } from '@/lib/explorer'

export function useApiClient() {
  const apiRequest = useCallback(
    async (path: string, init?: RequestInit): Promise<unknown> => {
      const base = normalizeBaseUrl(env.apiUrl)
      if (!base) throw new Error('API URL is empty. Set VITE_API_URL in .env')

      const headers = new Headers(init?.headers)
      if (!headers.has('content-type')) headers.set('content-type', 'application/json')

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
    [],
  )

  return { apiRequest }
}
