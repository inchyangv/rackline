import { SectionCard } from '@/components/shared/section-card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useConfigStore } from '@/stores/config-store'

export function SettingsTab() {
  const rpcUrl = useConfigStore((s) => s.rpcUrl)
  const setRpcUrl = useConfigStore((s) => s.setRpcUrl)
  const chainId = useConfigStore((s) => s.chainId)
  const setChainId = useConfigStore((s) => s.setChainId)
  const managerAddress = useConfigStore((s) => s.managerAddress)
  const setManagerAddress = useConfigStore((s) => s.setManagerAddress)
  const spvVerifierAddress = useConfigStore((s) => s.spvVerifierAddress)
  const setSpvVerifierAddress = useConfigStore((s) => s.setSpvVerifierAddress)
  const checkpointManagerAddress = useConfigStore((s) => s.checkpointManagerAddress)
  const setCheckpointManagerAddress = useConfigStore((s) => s.setCheckpointManagerAddress)

  return (
    <SectionCard title="Settings" full>
      <div className="space-y-3">
        <div>
          <Label className="text-[10px] uppercase tracking-widest">RPC URL (read-only)</Label>
          <Input value={rpcUrl} onChange={(e) => setRpcUrl(e.target.value)} placeholder="https://..." className="mt-1 font-mono text-xs" />
        </div>
        <div>
          <Label className="text-[10px] uppercase tracking-widest">Chain ID</Label>
          <Input value={String(chainId)} onChange={(e) => setChainId(Number(e.target.value))} placeholder="102031" inputMode="numeric" className="mt-1 font-mono text-xs" />
        </div>
        <div>
          <Label className="text-[10px] uppercase tracking-widest">HashCreditManager</Label>
          <Input value={managerAddress} onChange={(e) => setManagerAddress(e.target.value)} placeholder="0x..." className="mt-1 font-mono text-xs" />
        </div>
        <div>
          <Label className="text-[10px] uppercase tracking-widest">BtcSpvVerifier</Label>
          <Input value={spvVerifierAddress} onChange={(e) => setSpvVerifierAddress(e.target.value)} placeholder="0x..." className="mt-1 font-mono text-xs" />
        </div>
        <div>
          <Label className="text-[10px] uppercase tracking-widest">CheckpointManager</Label>
          <Input value={checkpointManagerAddress} onChange={(e) => setCheckpointManagerAddress(e.target.value)} placeholder="0x..." className="mt-1 font-mono text-xs" />
        </div>
        <p className="text-xs text-muted-foreground">
          Copy `apps/web/.env.example` to `apps/web/.env` to set defaults quickly.
        </p>
      </div>
    </SectionCard>
  )
}
