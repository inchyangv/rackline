import { useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useWalletStore } from '@/stores/wallet-store'
import { TxLink } from './explorer-link'

const AUTO_CLEAR_MS = 8000

/** Hairline strip under the top bar. Present only while a transaction matters. */
export function TxStrip() {
  const txState = useWalletStore((s) => s.txState)
  const setTxState = useWalletStore((s) => s.setTxState)
  const status = txState.status
  const idle = status === 'idle'

  useEffect(() => {
    if (status !== 'confirmed') return
    const timer = window.setTimeout(() => setTxState({ status: 'idle' }), AUTO_CLEAR_MS)
    return () => window.clearTimeout(timer)
  }, [status, setTxState])

  const full =
    txState.status === 'idle'
      ? ''
      : txState.status === 'error'
        ? `${txState.label} failed: ${txState.message}`
        : txState.status === 'signing'
          ? `Signing ${txState.label}…`
          : txState.status === 'pending'
            ? `Pending ${txState.label}`
            : `${txState.label} confirmed`

  // The live region is mounted at all times and only its contents are gated:
  // a region created in the same commit as its text is not announced. With no
  // border, padding or height class the wrapper collapses to zero height.
  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(!idle && 'flex h-7 items-center gap-2 border-b border-rule px-6 text-xs')}
    >
      {txState.status === 'idle' ? null : (
        <>
          {txState.status === 'error' ? (
            <span aria-hidden="true" className="num shrink-0 leading-none text-err">
              ×
            </span>
          ) : (
            <span
              aria-hidden="true"
              className={cn(
                'size-2 shrink-0 rounded-full',
                txState.status === 'confirmed' ? 'bg-ok' : 'bg-signal animate-pulse',
              )}
            />
          )}

          <span
            title={full}
            className={cn(
              'min-w-0 truncate',
              txState.status === 'error' ? 'text-err' : 'text-bone-2',
            )}
          >
            {full}
          </span>

          {txState.status === 'pending' || txState.status === 'confirmed' ? (
            <>
              <span aria-hidden="true" className="shrink-0 text-bone-3">
                ·
              </span>
              <TxLink hash={txState.hash} className="shrink-0" />
            </>
          ) : null}

          {txState.status === 'error' ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="ml-auto h-6 shrink-0 px-2 text-xs"
              onClick={() => setTxState({ status: 'idle' })}
            >
              Dismiss
            </Button>
          ) : null}
        </>
      )}
    </div>
  )
}
