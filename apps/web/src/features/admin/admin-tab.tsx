import { useEffect } from 'react'
import { ethers } from 'ethers'
import { SectionCard } from '@/components/shared/section-card'
import { KeyValueList } from '@/components/shared/key-value-list'
import { KeyValueRow } from '@/components/shared/key-value-row'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { useApiStore } from '@/stores/api-store'
import { useWalletStore } from '@/stores/wallet-store'
import { useConfigStore } from '@/stores/config-store'
import { useSpvReads } from '@/hooks/use-spv-reads'
import { sendContractTx } from '@/stores/tx-store'
import { HashCreditManagerAbi, BtcSpvVerifierAbi } from '@/lib/abis'
import { isHexBytes } from '@/lib/format'
import { toast } from 'sonner'

export function AdminTab() {
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

  // Convenience: compute keccak256(btcAddressString)
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
    if (!ethers.isAddress(adminBorrower)) { toast.error('Invalid Borrower address'); return }
    if (!adminBtcKeyHash || !isHexBytes(adminBtcKeyHash) || adminBtcKeyHash.length !== 66) {
      toast.error('Invalid btcPayoutKeyHash (bytes32)')
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
    if (!ethers.isAddress(adminNewVerifier)) { toast.error('Invalid Verifier address'); return }
    toast.promise(
      sendContractTx('setVerifier', managerAddress, HashCreditManagerAbi, (c) =>
        c.setVerifier(adminNewVerifier),
      ),
      { loading: 'Setting verifier...', success: 'Verifier set!', error: 'setVerifier failed' },
    )
  }

  async function setBorrowerPubkeyHash() {
    if (!ethers.isAddress(spvBorrower)) { toast.error('Invalid Borrower address'); return }
    if (!spvPubkeyHash || !isHexBytes(spvPubkeyHash) || spvPubkeyHash.length !== 42) {
      toast.error('pubkeyHash must be bytes20 (0x + 40 hex)')
      return
    }
    toast.promise(
      sendContractTx('setBorrowerPubkeyHash', spvVerifierAddress, BtcSpvVerifierAbi, (c) =>
        c.setBorrowerPubkeyHash(spvBorrower, spvPubkeyHash),
      ),
      { loading: 'Setting pubkeyHash...', success: 'PubkeyHash set!', error: 'setBorrowerPubkeyHash failed' },
    )
  }

  return (
    <>
      <SectionCard title="Admin (Manager, Wallet)" description="Only owner succeeds. Check revert reason in Tx status.">
        <div className="space-y-3">
          <div>
            <Label className="text-[10px] uppercase tracking-widest">registerBorrower: borrower</Label>
            <Input value={adminBorrower} onChange={(e) => setAdminBorrower(e.target.value)} placeholder="0x..." className="mt-1 font-mono text-xs" />
          </div>
          <div>
            <Label className="text-[10px] uppercase tracking-widest">BTC address (string → keccak)</Label>
            <Input value={adminBtcAddr} onChange={(e) => setAdminBtcAddr(e.target.value)} placeholder="tb1..." className="mt-1 font-mono text-xs" />
          </div>
          <div>
            <Label className="text-[10px] uppercase tracking-widest">btcPayoutKeyHash (bytes32)</Label>
            <Input value={adminBtcKeyHash} onChange={(e) => setAdminBtcKeyHash(e.target.value)} placeholder="0x..." className="mt-1 font-mono text-xs" />
          </div>
          <Button variant="secondary" size="sm" onClick={() => void registerBorrower()} disabled={!walletAccount}>
            registerBorrower
          </Button>

          <div className="pt-2">
            <Label className="text-[10px] uppercase tracking-widest">setVerifier: newVerifier</Label>
            <Input value={adminNewVerifier} onChange={(e) => setAdminNewVerifier(e.target.value)} placeholder="0x..." className="mt-1 font-mono text-xs" />
          </div>
          <Button variant="secondary" size="sm" onClick={() => void setVerifier()} disabled={!walletAccount}>
            setVerifier
          </Button>
        </div>
      </SectionCard>

      <SectionCard title="Admin (SPV Verifier, Wallet)" description="setBorrowerPubkeyHash is required for the SPV path.">
        <div className="space-y-3">
          <div>
            <Label className="text-[10px] uppercase tracking-widest">borrower</Label>
            <Input value={spvBorrower} onChange={(e) => setSpvBorrower(e.target.value)} placeholder="0x..." className="mt-1 font-mono text-xs" />
          </div>
          <div>
            <Label className="text-[10px] uppercase tracking-widest">pubkeyHash (bytes20)</Label>
            <Input value={spvPubkeyHash} onChange={(e) => setSpvPubkeyHash(e.target.value)} placeholder="0x + 40 hex" className="mt-1 font-mono text-xs" />
          </div>
          <KeyValueList>
            <KeyValueRow label="on-chain pubkeyHash" value={spvBorrowerOnchainPubkeyHash || '—'} mono />
          </KeyValueList>
          <Button variant="secondary" size="sm" onClick={() => void setBorrowerPubkeyHash()} disabled={!walletAccount}>
            setBorrowerPubkeyHash
          </Button>
        </div>
      </SectionCard>
    </>
  )
}
