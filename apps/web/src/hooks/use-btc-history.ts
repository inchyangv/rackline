import { useCallback, useEffect } from 'react'
import { getErrorMessage } from '@/lib/ethereum'
import { useDemoStore } from '@/stores/demo-store'
import { useApiClient } from './use-api-client'
import type { BtcAddressHistoryItem } from '@/types'

const BTC_HISTORY_REFRESH_INTERVAL_MS = 30_000

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

export function useBtcHistory() {
  const { apiRequest } = useApiClient()
  const btcHistoryMiningOnly = useDemoStore((s) => s.btcHistoryMiningOnly)
  const btcHistoryAutoRefreshEnabled = useDemoStore((s) => s.btcHistoryAutoRefreshEnabled)
  const borrowerBtcMap = useDemoStore((s) => s.borrowerBtcMap)
  const setBtcChainHistoryByAddress = useDemoStore((s) => s.setBtcChainHistoryByAddress)
  const setBtcChainHistoryLoading = useDemoStore((s) => s.setBtcChainHistoryLoading)
  const setBtcChainHistoryError = useDemoStore((s) => s.setBtcChainHistoryError)
  const btcChainHistoryByAddress = useDemoStore((s) => s.btcChainHistoryByAddress)
  const btcChainHistoryLoading = useDemoStore((s) => s.btcChainHistoryLoading)
  const btcChainHistoryError = useDemoStore((s) => s.btcChainHistoryError)

  const fetchBtcAddressHistory = useCallback(
    async (address: string, limit = 12, miningOnly: boolean = btcHistoryMiningOnly): Promise<void> => {
      const key = address.trim().toLowerCase()
      if (!key) return
      setBtcChainHistoryLoading({ ...useDemoStore.getState().btcChainHistoryLoading, [key]: true })
      setBtcChainHistoryError({ ...useDemoStore.getState().btcChainHistoryError, [key]: '' })
      try {
        const q = new URLSearchParams({ address: address.trim(), limit: String(limit) })
        if (miningOnly) q.set('mining_only', 'true')
        const result = await apiRequest(`/btc/address-history?${q.toString()}`, { method: 'GET' })
        if (!(typeof result === 'object' && result !== null)) {
          throw new Error('Unexpected API response')
        }
        if ((result as Record<string, unknown>).success !== true) {
          throw new Error(
            typeof (result as Record<string, unknown>).error === 'string'
              ? ((result as Record<string, unknown>).error as string)
              : 'Failed to fetch history',
          )
        }
        const itemsRaw: unknown[] = Array.isArray((result as Record<string, unknown>).items)
          ? ((result as Record<string, unknown>).items as unknown[])
          : []
        const items: BtcAddressHistoryItem[] = itemsRaw
          .filter(
            (x: unknown): x is Record<string, unknown> & { txid: string } =>
              isRecord(x) && typeof x.txid === 'string',
          )
          .map((x) => ({
            txid: String(x.txid),
            confirmed: Boolean(x.confirmed),
            block_time: typeof x.block_time === 'number' ? x.block_time : null,
            block_height: typeof x.block_height === 'number' ? x.block_height : null,
            confirmations: typeof x.confirmations === 'number' ? x.confirmations : null,
            sent_sats: typeof x.sent_sats === 'number' ? x.sent_sats : 0,
            received_sats: typeof x.received_sats === 'number' ? x.received_sats : 0,
            net_sats: typeof x.net_sats === 'number' ? x.net_sats : 0,
            direction: typeof x.direction === 'string' ? x.direction : 'self',
            has_coinbase_input: Boolean(x.has_coinbase_input),
            is_mining_reward: Boolean(x.is_mining_reward),
          }))

        const prev = useDemoStore.getState().btcChainHistoryByAddress
        setBtcChainHistoryByAddress({
          ...prev,
          [key]: {
            fetchedAt: Date.now(),
            address:
              typeof (result as Record<string, unknown>).address === 'string'
                ? ((result as Record<string, unknown>).address as string)
                : address.trim(),
            miningOnly,
            balanceChainSats:
              typeof (result as Record<string, unknown>).balance_chain_sats === 'number'
                ? ((result as Record<string, unknown>).balance_chain_sats as number)
                : null,
            balanceMempoolDeltaSats:
              typeof (result as Record<string, unknown>).balance_mempool_delta_sats === 'number'
                ? ((result as Record<string, unknown>).balance_mempool_delta_sats as number)
                : null,
            txCountChain:
              typeof (result as Record<string, unknown>).tx_count_chain === 'number'
                ? ((result as Record<string, unknown>).tx_count_chain as number)
                : null,
            txCountMempool:
              typeof (result as Record<string, unknown>).tx_count_mempool === 'number'
                ? ((result as Record<string, unknown>).tx_count_mempool as number)
                : null,
            items,
          },
        })
      } catch (e) {
        const prev = useDemoStore.getState().btcChainHistoryError
        setBtcChainHistoryError({ ...prev, [key]: getErrorMessage(e) })
      } finally {
        const prev = useDemoStore.getState().btcChainHistoryLoading
        setBtcChainHistoryLoading({ ...prev, [key]: false })
      }
    },
    [apiRequest, btcHistoryMiningOnly, setBtcChainHistoryByAddress, setBtcChainHistoryLoading, setBtcChainHistoryError],
  )

  const refreshAllLinkedBtc = useCallback(async (): Promise<void> => {
    const linkedAddresses = Array.from(
      new Set(
        Object.values(borrowerBtcMap)
          .map((value) => value.trim())
          .filter((value) => value.length > 0),
      ),
    )
    if (linkedAddresses.length === 0) return
    const limit = btcHistoryMiningOnly ? 50 : 12
    await Promise.all(
      linkedAddresses.map(async (address) => fetchBtcAddressHistory(address, limit, btcHistoryMiningOnly)),
    )
  }, [borrowerBtcMap, btcHistoryMiningOnly, fetchBtcAddressHistory])

  useEffect(() => {
    if (!btcHistoryAutoRefreshEnabled) return
    void refreshAllLinkedBtc()
    const timer = window.setInterval(() => {
      void refreshAllLinkedBtc()
    }, BTC_HISTORY_REFRESH_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [btcHistoryAutoRefreshEnabled, refreshAllLinkedBtc])

  return {
    fetchBtcAddressHistory,
    refreshAllLinkedBtc,
    btcChainHistoryByAddress,
    btcChainHistoryLoading,
    btcChainHistoryError,
  }
}
