import type { TabId } from '@/types'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

type Props = {
  tab: TabId
  onTabChange: (tab: TabId) => void
}

const tabs: { id: TabId; label: string }[] = [
  { id: 'dashboard', label: 'Dashboard' },
  { id: 'ops', label: 'Operations' },
  { id: 'proof', label: 'Proof/Submit' },
  { id: 'admin', label: 'Admin' },
  { id: 'config', label: 'Settings' },
]

export function Header({ tab, onTabChange }: Props) {
  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-border/40 bg-gradient-to-br from-[rgba(16,24,49,0.82)] to-[rgba(15,32,53,0.6)] p-3.5 sm:p-4">
      <div className="flex items-center gap-3">
        <div className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-gradient-to-br from-[#51beb0] to-[#5f7ae8] shadow-[0_0_22px_rgba(79,167,154,0.42),inset_0_0_18px_rgba(255,255,255,0.12)]">
          <span className="text-lg font-bold text-white">HC</span>
        </div>
        <div className="min-w-0">
          <div className="text-lg font-bold leading-tight sm:text-xl">HashCredit</div>
          <div className="text-xs text-muted-foreground mt-0.5">
            Creditcoin Testnet SPV Demo Dashboard
          </div>
        </div>
      </div>

      <Tabs value={tab} onValueChange={(v) => onTabChange(v as TabId)}>
        <TabsList className="h-auto flex-wrap gap-1 bg-transparent p-0">
          {tabs.map((t) => (
            <TabsTrigger
              key={t.id}
              value={t.id}
              className="rounded-lg border border-border/40 bg-secondary/30 px-3 py-1.5 text-xs font-semibold tracking-wider data-[state=active]:border-primary/40 data-[state=active]:bg-gradient-to-b data-[state=active]:from-primary/30 data-[state=active]:to-primary/10 data-[state=active]:text-primary-foreground"
            >
              {t.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
    </div>
  )
}
