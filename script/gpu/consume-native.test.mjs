import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'
import { ACCOUNT, PROVIDER, claimFromReceipt, canonicalSourceEventId, assertProofOnlyReceipt,
  reconcileVaultCashBlock, auditProofReceipt, canonicalConsumptionReceipt } from './consume-native.mjs'
const require = createRequire(path.resolve('offchain/attestcoin/package.json'))
const { Interface, ZeroAddress, ZeroHash, id, AbiCoder, keccak256 } = require('ethers')
const sourceAbi = JSON.parse(fs.readFileSync('test/fixtures/gpu/abi/SourceEscrow.json', 'utf8'))
const iface = new Interface(sourceAbi)
const emitter = '0x0000000000000000000000000000000000000123'
const other = '0x0000000000000000000000000000000000000456'
function log(name, args, address = emitter) {
  const encoded = iface.encodeEventLog(iface.getEvent(name), args)
  return { address, data: encoded.data, topics: encoded.topics, index: 87 }
}
test('V2 recognition selects transaction ordinal, not block-global RPC index or legacy log', () => {
  const legacy = log('ObligationRecognized', [ACCOUNT, id('ref'), other, other, emitter, 100n, 1234, 1])
  const modern = log('ObligationRecognizedV2', [ACCOUNT, id('ref'), other, other, emitter, other, 100n, 1234, 1])
  const result = claimFromReceipt('recognizeObligation', { status: 1, logs: [legacy, modern] }, emitter, 4567, sourceAbi)
  assert.equal(result.claim.logOrdinal, 1)
  assert.equal(result.claim.data, modern.data)
  assert.equal(result.claim.accountKey, ACCOUNT)
  assert.equal(result.claim.validUntil, 4567)
  assert.equal(result.protection, null)
})
test('checkpoint original source protection is retained even when claim submission is newer', () => {
  const checkpoint = log('SourceCheckpointV2', [ACCOUNT, 2, 3, 75n, 25n, 1000, 1900])
  const result = claimFromReceipt('reserveCheckpoint', { status: 1, logs: [checkpoint] }, emitter, 9000, sourceAbi)
  assert.deepEqual(result.protection, { observedAt: 1000, protectedUntil: 1900, checkpointSeq: '2' })
  assert.equal(result.claim.topic2, ZeroHash)
  assert.equal(result.claim.topic3, ZeroHash)
})
test('wrong account, emitter, failed receipt, and ambiguous duplicate event are rejected', () => {
  const assignment = log('ObligationAssigned', [ACCOUNT, id('ref'), id('facility'), 2])
  const wrong = log('ObligationAssigned', [id('wrong-account'), id('ref'), id('facility'), 2])
  assert.throws(() => claimFromReceipt('assignObligation', { status: 0, logs: [assignment] }, emitter, 1, sourceAbi))
  assert.throws(() => claimFromReceipt('assignObligation', { status: 1, logs: [assignment] }, ZeroAddress, 1, sourceAbi))
  assert.throws(() => claimFromReceipt('assignObligation', { status: 1, logs: [wrong] }, emitter, 1, sourceAbi))
  assert.throws(() => claimFromReceipt('assignObligation', { status: 1, logs: [assignment, assignment] }, emitter, 1, sourceAbi))
})
test('source ID matches the on-chain environment/chain/height/index/ordinal canonical type widths', () => {
  const expected = keccak256(AbiCoder.defaultAbiCoder().encode(['bytes32', 'uint64', 'uint64', 'uint64', 'uint32'],
    [id('cc3-testnet'), 1, 11700014, 98, 1]))
  assert.equal(canonicalSourceEventId({ envId: 'cc3-testnet' }, { chainKey: 1, height: '11700014', txIndex: 98 }, 1), expected)
  assert.notEqual(canonicalSourceEventId({ envId: 'other' }, { chainKey: 1, height: '11700014', txIndex: 98 }, 1), expected)
  assert.equal(PROVIDER, id('mockdepin-testonly'))
})

const auditManifest = { contracts: { DebtLedger: emitter, LendingVaultV2: other }, asset: { address: '0x0000000000000000000000000000000000000789' } }
const transferInterface = new Interface(['event Transfer(address indexed from,address indexed to,uint256 value)'])
function transfer(from, to, amount, address = auditManifest.asset.address) {
  return { address, ...transferInterface.encodeEventLog(transferInterface.getEvent('Transfer'), [from, to, amount]) }
}
test('proof-only receipt accepts unrelated external activity without comparing latest balances', () => {
  assert.equal(assertProofOnlyReceipt({ status: 1, logs: [transfer(ZeroAddress, emitter, 100n)] }, auditManifest).vaultAssetTransfers, 0)
})
test('proof-only receipt rejects ledger/vault events and even net-zero vault cash roundtrips', () => {
  assert.throws(() => assertProofOnlyReceipt({ status: 1, logs: [{ address: emitter, topics: [], data: '0x' }] }, auditManifest), /financial-contract/)
  assert.throws(() => assertProofOnlyReceipt({ status: 1, logs: [{ address: other, topics: [], data: '0x' }] }, auditManifest), /financial-contract/)
  assert.throws(() => assertProofOnlyReceipt({ status: 1, logs: [transfer(emitter, other, 5n), transfer(other, emitter, 5n)] }, auditManifest), /vault cash/)
  assert.throws(() => assertProofOnlyReceipt({ status: 0, logs: [] }, auditManifest), /Successful/)
})
test('untrusted source token logs do not masquerade as destination vault cash', () => {
  assert.equal(assertProofOnlyReceipt({ status: 1, logs: [transfer(ZeroAddress, other, 10n, ZeroAddress)] }, auditManifest).vaultAssetTransfers, 0)
})

