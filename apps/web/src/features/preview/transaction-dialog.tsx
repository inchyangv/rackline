import { useRef, useState } from 'react'
import { Dialog } from 'radix-ui'
import { ArrowDownLeft, ArrowUpRight, Check, ChevronLeft, ShieldCheck, X } from 'lucide-react'
import { getDemoQuote, useDemoStore } from './demo-store'
import type { DemoTransactionKind } from './demo-store'
import './transaction-dialog.css'

const labels = {
  supply: { title: 'Supply', action: 'supply', success: 'Supply complete', description: 'Put your demo USDC to work in the GPU receivables pool.' },
  withdraw: { title: 'Withdraw', action: 'withdrawal', success: 'Withdrawal complete', description: 'Return supplied demo USDC to your preview wallet.' },
  borrow: { title: 'Borrow', action: 'borrow', success: 'Borrow complete', description: 'Access working capital against your eligible demo receivables.' },
  repay: { title: 'Repay', action: 'repayment', success: 'Repayment complete', description: 'Reduce your demo balance. Accrued interest is paid first.' },
} as const
const format = (amount: number) => amount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

export function TransactionDialog({ kind, onClose }: { kind: DemoTransactionKind; onClose: () => void }) {
  return <TransactionContent key={kind} kind={kind} onClose={onClose} />
}

