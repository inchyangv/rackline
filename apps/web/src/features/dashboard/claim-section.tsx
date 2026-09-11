import { ethers } from 'ethers'
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
import { getErrorMessage } from '@/lib/ethereum'
import { toast } from 'sonner'

export function ClaimSection() {
  const claimBtcAddress = useApiStore((s) => s.claimBtcAddress)
  const setClaimBtcAddress = useApiStore((s) => s.setClaimBtcAddress)
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

  // The message the BTC wallet must sign
  const claimMessage = borrower
    ? `HashCredit: Link BTC to ${borrower}`
    : ''

  async function verifyAndRegister() {
    if (!ethers.isAddress(borrower)) {
      toast.error('Connect wallet or enter a borrower address first')
      return
    }
    if (!claimBtcAddress) {
      toast.error('Enter your BTC address')
      return
    }
    if (!claimBtcSignature.trim()) {
      toast.error('Paste the BTC signature (base64)')
      return
    }

    setClaimBusy(true)
    setClaimLog('')
    try {
      // Step 1: Extract on-chain params from BTC signature
      setClaimLog('Step 1/3: Extracting signature parameters...')
      const result = await apiRequest('/claim/extract-sig-params', {
        method: 'POST',
        body: JSON.stringify({
          message: claimMessage,
          signature_b64: claimBtcSignature.trim(),
        }),
      })
      const params = result as Record<string, unknown>
      if (!params.success) {
        setClaimLog(`Error: ${params.error}`)
        toast.error(String(params.error))
        return
      }

      // Step 2: On-chain BTC signature verification via claimBtcAddress
      setClaimLog('Step 2/3: Verifying BTC signature on-chain...')
      await sendContractTx(
        'claimBtcAddress',
        spvVerifierAddress,
        BtcSpvVerifierAbi,
        (c) => c.claimBtcAddress(
          params.pub_key_x,
          params.pub_key_y,
          params.btc_msg_hash,
          params.v,
          params.r,
          params.s,
        ),
      )

      // Step 3: Register borrower in Manager
      setClaimLog('Step 3/3: Registering borrower...')
      const btcPayoutKeyHash = ethers.keccak256(ethers.toUtf8Bytes(claimBtcAddress))
      await sendContractTx(
        'registerBorrower',
        managerAddress,
        HashCreditManagerAbi,
        (c) => c.registerBorrower(borrower, btcPayoutKeyHash),
      )

      // Step 4: Grant testnet credit (1000 USDT = 1000e6)
      setClaimLog('Granting testnet credit...')
      await sendContractTx(
        'grantTestnetCredit',
        managerAddress,
        HashCreditManagerAbi,
        (c) => c.grantTestnetCredit(borrower, 1_000_000_000n),
      )

      setClaimLog(
        `Done!\n` +
        `  BTC signature verified on-chain (secp256k1 ecrecover)\n` +
        `  BTC address: ${claimBtcAddress}\n` +
        `  Borrower registered with 1,000 cUSD credit`
      )
      toast.success('BTC wallet linked & borrower registered!')
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
      description="Sign a message with your Bitcoin wallet, then verify the signature on-chain."
      full
    >
      <div className="space-y-4">
        {/* Step 1: BTC Address */}
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary/20 text-[10px] font-bold text-primary">1</span>
            <Label className="text-xs font-semibold">BTC Address</Label>
          </div>
          <Input
            value={claimBtcAddress}
            onChange={(e) => setClaimBtcAddress(e.target.value.trim())}
            placeholder="tb1q... (copy from MetaMask Bitcoin wallet)"
            className="font-mono text-xs"
          />
        </div>

        {/* Step 2: Sign message */}
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary/20 text-[10px] font-bold text-primary">2</span>
            <Label className="text-xs font-semibold">Sign Message with BTC Wallet</Label>
          </div>
          {claimMessage && (
            <div>
              <Label className="text-[10px] uppercase tracking-widest">Message to sign</Label>
              <Textarea
                value={claimMessage}
                readOnly
                rows={2}
                className="mt-1 font-mono text-xs bg-secondary/30"
              />
            </div>
          )}
          <div>
            <Label className="text-[10px] uppercase tracking-widest">BTC Signature (base64)</Label>
            <Textarea
              value={claimBtcSignature}
              onChange={(e) => setClaimBtcSignature(e.target.value)}
              placeholder="Paste base64 signature from your BTC wallet..."
              rows={2}
              className="mt-1 font-mono text-xs"
            />
          </div>
        </div>

        {/* Step 3: Verify on-chain */}
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary/20 text-[10px] font-bold text-primary">3</span>
            <Label className="text-xs font-semibold">Verify On-chain & Register</Label>
          </div>
          <p className="text-xs text-muted-foreground">
            BTC signature is verified on-chain using secp256k1 ecrecover. Borrower gets 1,000 cUSD testnet credit.
          </p>
          <Button
            size="sm"
            onClick={() => void verifyAndRegister()}
            disabled={claimBusy || !claimBtcSignature.trim() || !walletAccount || !claimBtcAddress}
          >
            Verify & Register
          </Button>
        </div>

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
