import { useState, useEffect } from 'react'
import { ethers } from 'ethers'
import { SectionCard } from '@/components/shared/section-card'
import { KeyValueList } from '@/components/shared/key-value-list'
import { KeyValueRow } from '@/components/shared/key-value-row'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible'
import { useApiStore } from '@/stores/api-store'
import { useWalletStore } from '@/stores/wallet-store'
import { useConfigStore } from '@/stores/config-store'
import { useSpvReads } from '@/hooks/use-spv-reads'
import { sendContractTx } from '@/stores/tx-store'
import { HashCreditManagerAbi, BtcSpvVerifierAbi } from '@/lib/abis'
import { isHexBytes } from '@/lib/format'
import { toast } from 'sonner'

export function AdminSection() {
  const [open, setOpen] = useState(false)

  const adminBorrower = useApiStore((s) => s.adminBorrower)
  const setAdminBorrower = useApiStore((s) => s.setAdminBorrower)
  const adminBtcAddr = useApiStore((s) => s.adminBtcAddr)
  const setAdminBtcAddr = useApiStore((s) => s.setAdminBtcAddr)
  const adminBtcKeyHash = useApiStore((s) => s.adminBtcKeyHash)
  const setAdminBtcKeyHash = useApiStore((s) => s.setAdminBtcKeyHash)
  const adminNewVerifier = useApiStore((s) => s.adminNewVerifier)
  const setAdminNewVerifier = useApiStore((s) => s.setAdminNewVerifier)
  const spvBorrower = useApiStore((s) => s.spvBorrower)
  const setSpvBorrower = useApiStore((s) => s.setSpvBorrower)
  const spvPubkeyHash = useApiStore((s) => s.spvPubkeyHash)
  const setSpvPubkeyHash = useApiStore((s) => s.setSpvPubkeyHash)
  const walletAccount = useWalletStore((s) => s.walletAccount)
  const managerAddress = useConfigStore((s) => s.managerAddress)
  const spvVerifierAddress = useConfigStore((s) => s.spvVerifierAddress)

  const { spvBorrowerOnchainPubkeyHash } = useSpvReads(spvBorrower)

  useEffect(() => {
    if (!adminBtcAddr) return
    try {
      const hash = ethers.keccak256(ethers.toUtf8Bytes(adminBtcAddr))
      setAdminBtcKeyHash(hash)
    } catch {
      // ignore
    }
  }, [adminBtcAddr, setAdminBtcKeyHash])

  async function registerBorrower() {
    if (!ethers.isAddress(adminBorrower)) { toast.error('Invalid borrower address'); return }
    if (!adminBtcKeyHash || !isHexBytes(adminBtcKeyHash) || adminBtcKeyHash.length !== 66) {
      toast.error('Invalid BTC payout key hash')
      return
    }
    toast.promise(
      sendContractTx('registerBorrower', managerAddress, HashCreditManagerAbi, (c) =>
        c.registerBorrower(adminBorrower, adminBtcKeyHash),
      ),
      { loading: 'Registering borrower...', success: 'Borrower registered!', error: 'Registration failed' },
    )
  }

  async function setVerifier() {
    if (!ethers.isAddress(adminNewVerifier)) { toast.error('Invalid verifier address'); return }
    toast.promise(
      sendContractTx('setVerifier', managerAddress, HashCreditManagerAbi, (c) =>
        c.setVerifier(adminNewVerifier),
      ),
      { loading: 'Updating verifier...', success: 'Verifier updated!', error: 'Update failed' },
    )
  }

  async function setBorrowerPubkeyHash() {
    if (!ethers.isAddress(spvBorrower)) { toast.error('Invalid borrower address'); return }
    if (!spvPubkeyHash || !isHexBytes(spvPubkeyHash) || spvPubkeyHash.length !== 42) {
      toast.error('Pubkey hash must be 20 bytes (0x + 40 hex)')
      return
    }
    toast.promise(
      sendContractTx('setBorrowerPubkeyHash', spvVerifierAddress, BtcSpvVerifierAbi, (c) =>
        c.setBorrowerPubkeyHash(spvBorrower, spvPubkeyHash),
      ),
      { loading: 'Setting pubkey hash...', success: 'Pubkey hash saved!', error: 'Update failed' },
    )
  }

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="col-span-full">
      <CollapsibleTrigger asChild>
        <button className="flex w-full items-center gap-2 rounded-xl border border-border/40 bg-gradient-to-br from-card/80 to-card/60 px-4 py-3 text-sm font-semibold text-foreground/90 hover:bg-card/90 transition-colors">
          <span className="transition-transform" style={{ transform: open ? 'rotate(90deg)' : 'rotate(0deg)' }}>▶</span>
          Settings
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5 mt-3">
          <SectionCard title="Borrower Registration" description="Register a new borrower with their BTC payout address.">
            <div className="space-y-3">
              <div>
                <Label className="text-[10px] uppercase tracking-widest">Borrower Address</Label>
                <Input value={adminBorrower} onChange={(e) => setAdminBorrower(e.target.value)} placeholder="0x..." className="mt-1 font-mono text-xs" />
              </div>
              <div>
                <Label className="text-[10px] uppercase tracking-widest">BTC Payout Address</Label>
                <Input value={adminBtcAddr} onChange={(e) => setAdminBtcAddr(e.target.value)} placeholder="tb1..." className="mt-1 font-mono text-xs" />
              </div>
              <div>
                <Label className="text-[10px] uppercase tracking-widest">Payout Key Hash</Label>
                <Input value={adminBtcKeyHash} onChange={(e) => setAdminBtcKeyHash(e.target.value)} placeholder="0x..." className="mt-1 font-mono text-xs" />
              </div>
              <Button variant="secondary" size="sm" onClick={() => void registerBorrower()} disabled={!walletAccount}>
                Register Borrower
              </Button>

              <div className="pt-2">
                <Label className="text-[10px] uppercase tracking-widest">Verifier Address</Label>
                <Input value={adminNewVerifier} onChange={(e) => setAdminNewVerifier(e.target.value)} placeholder="0x..." className="mt-1 font-mono text-xs" />
              </div>
              <Button variant="secondary" size="sm" onClick={() => void setVerifier()} disabled={!walletAccount}>
                Update Verifier
              </Button>
            </div>
          </SectionCard>

          <SectionCard title="SPV Configuration" description="Link a borrower to their Bitcoin pubkey hash for SPV verification.">
            <div className="space-y-3">
              <div>
                <Label className="text-[10px] uppercase tracking-widest">Borrower Address</Label>
                <Input value={spvBorrower} onChange={(e) => setSpvBorrower(e.target.value)} placeholder="0x..." className="mt-1 font-mono text-xs" />
              </div>
              <div>
                <Label className="text-[10px] uppercase tracking-widest">Pubkey Hash</Label>
                <Input value={spvPubkeyHash} onChange={(e) => setSpvPubkeyHash(e.target.value)} placeholder="0x + 40 hex" className="mt-1 font-mono text-xs" />
              </div>
              <KeyValueList>
                <KeyValueRow label="On-chain Pubkey Hash" value={spvBorrowerOnchainPubkeyHash || '—'} mono />
              </KeyValueList>
              <Button variant="secondary" size="sm" onClick={() => void setBorrowerPubkeyHash()} disabled={!walletAccount}>
                Save Pubkey Hash
              </Button>
            </div>
          </SectionCard>
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}