const proofReceipt = { status: 1, hash: id('proof-tx'), blockNumber: 101, blockHash: id('block-101'), logs: [] }
function blockTransfer(from, to, amount, overrides = {}) {
  return { ...transfer(from, to, amount), blockNumber: 101, blockHash: proofReceipt.blockHash,
    transactionHash: id('external-tx'), index: 0, ...overrides }
}
test('pinned proof-block cash accepts concurrent deposits and withdrawals from other transactions', () => {
  const logs = [blockTransfer(emitter, other, 1000n), blockTransfer(other, emitter, 200n, { index: 1 }),
    blockTransfer(emitter, other, 1n, { index: 2, transactionHash: id('browser-lp') })]
  const result = reconcileVaultCashBlock(proofReceipt, auditManifest, 50n, 851n, logs)
  assert.equal(result.externalTransactionCashDelta, '801')
  assert.equal(result.proofTransactionCashDelta, '0')
  assert.equal(result.externalTransfers.length, 3)
  assert.equal(result.beforeBlock, 100)
  assert.equal(result.afterBlock, 101)
})
test('cash reconciliation fails closed for omitted transfers, proof transfers, duplicate logs and reorgs', () => {
  const external = blockTransfer(emitter, other, 10n)
  assert.throws(() => reconcileVaultCashBlock(proofReceipt, auditManifest, 0n, 10n, []), /does not reconcile/)
  assert.throws(() => reconcileVaultCashBlock(proofReceipt, auditManifest, 0n, 10n,
    [{ ...external, transactionHash: proofReceipt.hash }]), /Proof transaction/)
  assert.throws(() => reconcileVaultCashBlock(proofReceipt, auditManifest, 0n, 20n, [external, external]), /duplicate/)
  assert.throws(() => reconcileVaultCashBlock(proofReceipt, auditManifest, 0n, 10n,
    [{ ...external, blockHash: id('reorg') }]), /canonical/)
  assert.throws(() => reconcileVaultCashBlock(proofReceipt, auditManifest, 0n, 10n,
    [{ ...external, removed: true }]), /canonical/)
})
test('financial audit reads only pinned predecessor/proof block and hash-bound transfer logs', async () => {
  const tags = []
  const token = { balanceOf: async (_, { blockTag }) => { tags.push(blockTag); return blockTag === 100 ? 50n : 60n } }
  const destination = {
    getLogs: async filter => { assert.equal(filter.blockHash, proofReceipt.blockHash); assert.equal(filter.fromBlock, undefined); return [blockTransfer(emitter, other, 10n)] },
    getBlock: async number => { assert.equal(number, 101); return { hash: proofReceipt.blockHash } },
  }
  const result = await auditProofReceipt(destination, token, auditManifest, proofReceipt)
  assert.deepEqual(tags, [100, 101])
  assert.equal(result.cash.cashAfter, '60')
})
test('already-consumed proof recovers and validates canonical receipt rather than silently skipping', async () => {
  const evidenceInterface = new Interface(JSON.parse(fs.readFileSync('test/fixtures/gpu/abi/EvidenceBook.json', 'utf8')))
  const eventId = id('source-event')
  const manifest = { ...auditManifest, deploymentBlock: 90, finalityDepth: 6, manifestHash: `sha256:${'ab'.repeat(32)}`,
    contracts: { ...auditManifest.contracts, EvidenceBook: ZeroAddress, ReceivableBook: emitter } }
  const event = { address: ZeroAddress, ...evidenceInterface.encodeEventLog(evidenceInterface.getEvent('SourceEventConsumed'),
    [eventId, id('economic-event'), emitter, 0, `0x${'ab'.repeat(32)}`]) }
  const receipt = { ...proofReceipt, logs: [event] }
  const destination = {
    getBlockNumber: async () => 110,
    getLogs: async filter => { assert.deepEqual(filter.topics, [evidenceInterface.getEvent('SourceEventConsumed').topicHash, eventId]); return [{ transactionHash: receipt.hash }] },
    getTransactionReceipt: async hash => { assert.equal(hash, receipt.hash); return receipt },
    getBlock: async number => { assert.equal(number, receipt.blockNumber); return { hash: receipt.blockHash } },
  }
  const evidence = { interface: evidenceInterface, isConsumed: async (sourceId, { blockTag }) => { assert.equal(sourceId, eventId); assert.equal(blockTag, 101); return true } }
  assert.equal((await canonicalConsumptionReceipt(destination, evidence, manifest, eventId)).hash, receipt.hash)
  await assert.rejects(canonicalConsumptionReceipt({ ...destination, getBlock: async () => ({ hash: id('reorg') }) }, evidence, manifest, eventId), /not canonical/)
  await assert.rejects(canonicalConsumptionReceipt({ ...destination, getLogs: async () => [] }, evidence, manifest, eventId), /one canonical/)
})
