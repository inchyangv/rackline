import { Contract, type ContractTransactionResponse } from 'ethers'
import { ILendingVaultV2Abi } from './generated/ILendingVaultV2'
import { ICreditFacilityManagerAbi } from './generated/ICreditFacilityManager'
import { IRepaymentRouterAbi } from './generated/IRepaymentRouter'
import { GpuTestTokenAbi } from './generated/GpuTestToken'
import {
  request,
  validateRead,
  type Config,
  type Envelope,
  type Session,
  type TransactionContext,
} from './client'
import { assertWallet } from './use-gpu'

export type Action =
  | 'deposit'
  | 'withdraw'
  | 'requestWithdrawal'
  | 'cancelWithdrawal'
  | 'claimWithdrawal'
  | 'processWithdrawals'
  | 'claimEpochRecovery'
  | 'borrow'
  | 'repay'
  | 'faucet'
export type Progress = {
  stage: 'review' | 'approving' | 'signing' | 'pending' | 'confirmed'
  hash?: string
  message: string
}
const tokenAbi = [
  'function allowance(address owner,address spender) view returns (uint256)',
  'function approve(address spender,uint256 amount) returns (bool)',
  'function decimals() view returns (uint8)',
]

async function confirmed(
  tx: ContractTransactionResponse,
  onProgress: (state: Progress) => void,
) {
  onProgress({
    stage: 'pending',
    hash: tx.hash,
    message: 'Submitted. Waiting for two block confirmations…',
  })
  let receipt
  try {
    receipt = await tx.wait(2)
  } catch (err) {
    const replaced = err as {
      code?: string
      cancelled?: boolean
      receipt?: { status: number }
      replacement?: ContractTransactionResponse
    }
    if (
      replaced.code !== 'TRANSACTION_REPLACED' ||
      replaced.cancelled ||
      !replaced.replacement ||
      replaced.receipt?.status !== 1
    )
      throw err
    // Only a same-call replacement is confirmation of the reviewed action.
    if (
      replaced.replacement.to?.toLowerCase() !== tx.to?.toLowerCase() ||
      replaced.replacement.data !== tx.data ||
      replaced.replacement.value !== tx.value
    )
      throw new Error(
        'The transaction was replaced with a different action. Refresh to inspect its result.',
      )
    receipt = await replaced.replacement.wait(2)
  }
  if (!receipt || receipt.status !== 1)
    throw new Error(
      'Transaction reverted. Refresh your balances before retrying.',
    )
  return receipt
}

export async function quoteVault(
  config: Config,
  session: Session,
  action: Action,
  amount: bigint,
) {
  const provider = await assertWallet(config, session)
  const vault = new Contract(
    config.contracts.vault!,
    ILendingVaultV2Abi,
    provider,
  )
  const quoted: bigint =
    await vault[action === 'deposit' ? 'previewDeposit' : 'previewWithdraw'](
      amount,
    )
  if (quoted <= 0n)
    throw new Error('This amount rounds to zero. Enter a larger amount.')
  return {
    quoted,
    minimum: (quoted * 995n) / 1000n || 1n,
    expiresAt: Date.now() + 120000,
  }
}

