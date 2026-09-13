/** Package public, receipt-verified release evidence for repeatable container bootstrap. No keys. */
import fs from 'node:fs'
import path from 'node:path'
import { createHash } from 'node:crypto'
import { createRequire } from 'node:module'
const require = createRequire(path.resolve('apps/web/package.json'))
const { JsonRpcProvider } = require('ethers')
const source = process.argv[2] || '.artifacts/native-testnet'
const read = file => JSON.parse(fs.readFileSync(file, 'utf8'))
const manifestPath = 'config/gpu/deployments/cc3-testnet.json'
const manifest = read(manifestPath)
const audit = read(`${source}/consumption-audited.json`)
if (manifest.chainId !== 102031 || !manifest.asset.testOnly || !audit.nativeAccepted ||
    !audit.financialAuditPassed || audit.deploymentId !== manifest.deploymentId ||
    audit.manifestHash !== manifest.manifestHash || audit.transactions.length !== 4) {
  throw Error('Complete audited native TEST_ONLY release required')
}
const provider = new JsonRpcProvider(manifest.rpcUrl)
if (Number((await provider.getNetwork()).chainId) !== manifest.chainId) throw Error('Chain mismatch')
const head = await provider.getBlockNumber()
const directory = 'config/gpu/evidence/native-20260914'
const files = new Map()
const verify = async (transition, artifactPath, expectedAudit = audit) => {
  if (expectedAudit.deploymentId !== manifest.deploymentId || expectedAudit.manifestHash !== manifest.manifestHash ||
      !expectedAudit.nativeAccepted || !expectedAudit.financialAuditPassed) throw Error('Audit binding mismatch')
  const receipt = await provider.getTransactionReceipt(transition.destinationTxHash)
  if (!transition.nativeAccepted || !transition.proofOnlyDebtAndCashUnchanged ||
      transition.financialAuditStatus !== 'PASSED' || receipt?.status !== 1 ||
      receipt.blockHash !== transition.destinationBlockHash ||
      head - receipt.blockNumber < manifest.finalityDepth ||
      receipt.to.toLowerCase() !== manifest.contracts.ReceivableBook.toLowerCase()) {
    throw Error(`Unconfirmed consumption: ${transition.step}`)
  }
  const proof = read(artifactPath)
  if (proof.status !== 'PROOF_READY' || proof.txHash !== transition.sourceTxHash ||
      proof.manifestHash !== manifest.manifestHash) throw Error('Official artifact binding mismatch')
  return proof
}
for (const transition of audit.transactions) {
  files.set(`${transition.step}.proof.json`, await verify(transition, `${source}/${transition.step}.proof.json`))
}
if (process.argv[3]) {
  const refresh = read(`${process.argv[3]}/checkpoint-consumption.json`)
  if (refresh.transactions.length !== 1 || refresh.transactions[0].step !== 'reserveCheckpoint') throw Error('One refresh checkpoint required')
  files.set('checkpoint-refresh.proof.json', await verify(refresh.transactions[0],
    `${process.argv[3]}/checkpoint-refresh.proof.json`, refresh))
  files.set('checkpoint-consumption.json', refresh)
}
const setup = read('broadcast/SetupGpuFacility.s.sol/102031/run-latest.json')
// The ABI is authoritative if the event signature changes; never infer a bootstrap locator.
const abi = read('test/fixtures/gpu/abi/DebtLedger.json')
const { Interface } = require('ethers')
const topic = new Interface(abi).getEvent('FacilityOpened').topicHash
const located = setup.receipts.filter(receipt => receipt.logs.some(log =>
  log.address.toLowerCase() === manifest.contracts.DebtLedger.toLowerCase() && log.topics[0] === topic))
if (located.length !== 1) throw Error('Expected one facility opening receipt')
const actual = await provider.getTransactionReceipt(located[0].transactionHash)
if (actual?.status !== 1 || actual.blockHash !== located[0].blockHash) throw Error('Opening receipt not canonical')
files.set('setup-receipt.json', {receipts: located})
files.set('consumption-audited.json', audit)
fs.mkdirSync(directory, {recursive:true})
const hashes = {}
for (const [name, value] of files) {
  const body = JSON.stringify(value, null, 2) + '\n'
  fs.writeFileSync(`${directory}/${name}`, body)
  hashes[name] = `sha256:${createHash('sha256').update(body).digest('hex')}`
}
fs.writeFileSync(`${directory}/index.json`, JSON.stringify({version:1, deploymentId:manifest.deploymentId,
  manifestHash:manifest.manifestHash, nativeStatus:'CONSUMED', partnerRevenue:'SIMULATED',
  partnerSourceBinding:'UNCONFIGURED', files:hashes}, null, 2) + '\n')
manifest.nativeStatus = 'CONSUMED'
manifest.nativeEvidence = `${directory}/index.json`
fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + '\n')
console.log(JSON.stringify({directory, artifacts:files.size, nativeStatus:'CONSUMED'}))
