import { ethers, BrowserProvider } from 'ethers'
import { SectionCard } from '@/components/shared/section-card'
import { KeyValueList } from '@/components/shared/key-value-list'
import { KeyValueRow } from '@/components/shared/key-value-row'
import { Input } from '@/components/ui/input'
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
  const setClaimToken = useApiStore((s) => s.setClaimToken)
  const setClaimMessage = useApiStore((s) => s.setClaimMessage)
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

  async function claimAndRegister() {
    if (!ethers.isAddress(borrower)) {
      toast.error('Connect wallet or enter a borrower address first')
      return
    }
    if (!claimBtcAddress) {
      toast.error('Enter your BTC address')
      return
    }

    setClaimBusy(true)
    setClaimLog('')
    setClaimToken('')
    setClaimMessage('')
    try {
      // Step 1: Generate challenge
      setClaimLog('Step 1/3: Generating challenge...')
      const startResult = await apiRequest('/claim/start', {
        method: 'POST',
        body: JSON.stringify({ borrower, btc_address: claimBtcAddress }),
      })
      const sr = startResult as Record<string, unknown>
      if (!sr.success || typeof sr.claim_token !== 'string' || typeof sr.message !== 'string') {
        setClaimLog(`Error: ${sr.error || 'Failed to generate challenge'}`)
        toast.error(String(sr.error || 'Failed to generate challenge'))
        return
      }
      setClaimToken(sr.claim_token)
      setClaimMessage(sr.message)

      // Step 2: Sign with MetaMask (EVM)
      setClaimLog('Step 2/3: Signing with MetaMask...')
      const ethereum = getEthereum()
      if (!ethereum) throw new Error('Browser wallet not found')
      const provider = new BrowserProvider(ethereum)
      const signer = await provider.getSigner()
      const evmSignature = await signer.signMessage(sr.message)

      // Step 3: Verify via API (no BTC signature needed)
      setClaimLog('Step 3/3: Verifying and registering on-chain...')
      const completeResult = await apiRequest('/claim/complete', {
        method: 'POST',
        body: JSON.stringify({
          claim_token: sr.claim_token,
          evm_signature: evmSignature,
        }),
      })
      const cr = completeResult as Record<string, unknown>
      if (!cr.success) {
        setClaimLog(`Verification failed: ${cr.error}`)
        toast.error(`Verification failed: ${cr.error}`)
        return
      }

      const pubkeyHash = cr.pubkey_hash as string
      const btcPayoutKeyHash = cr.btc_payout_key_hash as string

      setClaimLog(
        `Verified!\n` +
        `  pubkeyHash: ${pubkeyHash}\n` +
        `  btcPayoutKeyHash: ${btcPayoutKeyHash}\n\n` +
        `Registering on-chain (2 transactions)...`
      )

      // On-chain registration
      await sendContractTx(
        'setBorrowerPubkeyHash',
        spvVerifierAddress,
        BtcSpvVerifierAbi,
        (c) => c.setBorrowerPubkeyHash(borrower, pubkeyHash),
      )
      await sendContractTx(
        'registerBorrower',
        managerAddress,
        HashCreditManagerAbi,
        (c) => c.registerBorrower(borrower, btcPayoutKeyHash),
      )

      setClaimLog(
        `Done!\n` +
        `  BTC address linked via EVM signature\n` +
        `  pubkeyHash: ${pubkeyHash}\n` +
        `  btcPayoutKeyHash: ${btcPayoutKeyHash}\n` +
        `  On-chain registration complete`
      )
      toast.success('Borrower registered!')
    } catch (e) {
      setClaimLog(`Error: ${getErrorMessage(e)}`)
      toast.error(getErrorMessage(e))
    } finally {
      setClaimBusy(false)
    }
  }

  return (
    <SectionCard
      title="Link BTC Wallet"
      description="Enter your BTC address from MetaMask and sign with your EVM wallet to register as a borrower."
      full
    >
      <div className="space-y-4">
        <div className="space-y-2">
          <div>
            <Label className="text-[10px] uppercase tracking-widest">BTC Address</Label>
            <Input
              value={claimBtcAddress}
              onChange={(e) => setClaimBtcAddress(e.target.value.trim())}
              placeholder="tb1q... (copy from MetaMask Bitcoin wallet)"
              className="mt-1 font-mono text-xs"
            />
          </div>
          <Button
            size="sm"
            onClick={() => void claimAndRegister()}
            disabled={claimBusy || !borrower || !claimBtcAddress}
          >
            Link & Register
          </Button>
        </div>

        {claimLog && (
          <KeyValueList>
            <KeyValueRow label="Status" value={claimLog} mono pre />
          </KeyValueList>
        )}
      </div>
    </SectionCard>
  )
}