export async function executeTransaction(
  config: Config,
  session: Session,
  action: Action,
  amount: bigint,
  reference: string | undefined,
  onProgress: (state: Progress) => void,
  quote?: { minimum: bigint; expiresAt: number } | null,
) {
  if (!config.configured) throw new Error('Contract deployment is unavailable.')
  const provider = await assertWallet(config, session)
  const signer = await provider.getSigner()
  const addresses = [
    config.contracts.asset,
    config.contracts.vault,
    config.contracts.manager,
    config.contracts.repaymentRouter,
  ]
  const codes = await Promise.all(
    addresses.map((address) =>
      address ? provider.getCode(address) : Promise.resolve('0x'),
    ),
  )
  if (codes.some((code) => code === '0x'))
    throw new Error(
      'A configured GPU contract has no deployed code on this network.',
    )
  const token = new Contract(config.contracts.asset!, tokenAbi, signer)
  const vault = new Contract(
    config.contracts.vault!,
    ILendingVaultV2Abi,
    signer,
  )
  if (
    Number(await token.decimals()) !== config.asset.decimals ||
    String(await vault.asset()).toLowerCase() !==
      config.contracts.asset!.toLowerCase()
  )
    throw new Error(
      'Deployed vault asset or token decimals do not match the manifest.',
    )
  let contract = vault
  let method: string = action
  let args: unknown[] = []
  let allowanceSpender: string | null = null
  if (
    action === 'deposit' ||
    action === 'withdraw' ||
    action === 'requestWithdrawal'
  ) {
    if (amount <= 0n) throw new Error('The amount must be positive.')
    if (!quote || quote.expiresAt <= Date.now() || quote.minimum <= 0n)
      throw new Error(
        'Your quote expired. Edit the amount to request a fresh quote.',
      )
    args = [amount, quote.minimum]
    if (action === 'deposit') allowanceSpender = config.contracts.vault
  } else if (action === 'borrow' || action === 'repay') {
    if (!reference)
      throw new Error('Choose the facility receiving this transaction.')
    const context = await request<Envelope<TransactionContext>>(
      `/v1/facilities/${encodeURIComponent(reference)}/transaction-context`,
      { token: session.token },
    )
    validateRead(context.meta, config)
    const ctx = context.data
    if (
      ctx.facilityId !== reference ||
      !/^0x[0-9a-fA-F]{64}$/.test(ctx.canonicalFacilityId) ||
      ctx.chainId !== config.chainId ||
      ctx.expiresAt <= Date.now() / 1000 ||
      ctx.manager.toLowerCase() !== config.contracts.manager!.toLowerCase() ||
      ctx.repaymentRouter.toLowerCase() !==
        config.contracts.repaymentRouter!.toLowerCase() ||
      ctx.asset.address?.toLowerCase() !==
        config.asset.address?.toLowerCase() ||
      ctx.asset.chainId !== config.chainId ||
      ctx.asset.decimals !== config.asset.decimals
    )
      throw new Error(
        'The facility transaction binding is invalid or expired. Refresh before retrying.',
      )
    if (action === 'borrow') {
      if (
        ctx.wallet.toLowerCase() !== session.wallet.toLowerCase() ||
        ctx.availableDraw == null ||
        ctx.drawBlockedReason ||
        amount > BigInt(ctx.availableDraw)
      )
        throw new Error(
          ctx.drawBlockedReason ||
            'New borrowing is unavailable for this wallet or amount.',
        )
      if (context.meta.freshness !== 'FRESH')
        throw new Error(
          'Credit evidence is stale. Repayment remains available.',
        )
      contract = new Contract(
        config.contracts.manager!,
        ICreditFacilityManagerAbi,
        signer,
      )
      args = [ctx.canonicalFacilityId, amount, amount]
    } else {
      contract = new Contract(
        config.contracts.repaymentRouter!,
        IRepaymentRouterAbi,
        signer,
      )
      method = 'repayExact'
      args = [ctx.canonicalFacilityId, amount]
      allowanceSpender = config.contracts.repaymentRouter
    }
  } else if (action === 'faucet') {
    if (
      config.executionProfile !== 'NATIVE_TESTNET' ||
      config.asset.testOnly !== true
    )
      throw new Error(
        'The test-token faucet is unavailable in this environment.',
      )
    contract = new Contract(config.contracts.asset!, GpuTestTokenAbi, signer)
    if ((await contract.testOnly()) !== true)
      throw new Error('The deployed asset is not a test-only faucet token.')
  } else {
    if (action === 'processWithdrawals') args = [20n]
    else {
      if (!reference || !/^\d+$/.test(reference))
        throw new Error('The withdrawal or epoch reference is invalid.')
      args = [BigInt(reference)]
    }
  }
  if (
    allowanceSpender &&
    BigInt(await token.allowance(session.wallet, allowanceSpender)) < amount
  ) {
    onProgress({
      stage: 'approving',
      message: `Approve only this transaction amount in your wallet.`,
    })
    await assertWallet(config, session)
    await confirmed(await token.approve(allowanceSpender, amount), onProgress)
  }
  await assertWallet(config, session)
  if (quote && quote.expiresAt <= Date.now())
    throw new Error(
      'Your quote expired during approval. Edit the amount to request a fresh quote.',
    )
  await contract[method].staticCall(...args)
  onProgress({
    stage: 'signing',
    message: 'Simulation passed. Review the transaction in your wallet.',
  })
  const receipt = await confirmed(await contract[method](...args), onProgress)
  onProgress({
    stage: 'confirmed',
    hash: receipt.hash,
    message: 'Transaction confirmed. Refreshing canonical balances…',
  })
  return receipt.hash
}
