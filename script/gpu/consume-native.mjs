/**
 * Native TEST_ONLY technical integration. Default is read-only preparation; publishing requires BOTH flags.
 * Receipt logs are untrusted claims, never a decoder substitute: ReceivableBook compares every byte against
 * the official on-chain decoder after the immutable BlockProver verifies the SDK proof.
 * Source reservations retain their ORIGINAL timestamps. Expired checkpoints cannot authorize borrowing.
 */
import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
const require = createRequire(path.resolve('offchain/attestcoin/package.json'))
const { Interface, AbiCoder, JsonRpcProvider, Wallet, Contract, id, ZeroHash, keccak256 } = require('ethers')
const abi = name => JSON.parse(fs.readFileSync(`test/fixtures/gpu/abi/${name}.json`, 'utf8'))
const steps = {
  recognizeObligation: 'ObligationRecognizedV2', assignObligation: 'ObligationAssigned',
  correctObligation: 'ObligationCorrected', settle: 'PayoutReceived', cancelPayout: 'PayoutCancelled',
  reserveCheckpoint: 'SourceCheckpointV2',
}
export const ACCOUNT = id('mockdepin-testonly:native-integration')
export const PROVIDER = id('mockdepin-testonly')
export const FACILITY = id('gpu080-facility-v2')
// Report-only: which facility's eligibleUnpaid/legalDebt the summary reads (`--facility <name>`).
const facilityArg = process.argv.indexOf('--facility')
const REPORT_FACILITY = facilityArg >= 0 && process.argv[facilityArg + 1] ? id(process.argv[facilityArg + 1]) : FACILITY

/** Transaction-local ordinal is the array index, NOT the block-global RPC logIndex. */
export function claimFromReceipt(step, receipt, emitter, validUntil, sourceAbi = abi('SourceEscrow')) {
  if (!steps[step] || receipt.status !== 1) throw new Error('Successful known source transition required')
  const iface = new Interface(sourceAbi)
  const topic0 = iface.getEvent(steps[step]).topicHash
  const matches = receipt.logs.map((log, ordinal) => ({ log, ordinal }))
    .filter(({ log }) => log.address.toLowerCase() === emitter.toLowerCase() && log.topics[0] === topic0)
  if (matches.length !== 1) throw new Error(`Expected exactly one ${steps[step]} log`)
  const { log, ordinal } = matches[0]
  if (log.topics[1] !== ACCOUNT) throw new Error('Source account binding mismatch')
  const decoded = iface.parseLog(log)
  const claim = { logOrdinal: ordinal, accountKey: log.topics[1], topic2: log.topics[2] ?? ZeroHash,
    topic3: log.topics[3] ?? ZeroHash, data: log.data, validUntil }
  const protection = step === 'reserveCheckpoint' ? {
    observedAt: Number(decoded.args.observedAt), protectedUntil: Number(decoded.args.protectedUntil),
    checkpointSeq: String(decoded.args.checkpointSeq),
  } : null
  return { topic0, claim, protection }
}

export function canonicalSourceEventId(manifest, artifact, ordinal) {
  return keccak256(AbiCoder.defaultAbiCoder().encode(['bytes32', 'uint64', 'uint64', 'uint64', 'uint32'],
    [id(manifest.envId), artifact.chainKey, artifact.height, artifact.txIndex, ordinal]))
}

