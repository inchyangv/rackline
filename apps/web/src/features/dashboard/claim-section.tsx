import { ethers, BrowserProvider } from 'ethers'
import { SectionCard } from '@/components/shared/section-card'
import { KeyValueList } from '@/components/shared/key-value-list'
import { KeyValueRow } from '@/components/shared/key-value-row'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { useApiStore } from '@/stores/api-store'
import { useWalletStore } from '@/stores/wallet-store'
import { useConfigStore } from '@/stores/config-store'
import { useApiClient } from '@/hooks/use-api-client'
import { sendContractTx } from '@/stores/tx-store'
import { HashCreditManagerAbi, BtcSpvVerifierAbi } from '@/lib/abis'
import { getEthereum, getErrorMessage } from '@/lib/ethereum'
import { toast } from 'sonner'

export function ClaimSection() {
  const claimBtcAddress = useApiStore((s) => s.claimBtcAddress)
  const setClaimBtcAddress = useApiStore((s) => s.setClaimBtcAddress)
  const claimToken = useApiStore((s) => s.claimToken)
  const setClaimToken = useApiStore((s) => s.setClaimToken)
  const claimMessage = useApiStore((s) => s.claimMessage)
  const setClaimMessage = useApiStore((s) => s.setClaimMessage)
  const claimBtcSignature = useApiStore((s) => s.claimBtcSignature)
  const setClaimBtcSignature = useApiStore((s) => s.setClaimBtcSignature)
  const claimLog = useApiStore((s) => s.claimLog)
  const setClaimLog = useApiStore((s) => s.setClaimLog)
  const claimBusy = useApiStore((s) => s.claimBusy)
  const setClaimBusy = useApiStore((s) => s.setClaimBusy)
  const borrowerAddress = useApiStore((s) => s.borrowerAddress)
  const walletAccount = useWalletStore((s) => s.walletAccount)
  const managerAddress = useConfigStore((s) => s.managerAddress)
  const spvVerifierAddress = useConfigStore((s) => s.spvVerifierAddress)

  const { apiRequest } = useApiClient()

  const borrower = borrowerAddress || walletAccount

  async function generateChallenge() {
    if (!ethers.isAddress(borrower)) {
      toast.error('Borrower EVM address is required (connect wallet or enter above)')
      return
    }
    if (!claimBtcAddress) {
      toast.error('Enter a BTC address')
      return
    }

    setClaimBusy(true)
    setClaimLog('')
    setClaimToken('')
    setClaimMessage('')
    try {
      const result = await apiRequest('/claim/start', {
        method: 'POST',
        body: JSON.stringify({ borrower, btc_address: claimBtcAddress }),
      })
      const r = result as Record<string, unknown>
      if (r.success && typeof r.claim_token === 'string' && typeof r.message === 'string') {
        setClaimToken(r.claim_token)
        setClaimMessage(r.message)
        setClaimLog(`Challenge generated. Sign the message below in your BTC wallet.\nExpires: ${new Date((r.expires_at as number) * 1000).toLocaleTimeString()}`)
        toast.success('Challenge generated — sign it in your BTC wallet')
      } else {
        setClaimLog(`Error: ${r.error || 'Unknown error'}`)
      }
    } catch (e) {
      setClaimLog(`Error: ${getErrorMessage(e)}`)
    } finally {
      setClaimBusy(false)
    }
  }

  async function verifyAndRegister() {
    if (!claimToken || !claimMessage) {
      toast.error('Generate a challenge first')
      return
    }
    if (!claimBtcSignature.trim()) {
      toast.error('Paste the BTC signature (base64)')
      return
    }

    setClaimBusy(true)
    setClaimLog('Step 1/3: Signing with EVM wallet (MetaMask)...')
    try {
      // 1. EVM signature via MetaMask
      const ethereum = getEthereum()
      if (!ethereum) throw new Error('Browser wallet not found')
      const provider = new BrowserProvider(ethereum)
      const signer = await provider.getSigner()
      const evmSignature = await signer.signMessage(claimMessage)

      // 2. Verify both signatures via API
      setClaimLog('Step 2/3: Verifying signatures (API)...')
      const result = await apiRequest('/claim/complete', {
        method: 'POST',
        body: JSON.stringify({
          claim_token: claimToken,
          evm_signature: evmSignature,
          btc_signature: claimBtcSignature.trim(),
        }),
      })
      const r = result as Record<string, unknown>
      if (!r.success) {
        setClaimLog(`Verification failed: ${r.error}`)
        toast.error(`Verification failed: ${r.error}`)
        return
      }

      const pubkeyHash = r.pubkey_hash as string
      const btcPayoutKeyHash = r.btc_payout_key_hash as string

      setClaimLog(
        `Verified!\n` +
        `  pubkeyHash: ${pubkeyHash}\n` +
        `  btcPayoutKeyHash: ${btcPayoutKeyHash}\n\n` +
        `Step 3/3: Registering on-chain (2 transactions)...`
      )

      // 3. On-chain registration: setBorrowerPubkeyHash
      await sendContractTx(
        'setBorrowerPubkeyHash',
        spvVerifierAddress,
        BtcSpvVerifierAbi,
        (c) => c.setBorrowerPubkeyHash(borrower, pubkeyHash),
      )

      // 4. On-chain registration: registerBorrower
      await sendContractTx(
        'registerBorrower',
        managerAddress,
        HashCreditManagerAbi,
        (c) => c.registerBorrower(borrower, btcPayoutKeyHash),
      )

      setClaimLog(
        `Done!\n` +
        `  BTC ownership verified (BIP-137 + EVM signature)\n` +
        `  pubkeyHash: ${pubkeyHash}\n` +
        `  btcPayoutKeyHash: ${btcPayoutKeyHash}\n` +
        `  On-chain: setBorrowerPubkeyHash + registerBorrower submitted`
      )
      toast.success('Borrower registered with verified BTC ownership!')
    } catch (e) {
      setClaimLog(`Error: ${getErrorMessage(e)}`)
      toast.error(getErrorMessage(e))
    } finally {
      setClaimBusy(false)
    }
  }

  function copyMessage() {
    if (claimMessage) {
      navigator.clipboard.writeText(claimMessage)
      toast.success('Message copied — paste into your BTC wallet\'s Sign Message')
    }
  }

  const hasChallenge = !!claimToken && !!claimMessage

  return (
    <SectionCard
      title="Claim: Prove BTC Wallet Ownership"
      description="Verify you own a BTC address via BIP-137 signature, then register as borrower on-chain."
      full
    >
      <div className="space-y-4">
        {/* Step 1: Generate challenge */}
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary/20 text-[10px] font-bold text-primary">1</span>
            <Label className="text-xs font-semibold">Generate Challenge</Label>
          </div>
          <div>
            <Label className="text-[10px] uppercase tracking-widest">BTC Address (testnet)</Label>
            <Input
              value={claimBtcAddress}
              onChange={(e) => setClaimBtcAddress(e.target.value.trim())}
              placeholder="tb1q... or m... or n..."
              className="mt-1 font-mono text-xs"
            />
          </div>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => void generateChallenge()}
            disabled={claimBusy || !borrower}
          >
            Generate Challenge
          </Button>
        </div>

        {/* Step 2: Sign in BTC wallet */}
        {hasChallenge && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary/20 text-[10px] font-bold text-primary">2</span>
              <Label className="text-xs font-semibold">Sign in BTC Wallet (Sparrow / Electrum / CLI)</Label>
            </div>
            <div className="relative">
              <Label className="text-[10px] uppercase tracking-widest">Message to sign</Label>
              <Textarea
                value={claimMessage}
                readOnly
                rows={7}
                className="mt-1 font-mono text-xs bg-secondary/30"
              />
              <Button
                variant="outline"
                size="sm"
                className="absolute top-6 right-2"
                onClick={copyMessage}
              >
                Copy
              </Button>
            </div>
            <div>
              <Label className="text-[10px] uppercase tracking-widest">BTC Signature (base64, from wallet)</Label>
              <Textarea
                value={claimBtcSignature}
                onChange={(e) => setClaimBtcSignature(e.target.value)}
                placeholder="Paste base64 signature from your BTC wallet here..."
                rows={2}
                className="mt-1 font-mono text-xs"
              />
            </div>
          </div>
        )}

        {/* Step 3: Verify & Register */}
        {hasChallenge && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary/20 text-[10px] font-bold text-primary">3</span>
              <Label className="text-xs font-semibold">Verify & Register On-chain</Label>
            </div>
            <p className="text-xs text-muted-foreground">
              Clicking below will: sign with MetaMask (EVM proof) → verify both signatures (API) → register borrower on-chain (2 wallet transactions).
            </p>
            <Button
              size="sm"
              onClick={() => void verifyAndRegister()}
              disabled={claimBusy || !claimBtcSignature.trim() || !walletAccount}
            >
              Verify & Register
            </Button>
          </div>
        )}

        {/* Log */}
        {claimLog && (
          <KeyValueList>
            <KeyValueRow label="Status" value={claimLog} mono pre />
          </KeyValueList>
        )}
      </div>
    </SectionCard>
  )
}