function TransactionContent({ kind, onClose }: { kind: DemoTransactionKind; onClose: () => void }) {
  const state = useDemoStore()
  const [input, setInput] = useState('')
  const [step, setStep] = useState<'amount' | 'review' | 'success'>('amount')
  const [error, setError] = useState('')
  const [successTitle, setSuccessTitle] = useState<string>(labels[kind].success)
  const [busy, setBusy] = useState(false)
  const [returnFocus] = useState(() => typeof document !== 'undefined' && document.activeElement instanceof HTMLElement ? document.activeElement : null)
  const submitted = useRef(false)
  const amount = input.trim() === '' ? 0 : Number(input)
  const quote = getDemoQuote(state, kind, amount)
  const label = labels[kind]
  const isInflow = kind === 'supply' || kind === 'repay'
  const Icon = isInflow ? ArrowDownLeft : ArrowUpRight
  const showError = error || (input !== '' && !quote.ok && state.connected ? quote.message : '')

  function confirm() {
    if (submitted.current) return
    submitted.current = true
    setBusy(true)
    const result = useDemoStore.getState().transact(kind, amount)
    if (!result.ok) {
      submitted.current = false
      setError(result.message)
      setBusy(false)
      return
    }
    setSuccessTitle(result.message)
    setStep('success')
    setBusy(false)
  }

  return (
    <Dialog.Root open onOpenChange={(open) => { if (!open) onClose() }}>
      <Dialog.Portal>
        <Dialog.Overlay className="rl-transaction-overlay" />
        <Dialog.Content className="rl-transaction" aria-describedby="rl-transaction-description" onCloseAutoFocus={(event) => { event.preventDefault(); returnFocus?.focus() }}>
          <Dialog.Close className="rl-icon-button rl-transaction-close" aria-label="Close transaction"><X size={19} /></Dialog.Close>
          <div className={`rl-transaction-symbol${step === 'success' ? ' rl-transaction-symbol-success' : ''}`}>{step === 'success' ? <Check size={25} /> : <Icon size={25} />}</div>
          <p className="rl-eyebrow rl-transaction-eyebrow">RACKLINE PREVIEW</p>
          <Dialog.Title className="rl-transaction-title">{step === 'success' ? successTitle : `${label.title} demo USDC`}</Dialog.Title>
          <Dialog.Description id="rl-transaction-description" className="rl-muted rl-transaction-description">{step === 'success' ? 'Your local preview has been updated. No blockchain transaction was submitted.' : label.description}</Dialog.Description>

          {step === 'success' ? (
            <div className="rl-transaction-success" aria-live="polite">
              <div className="rl-transaction-success-amount">{format(amount)} <span>USDC</span></div>
              <div className="rl-transaction-details">
                <div><span>Environment</span><strong>Simulated · browser only</strong></div>
                <div><span>Demo wallet balance</span><strong>{format(state.walletBalance)} USDC</strong></div>
                {kind === 'supply' || kind === 'withdraw' ? <div><span>Available supplied balance</span><strong>{format(state.supplied)} USDC</strong></div> : <div><span>Principal + interest remaining</span><strong>{format(state.debt + state.interest)} USDC</strong></div>}
                {successTitle === 'Withdrawal queued' && <p className="rl-transaction-notice">This amount is reserved. Manage it in your withdrawal queue; it is not yet in your demo wallet.</p>}
              </div>
              <button className="rl-button rl-button-primary rl-transaction-submit" onClick={onClose}>Done <Check size={16} /></button>
            </div>
          ) : (
            <form onSubmit={(event) => {
              event.preventDefault()
              if (step === 'review') { confirm(); return }
              if (!quote.ok) { setError(quote.message); return }
              setError('')
              setStep('review')
            }}>
              {step === 'amount' ? (
                <div className="rl-transaction-amount-block">
                  <label htmlFor="rl-transaction-amount">Amount in demo USDC</label>
                  <div className="rl-transaction-input-row">
                    <input id="rl-transaction-amount" type="text" inputMode="decimal" autoComplete="off" placeholder="0.00" value={input} maxLength={18} aria-invalid={Boolean(showError)} aria-describedby={showError ? 'rl-transaction-error' : 'rl-transaction-limit'} onChange={(event) => { setInput(event.target.value); setError('') }} />
                    <span>USDC</span>
                    <button className="rl-transaction-max" type="button" onClick={() => { setInput(quote.max.toFixed(2)); setError('') }}>MAX</button>
                  </div>
                  <p id="rl-transaction-limit" className="rl-muted">{kind === 'borrow' ? 'Available to borrow' : kind === 'withdraw' ? 'Available supplied balance' : kind === 'repay' ? 'Maximum repayment' : 'Demo wallet balance'} <strong>{format(quote.max)} USDC</strong></p>
                </div>
              ) : (
                <div className="rl-transaction-review-amount"><span>Review {label.action}</span><strong>{format(amount)} <small>USDC</small></strong><button type="button" className="rl-transaction-edit" onClick={() => { setStep('amount'); setError('') }}><ChevronLeft size={14} /> Edit amount</button></div>
              )}

              <div className="rl-transaction-details">
                <div><span>Asset</span><strong>USDC <em>Demo</em></strong></div>
                <div><span>{kind === 'repay' ? 'Repayment order' : 'Destination'}</span><strong>{kind === 'supply' ? 'GPU receivables pool' : kind === 'repay' ? 'Interest → principal' : 'Your demo wallet'}</strong></div>
                {kind === 'borrow' && <><div><span>Available credit after borrow</span><strong>{format(Math.max(0, state.creditLimit - state.debt - state.interest - (quote.ok ? amount : 0)))} USDC</strong></div><div><span>Illustrative borrower APR</span><strong>11.50%</strong></div></>}
                {kind === 'repay' && <><div><span>Interest repayment</span><strong>{format(quote.interestPaid)} USDC</strong></div><div><span>Principal repayment</span><strong>{format(quote.principalPaid)} USDC</strong></div></>}
                {kind === 'withdraw' && <div><span>Availability</span><strong>{quote.queued ? 'Queued until liquidity is available' : 'Immediate in this preview'}</strong></div>}
                <div><span>Network fee</span><strong>None · no transaction</strong></div>
              </div>

              {quote.queued && <p className="rl-transaction-notice">Liquidity is limited or earlier requests are pending. The full amount will be reserved and added to the demo queue, in order.</p>}
              {showError && <p className="rl-transaction-error" id="rl-transaction-error" role="alert">{showError}</p>}
              <p className="rl-transaction-warning"><ShieldCheck size={17} aria-hidden="true" /><span>Simulation only. No real wallet connection, signatures, tokens, or transactions.</span></p>
              {!state.connected ? <button type="button" className="rl-button rl-button-primary rl-transaction-submit" onClick={() => { state.connect(); setError('') }}>Connect demo wallet <ArrowUpRight size={16} /></button> : <button type="submit" className="rl-button rl-button-primary rl-transaction-submit" disabled={!quote.ok || busy}>{busy ? 'Updating preview…' : step === 'review' ? `Confirm demo ${label.action}` : `Review ${label.action}`} <ArrowUpRight size={16} /></button>}
              {step === 'review' && <p className="rl-transaction-footnote">Balances are checked again when you confirm.</p>}
            </form>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