/** Scope proof-only checks to this transaction, not unrelated LP activity during confirmations. */
export function assertProofOnlyReceipt(receipt, manifest) {
  if (receipt.status !== 1) throw new Error('Successful proof receipt required')
  const financial = new Set(['DebtLedger', 'LendingVaultV2', 'RepaymentRouter', 'RecoveryManager', 'SettlementReceiver']
    .map(name => manifest.contracts[name]?.toLowerCase()).filter(Boolean))
  const tokenAddress = manifest.asset.address.toLowerCase()
  const vaultAddress = manifest.contracts.LendingVaultV2.toLowerCase()
  const tokenInterface = new Interface(['event Transfer(address indexed from,address indexed to,uint256 value)'])
  for (const log of receipt.logs) {
    if (financial.has(log.address.toLowerCase())) throw new Error('Proof transaction emitted a financial-contract mutation event')
    if (log.address.toLowerCase() !== tokenAddress || log.topics[0] !== tokenInterface.getEvent('Transfer').topicHash) continue
    const transfer = tokenInterface.parseLog(log)
    if ([transfer.args.from, transfer.args.to].some(address => address.toLowerCase() === vaultAddress)) {
      throw new Error('Proof transaction transferred destination vault cash')
    }
  }
  return { method: 'CANONICAL_TRANSACTION_RECEIPT_EVENTS', debtMutationEvents: 0, vaultMutationEvents: 0, vaultAssetTransfers: 0 }
}

/** Reconcile the whole mined block while attributing other users' cash movements to their own transactions. */
export function reconcileVaultCashBlock(receipt, manifest, before, after, logs) {
  assertProofOnlyReceipt(receipt, manifest)
  const tokenAddress = manifest.asset.address.toLowerCase()
  const vaultAddress = manifest.contracts.LendingVaultV2.toLowerCase()
  const tokenInterface = new Interface(['event Transfer(address indexed from,address indexed to,uint256 value)'])
  const movements = []
  const seen = new Set()
  let net = 0n
  for (const log of logs) {
    if (log.address.toLowerCase() !== tokenAddress || log.topics[0] !== tokenInterface.getEvent('Transfer').topicHash) continue
    if (log.blockNumber !== receipt.blockNumber || log.blockHash !== receipt.blockHash || log.removed) {
      throw new Error('Cash reconciliation log is outside the canonical proof block')
    }
    const key = `${log.transactionHash}:${log.index}`
    if (!log.transactionHash || !Number.isInteger(log.index) || seen.has(key)) throw new Error('Invalid or duplicate cash reconciliation log')
    seen.add(key)
    const { from, to, value } = tokenInterface.parseLog(log).args
    const outgoing = from.toLowerCase() === vaultAddress
    const incoming = to.toLowerCase() === vaultAddress
    if (!outgoing && !incoming) continue
    if (log.transactionHash.toLowerCase() === receipt.hash.toLowerCase()) throw new Error('Proof transaction transferred destination vault cash')
    const delta = (incoming ? value : 0n) - (outgoing ? value : 0n)
    net += delta
    movements.push({ transactionHash: log.transactionHash, logIndex: log.index, from, to, amount: String(value), vaultDelta: String(delta) })
  }
  if (BigInt(before) + net !== BigInt(after)) throw new Error('Pinned-block vault cash does not reconcile with token transfers')
  return { method: 'PINNED_BLOCK_TOKEN_TRANSFER_RECONCILIATION', beforeBlock: receipt.blockNumber - 1,
    afterBlock: receipt.blockNumber, blockHash: receipt.blockHash, cashBefore: String(before), cashAfter: String(after),
    externalTransactionCashDelta: String(net), proofTransactionCashDelta: '0', externalTransfers: movements }
}

export async function auditProofReceipt(destination, token, manifest, receipt) {
  const events = assertProofOnlyReceipt(receipt, manifest)
  const [before, after, logs] = await Promise.all([
    token.balanceOf(manifest.contracts.LendingVaultV2, { blockTag: receipt.blockNumber - 1 }),
    token.balanceOf(manifest.contracts.LendingVaultV2, { blockTag: receipt.blockNumber }),
    destination.getLogs({ address: manifest.asset.address, topics: [id('Transfer(address,address,uint256)')], blockHash: receipt.blockHash }),
  ])
  const cash = reconcileVaultCashBlock(receipt, manifest, before, after, logs)
  if ((await destination.getBlock(receipt.blockNumber))?.hash !== receipt.blockHash) throw new Error('Proof block reorganized during financial audit')
  return { ...events, cash }
}

