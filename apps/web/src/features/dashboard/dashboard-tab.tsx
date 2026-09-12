import { useState } from 'react'
import { ChevronDown, ChevronRight, Bitcoin, CreditCard, Coins } from 'lucide-react'
import { BorrowerCard } from './borrower-card'
import { ClaimSection } from './claim-section'
import { ProtocolStatusCard } from './protocol-status-card'
import { useWalletStore } from '@/stores/wallet-store'

function HowItWorksBanner() {
  const steps = [
    {
      icon: Bitcoin,
      title: 'Link your BTC wallet',
      desc: 'Sign a message with your Bitcoin wallet to prove ownership and bind it to your EVM address.',
    },
    {
      icon: CreditCard,
      title: 'Get borrowing credit',
      desc: 'Your BTC mining identity is verified on-chain. You receive a testnet credit line.',
    },
    {
      icon: Coins,
      title: 'Borrow stablecoins',
      desc: 'Draw from your credit line to borrow mUSDT instantly — no collateral lock-up needed.',
    },
  ]

  return (
    <div className="col-span-full rounded-xl border border-border/40 bg-gradient-to-br from-card/80 to-card/40 p-4">
      <h2 className="text-sm font-semibold text-foreground/90 mb-3">How HashCredit works</h2>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {steps.map((s, i) => (
          <div key={s.title} className="flex gap-3 items-start">
            <div className="flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-primary/20 text-primary text-xs font-bold">
              {i + 1}
            </div>
            <div className="min-w-0">
              <p className="text-xs font-semibold text-foreground/90">{s.title}</p>
              <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">{s.desc}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export function DashboardTab() {
  const [showProtocol, setShowProtocol] = useState(false)
  const walletAccount = useWalletStore((s) => s.walletAccount)

  return (
    <>
      {!walletAccount && <HowItWorksBanner />}
      <BorrowerCard />
      <ClaimSection />
      <div className="col-span-full">
        <button
          className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors mb-2"
          onClick={() => setShowProtocol((v) => !v)}
          aria-expanded={showProtocol}
        >
          {showProtocol ? (
            <ChevronDown className="h-3.5 w-3.5" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5" />
          )}
          Protocol Details
        </button>
        {showProtocol && <ProtocolStatusCard />}
      </div>
    </>
  )
}