export async function canonicalConsumptionReceipt(destination, evidence, manifest, eventId, receipt = null) {
  if (!receipt) {
    const tip = await destination.getBlockNumber()
    const topic = evidence.interface.getEvent('SourceEventConsumed').topicHash
    const matches = []
    for (let fromBlock = manifest.deploymentBlock; fromBlock <= tip; fromBlock += 2000) {
      matches.push(...await destination.getLogs({ address: manifest.contracts.EvidenceBook,
        topics: [topic, eventId], fromBlock, toBlock: Math.min(fromBlock + 1999, tip) }))
    }
    if (matches.length !== 1) throw new Error('Expected one canonical consumed-source event')
    receipt = await destination.getTransactionReceipt(matches[0].transactionHash)
  }
  const confirmations = Math.max(2, manifest.finalityDepth ?? 6)
  if (receipt && await destination.getBlockNumber() - receipt.blockNumber + 1 < confirmations) {
    receipt = await destination.waitForTransaction(receipt.hash, confirmations, 180000)
  }
  if (!receipt || receipt.status !== 1) throw new Error('Native consumption not confirmed')
  const block = await destination.getBlock(receipt.blockNumber)
  if (block?.hash !== receipt.blockHash || !(await evidence.isConsumed(eventId, { blockTag: receipt.blockNumber }))) {
    throw new Error('Native consumption receipt is not canonical')
  }
  const events = receipt.logs.filter(log => log.address.toLowerCase() === manifest.contracts.EvidenceBook.toLowerCase())
    .map(log => { try { return evidence.interface.parseLog(log) } catch { return null } })
  const consumed = events.filter(event => event?.name === 'SourceEventConsumed' && event.args.id === eventId)
  if (consumed.length !== 1 || consumed[0].args.consumer.toLowerCase() !== manifest.contracts.ReceivableBook.toLowerCase() ||
      consumed[0].args.manifestHash !== manifest.manifestHash.replace('sha256:', '0x')) throw new Error('Bound native consumption event missing')
  return receipt
}

async function main(args) {
  if (args.includes('--help')) {
    console.log('node script/gpu/consume-native.mjs [--step recognizeObligation|assignObligation|correctObligation|settle|cancelPayout|reserveCheckpoint] [--proof FILE] [--facility NAME] [--checkpoint-proof FILE] [--settle-proof FILE] [--deployment FILE] [--proof-dir DIR] [--out FILE] [--preflight] [--broadcast --approval=user-20260914]')
    return
  }
  const value = (flag, fallback) => args.includes(flag) ? args[args.indexOf(flag) + 1] : fallback
  const publish = args.includes('--broadcast')
  if (publish && !args.includes('--approval=user-20260914')) throw new Error('Explicit testnet approval required')
  const manifest = JSON.parse(fs.readFileSync(value('--deployment', 'config/gpu/deployments/cc3-testnet.json'), 'utf8'))
  const environment = JSON.parse(fs.readFileSync(value('--environment', 'config/attestcoin/cc3-testnet.sepolia.release.json'), 'utf8'))
  if (manifest.chainId !== 102031 || manifest.executionProfile !== 'NATIVE_TESTNET' || !manifest.asset.testOnly ||
      manifest.requiredVerification !== 'ATTESTCOIN_NATIVE' || manifest.manifestHash !== environment.manifestHash) {
    throw new Error('Bound native TEST_ONLY destination required')
  }
  const { encodeSubmission } = require(path.resolve('offchain/attestcoin/dist/src/submission.js'))
  const destination = new JsonRpcProvider(manifest.rpcUrl)
  const source = new JsonRpcProvider(environment.source.rpcUrls[0])
  if (Number((await destination.getNetwork()).chainId) !== 102031 ||
      Number((await source.getNetwork()).chainId) !== 11155111) throw new Error('RPC chain mismatch')
  const verifier = new Contract(manifest.contracts.AttestcoinRevenueVerifier, abi('AttestcoinRevenueVerifier'), destination)
  if ((await verifier.manifestHash()) !== manifest.manifestHash.replace('sha256:', '0x') ||
      Number(await verifier.verificationMethod()) !== 0 || (await verifier.PRECOMPILE()).toLowerCase() !== '0x0000000000000000000000000000000000000fd2') {
    throw new Error('Official immutable native binding mismatch')
  }
  const evidence = new Contract(manifest.contracts.EvidenceBook, abi('EvidenceBook'), destination)
  const book = new Contract(manifest.contracts.ReceivableBook, abi('ReceivableBook'), destination)
  const ledger = new Contract(manifest.contracts.DebtLedger, abi('DebtLedger'), destination)
  const vault = new Contract(manifest.contracts.LendingVaultV2, abi('LendingVaultV2'), destination)
  const token = new Contract(manifest.asset.address, abi('GpuTestToken'), destination)
  const now = Number((await destination.getBlock('latest')).timestamp)
  const roles = JSON.parse(fs.readFileSync('keys/gpu-native-testnet.json', 'utf8'))
  const keeper = publish ? new Wallet(roles.keeper.privateKey, destination) : null
  const chosen = value('--step', 'all')
  if (chosen !== 'all' && !steps[chosen]) throw new Error('Unknown step')
  const report = { version: 1, executionProfile: 'NATIVE_TESTNET', verificationMethod: 'ATTESTCOIN_NATIVE',
    deploymentId: manifest.deploymentId, manifestHash: manifest.manifestHash, facilityId: REPORT_FACILITY,
    partnerRevenue: 'SIMULATED', partnerSourceBinding: 'UNCONFIGURED', controlProvenance: 'SIMULATED_NOT_PARTNER_E2',
    nativeAccepted: false, transactions: [] }
  // `all` is the original four-transition deployment set; corrections/chargebacks are always consumed one step at a time.
  const defaultSteps = ['recognizeObligation', 'assignObligation', 'settle', 'reserveCheckpoint']
  const selectedSteps = chosen === 'all' ? defaultSteps : [chosen]
  const persist = () => {
    report.nativeAccepted = report.transactions.length === selectedSteps.length && report.transactions.every(tx => tx.nativeAccepted)
    report.financialAuditPassed = report.transactions.length === selectedSteps.length && report.transactions.every(tx => tx.financialAuditStatus === 'PASSED')
    const out = value('--out', null)
    if (out) fs.writeFileSync(out, JSON.stringify(report, (_, v) => typeof v === 'bigint' ? String(v) : v, 2) + '\n')
  }
  const recordReceipt = async (row, receipt, status) => {
    row.nativeAccepted = true
    row.destinationTxHash = receipt.hash
    row.destinationBlock = receipt.blockNumber
    row.destinationBlockHash = receipt.blockHash
    row.status = 'NATIVE_CONSUMED_UNAUDITED'
    row.financialAuditStatus = 'PENDING'
    delete row.request
    persist()
    try {
      row.financialAudit = await auditProofReceipt(destination, token, manifest, receipt)
    } catch (error) {
      row.status = 'NATIVE_CONSUMED_AUDIT_FAILED'
      row.financialAuditStatus = 'FAILED'
      // Keep native receipt evidence even when an RPC/audit fails; do not mislabel consumption as failed.
      row.financialAuditError = error.code ? 'Pinned-block financial audit/RPC failed' : error.message
      persist()
      throw error
    }
    row.proofOnlyDebtAndCashUnchanged = true
    row.financialAuditStatus = 'PASSED'
    row.status = status
    persist()
  }
  for (const step of selectedSteps) {
    // A single selected step may read an explicit official proof artifact instead of the proof directory.
    const artifactPath = value('--proof', null) && chosen === step ? value('--proof', null)
      : step === 'reserveCheckpoint' ? value('--checkpoint-proof', null) : step === 'settle' ? value('--settle-proof', null) : null
    const artifact = JSON.parse(fs.readFileSync(artifactPath ?? path.join(value('--proof-dir', '.artifacts/native-testnet'), `${step}.proof.json`), 'utf8'))
    if (artifact.status !== 'PROOF_READY' || artifact.nativeAccepted !== false || artifact.manifestHash !== manifest.manifestHash ||
        artifact.executionProfile !== 'NATIVE_TESTNET' || artifact.verificationMethod !== 'ATTESTCOIN_NATIVE') throw new Error(`${step}: bound official proof is not ready`)
    const receipt = await source.getTransactionReceipt(artifact.txHash)
    if (!receipt || receipt.blockNumber !== Number(artifact.height)) throw new Error('Source receipt/height mismatch')
    const { topic0, claim, protection } = claimFromReceipt(step, receipt, manifest.source.emitter, now + 6 * 3600)
    const eventId = canonicalSourceEventId(manifest, artifact, claim.logOrdinal)
    const previouslyConsumed = await evidence.isConsumed(eventId)
    const row = { step, sourceTxHash: artifact.txHash, sourceEventId: eventId, logOrdinal: claim.logOrdinal,
      protection, protectionExpired: protection ? protection.protectedUntil <= now : null,
      nativeAccepted: false, status: previouslyConsumed ? 'CONSUMPTION_RECEIPT_PENDING' : 'PREPARED' }
    report.transactions.push(row)
    if (previouslyConsumed) {
      await recordReceipt(row, await canonicalConsumptionReceipt(destination, evidence, manifest, eventId), 'ALREADY_CONSUMED')
      continue
    }
    const encoded = encodeSubmission(environment, { artifact, plan: { purpose: 'receivables.ingest',
      providerId: PROVIDER, expectedEmitter: manifest.source.emitter, topic0s: [topic0], instructions: [claim] } })
    const request = { to: manifest.contracts.ReceivableBook, from: roles.keeper.address, data: encoded.calldata, value: '0x0' }
    row.request = request
    if (!publish && !args.includes('--preflight')) continue
    // Static preflight is NOT native acceptance. Only a successful mined consumption receipt sets that label.
    await destination.call(request)
    row.status = 'PREFLIGHT_OK_NOT_CONSUMED'
    if (!publish) continue
    const estimated = await destination.estimateGas(request)
    const transaction = await keeper.sendTransaction({ to: request.to, data: request.data, gasLimit: estimated * 5n, value: 0n })
    row.destinationTxHash = transaction.hash
    row.status = 'NATIVE_SUBMITTED'
    persist()
    const mined = await transaction.wait(Math.max(2, manifest.finalityDepth ?? 6), 180000)
    await recordReceipt(row, await canonicalConsumptionReceipt(destination, evidence, manifest, eventId, mined), 'NATIVE_CONSUMED')
  }
  report.nativeAccepted = report.transactions.length > 0 && report.transactions.every(tx => tx.nativeAccepted)
  const at = Number((await destination.getBlock('latest')).timestamp)
  report.eligibleUnpaid = String((await book.eligibleUnpaid(REPORT_FACILITY, 900, 0, 1000, at))[0])
  report.legalDebt = String(await ledger.legalDebtAt(REPORT_FACILITY, at))
  report.vaultNav = String(await vault.nav())
  const rendered = JSON.stringify(report, (_, v) => typeof v === 'bigint' ? String(v) : v, 2) + '\n'
  persist()
  console.log(rendered)
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main(process.argv.slice(2)).catch(error => {
    // RPC exceptions can carry credential URLs or request contexts. Never print those, keys, or complete errors.
    // A custom revert is decoded against the app ABIs so an operator sees the named refusal, not a selector.
    const data = error.data ?? error.info?.error?.data
    let revert = null
    if (typeof data === 'string' && data.length >= 10) {
      for (const name of ['ReceivableBook', 'EvidenceBook', 'AttestcoinRevenueVerifier', 'AccountRegistry']) {
        try { const parsed = new Interface(abi(name)).parseError(data); if (parsed) { revert = `${name}.${parsed.name}(${parsed.args.map(String).join(', ')})`; break } } catch { /* next */ }
      }
      revert ??= `selector ${data.slice(0, 10)}`
    }
    console.error(JSON.stringify({ status: 'FAILED', code: error.code ?? 'NATIVE_CONSUME_FAILED',
      reason: error.shortMessage ?? (error.code ? 'Native preflight/transaction failed' : error.message), ...(revert ? { revert } : {}) }))
    process.exitCode = 1
  })
}
