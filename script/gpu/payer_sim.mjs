/**
 * Simulated payer personas on the TEST_ONLY Sepolia source escrow (QA tooling).
 *
 * A persona is a `MockDePINPayout` contract registered as a PAYER on the escrow. It imitates how a DePIN GPU
 * network settles an operator's receivables (epoch rewards, per-job invoices, adjustments, chargebacks) so the
 * whole native path — Sepolia log → official Attestcoin proof → Creditcoin consumption → borrowing base — can be
 * exercised with realistic event shapes. Personas are NOT partner integrations: `partnerRevenue=SIMULATED`,
 * faucet tokens only, and the issuer/owner is our own deployer key.
 *
 * Every mutation writes `.artifacts/native-testnet/<name>.json` ({txHash, blockNumber, ...}) so that
 * `native_proofs.mjs --refresh <name>` and `consume-native.mjs --step <step> --proof <name>.proof.json` can follow.
 * Private material is read only from ignored keys/. Output carries public identifiers only.
 */
import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'
const require = createRequire(path.resolve('apps/web/package.json'))
const { Wallet, JsonRpcProvider, Contract, ContractFactory, id, keccak256, ZeroHash, Interface } = require('ethers')

const args = process.argv.slice(2)
const command = args[0]
const flag = (name, fallback) => (args.includes(name) ? args[args.indexOf(name) + 1] : fallback)
const has = (name) => args.includes(name)
const personaFile = 'config/gpu/scenarios/payer-personas.json'
const outputDir = '.artifacts/native-testnet'
const APPROVAL = 'user-20260914'
const SOURCE_RPC = 'https://ethereum-sepolia-rpc.publicnode.com'
const MAX_OBLIGATION = 100_000_000n // 100 source tUSD
const MAX_PAYOUT = 50_000_000n // 50 source tUSD

const personas = JSON.parse(fs.readFileSync(personaFile, 'utf8'))
const environment = JSON.parse(fs.readFileSync('config/attestcoin/cc3-testnet.sepolia.release.json', 'utf8'))
const abi = (name) => JSON.parse(fs.readFileSync(`test/fixtures/gpu/abi/${name}.json`, 'utf8'))
// The persona payer is a mock; its ABI comes from the build artifact rather than the audited fixture set.
const payerArtifact = () => JSON.parse(fs.readFileSync('out/MockDePINPayout.sol/MockDePINPayout.json', 'utf8'))
const rootKeys = [...new Set(fs.readFileSync('keys/PRIVATE_KEYS.txt', 'utf8').match(/(?:0x)?[a-fA-F0-9]{64}/g) || [])]
if (rootKeys.length !== 1) throw new Error('Expected one unambiguous existing testnet deployment key')
const deployer = new Wallet(rootKeys[0].startsWith('0x') ? rootKeys[0] : `0x${rootKeys[0]}`)
const accountKey = id(`${personas.providerId}:${personas.accountName}`)
const escrowAddress = environment.source.emitters[0].address
const tokenAddress = environment.source.tokens[0].address
const CORRECTION_REASONS = { DISPUTE: 0, REFUND: 1, SLA: 2, CANCEL: 3, OTHER: 4 }

function requireBroadcast() {
  if (!has('--broadcast') || !has(`--approval=${APPROVAL}`)) {
    throw new Error('Explicit testnet broadcast and approval reference required')
  }
}
function record(name, value) {
  if (!/^[a-z0-9-]+$/.test(name)) throw new Error('Record names are lowercase kebab-case (native_proofs.mjs --refresh)')
  fs.mkdirSync(outputDir, { recursive: true })
  fs.writeFileSync(`${outputDir}/${name}.json`, JSON.stringify(value, null, 2) + '\n')
  console.log(JSON.stringify({ record: name, ...value }))
}
function persona(name) {
  const p = personas.personas[name]
  if (!p) throw new Error(`Unknown persona ${name}; use ${Object.keys(personas.personas).join(', ')}`)
  return { name, ...p, deployed: personas.deployed[name] ?? null }
}
function savePersonas() {
  fs.writeFileSync(personaFile, JSON.stringify(personas, null, 2) + '\n')
}
async function connect() {
  const provider = new JsonRpcProvider(SOURCE_RPC)
  if (Number((await provider.getNetwork()).chainId) !== 11155111) throw new Error('Source chain mismatch')
  const signer = deployer.connect(provider)
  const escrow = new Contract(escrowAddress, abi('SourceEscrow'), signer)
  const token = new Contract(tokenAddress, abi('GpuTestToken'), signer)
  return { provider, signer, escrow, token }
}
async function send(promise, label) {
  const tx = await promise
  const receipt = await tx.wait()
  if (receipt.status !== 1) throw new Error(`${label} failed`)
  return { tx, receipt }
}
function revertName(error, iface) {
  const data = error?.data ?? error?.info?.error?.data ?? error?.error?.data
  if (typeof data === 'string' && data.length >= 10) {
    try {
      const parsed = iface.parseError(data)
      if (parsed) return parsed.name
    } catch {
      /* not one of ours */
    }
    return `selector:${data.slice(0, 10)}`
  }
  return error?.shortMessage ?? error?.code ?? 'UNKNOWN'
}

if (command === 'status') {
  const { provider, escrow, token } = await connect()
  const summary = { escrow: escrowAddress, token: tokenAddress, accountKey, personas: {} }
  summary.account = {
    latestRevision: String(await escrow.accountLatestRevision(accountKey)),
    openAmount: String(await escrow.accountOpenAmount(accountKey)),
    paidCumulative: String(await escrow.accountPaidCumulative(accountKey)),
    checkpointSeq: String(await escrow.checkpointSeq(accountKey)),
    protectedUntil: String(await escrow.protectedUntil(accountKey)),
    settlementSeq: String(await escrow.settlementSeq()),
    now: (await provider.getBlock('latest')).timestamp,
  }
  for (const [name, p] of Object.entries(personas.deployed)) {
    summary.personas[name] = {
      payer: p.payer,
      registered: await escrow.isRegisteredPayer(p.payer),
      balance: String(await token.balanceOf(p.payer)),
    }
  }
  console.log(JSON.stringify(summary, null, 2))
} else if (command === 'payers') {
  // Deploy each persona's payer contract once, register it as a PAYER and fund it with faucet tokens.
  requireBroadcast()
  const { signer, escrow, token } = await connect()
  const artifact = payerArtifact()
  const fund = BigInt(flag('--fund', '200000000')) // 200 source tUSD per persona
  for (const name of Object.keys(personas.personas)) {
    let deployed = personas.deployed[name]
    if (!deployed) {
      const factory = new ContractFactory(artifact.abi, artifact.bytecode.object, signer)
      const contract = await factory.deploy(escrowAddress, deployer.address)
      const receipt = await contract.deploymentTransaction().wait()
      deployed = { payer: (await contract.getAddress()).toLowerCase(), deployTxHash: receipt.hash, deployBlock: receipt.blockNumber, chainId: 11155111 }
      personas.deployed[name] = deployed
      savePersonas()
      console.log(JSON.stringify({ persona: name, deployed }))
    }
    if (!(await escrow.isRegisteredPayer(deployed.payer))) {
      const { tx } = await send(escrow.setPayer(deployed.payer, true), `setPayer ${name}`)
      deployed.registerTxHash = tx.hash
      savePersonas()
      console.log(JSON.stringify({ persona: name, registered: tx.hash }))
    }
    const balance = await token.balanceOf(deployed.payer)
    if (balance < fund) {
      const { tx } = await send(token.transfer(deployed.payer, fund - balance), `fund ${name}`)
      deployed.fundTxHash = tx.hash
      savePersonas()
      console.log(JSON.stringify({ persona: name, funded: tx.hash, amount: String(fund - balance) }))
    }
  }
  console.log(JSON.stringify({ personas: personas.deployed }))
} else if (command === 'recognize') {
  // Issuer recognises a persona obligation (an epoch reward or a job invoice) payable by the persona's payer.
  requireBroadcast()
  const p = persona(flag('--persona'))
  if (!p.deployed) throw new Error('Run payers first')
  const ref = flag('--ref')
  const name = flag('--name')
  const amount = BigInt(flag('--amount', '10000000'))
  if (!ref || !name) throw new Error('--ref and --name required')
  if (amount <= 0n || amount > MAX_OBLIGATION) throw new Error('Persona obligations are limited to 100 source tUSD')
  const { provider, escrow } = await connect()
  const obligationRef = id(`${p.obligationPrefix}:${ref}`)
  const dueAt = (await provider.getBlock('latest')).timestamp + Number(flag('--due-seconds', '86400'))
  const { tx, receipt } = await send(
    escrow.recognizeObligation(accountKey, obligationRef, p.deployed.payer, tokenAddress, amount, dueAt),
    'recognizeObligation',
  )
  record(name, { step: 'recognizeObligation', persona: p.name, txHash: tx.hash, blockNumber: receipt.blockNumber, obligationRef, ref, amount: String(amount), dueAt, payer: p.deployed.payer })
} else if (command === 'assign') {
  requireBroadcast()
  const p = persona(flag('--persona'))
  const ref = flag('--ref')
  const name = flag('--name')
  const facilityName = flag('--facility')
  if (!ref || !name || !facilityName) throw new Error('--ref, --facility and --name required')
  const { escrow } = await connect()
  const obligationRef = id(`${p.obligationPrefix}:${ref}`)
  const facilityKey = keccak256(id(facilityName))
  const { tx, receipt } = await send(escrow.assignObligation(accountKey, obligationRef, facilityKey), 'assignObligation')
  record(name, { step: 'assignObligation', persona: p.name, txHash: tx.hash, blockNumber: receipt.blockNumber, obligationRef, ref, facilityKey, facilityName })
} else if (command === 'payout') {
  // The persona's payer contract pays through the real token path (approve + settle); the escrow measures the delta.
  requireBroadcast()
  const p = persona(flag('--persona'))
  if (!p.deployed) throw new Error('Run payers first')
  const ref = flag('--ref', null)
  const name = flag('--name')
  const amount = BigInt(flag('--amount', '1000000'))
  if (!name) throw new Error('--name required')
  if (amount <= 0n || amount > MAX_PAYOUT) throw new Error('Persona payouts are limited to 50 source tUSD')
  const { signer, escrow } = await connect()
  const payer = new Contract(p.deployed.payer, payerArtifact().abi, signer)
  const obligationRef = ref ? id(`${p.obligationPrefix}:${ref}`) : ZeroHash
  const settlementId = id(`${p.name}:settlement:${flag('--settlement', String(Date.now()))}`)
  const { tx, receipt } = await send(payer.payout(accountKey, obligationRef, tokenAddress, amount, settlementId), 'payout')
  const iface = new Interface(abi('SourceEscrow'))
  const log = receipt.logs.map((l) => { try { return iface.parseLog(l) } catch { return null } }).find((e) => e?.name === 'PayoutReceived')
  record(name, { step: 'settle', persona: p.name, txHash: tx.hash, blockNumber: receipt.blockNumber, obligationRef, ref, amount: String(amount), settlementSeq: String(log.args.settlementSeq), measured: String(log.args.amount), payer: p.deployed.payer })
} else if (command === 'correct') {
  // Signed adjustment by the issuer: SLA/QoS haircut, dispute, or CANCEL (must zero the open amount).
  requireBroadcast()
  const p = persona(flag('--persona'))
  const ref = flag('--ref')
  const name = flag('--name')
  const delta = BigInt(flag('--delta', '0'))
  const reason = flag('--reason', 'SLA')
  if (!ref || !name || delta === 0n) throw new Error('--ref, --name and a non-zero --delta required')
  if (!(reason in CORRECTION_REASONS)) throw new Error(`reason must be one of ${Object.keys(CORRECTION_REASONS).join(', ')}`)
  if (delta > MAX_OBLIGATION || -delta > MAX_OBLIGATION) throw new Error('Corrections are limited to 100 source tUSD')
  const { escrow } = await connect()
  const obligationRef = id(`${p.obligationPrefix}:${ref}`)
  const { tx, receipt } = await send(escrow.correctObligation(accountKey, obligationRef, delta, CORRECTION_REASONS[reason]), 'correctObligation')
  record(name, { step: 'correctObligation', persona: p.name, txHash: tx.hash, blockNumber: receipt.blockNumber, obligationRef, ref, delta: String(delta), reason })
} else if (command === 'cancel-payout') {
  // Chargeback: the issuer reverses a prior settlement; tokens actually return to the persona payer.
  requireBroadcast()
  const seq = BigInt(flag('--seq', '0'))
  const name = flag('--name')
  if (!seq || !name) throw new Error('--seq and --name required')
  const { escrow } = await connect()
  const payout = await escrow.payout(seq)
  if (payout.accountKey !== accountKey) throw new Error('Settlement belongs to another account')
  const { tx, receipt } = await send(escrow.cancelPayout(seq), 'cancelPayout')
  record(name, { step: 'cancelPayout', txHash: tx.hash, blockNumber: receipt.blockNumber, settlementSeq: String(seq), obligationRef: payout.obligationRef, amount: String(payout.amount), payer: payout.payer.toLowerCase() })
} else if (command === 'checkpoint') {
  requireBroadcast()
  const name = flag('--name', 'checkpoint-refresh')
  const window = Number(flag('--window', '850'))
  const { provider, escrow } = await connect()
  const until = (await provider.getBlock('latest')).timestamp + window
  const { tx, receipt } = await send(escrow.reserveCheckpoint(accountKey, until), 'reserveCheckpoint')
  record(name, { step: 'reserveCheckpoint', txHash: tx.hash, blockNumber: receipt.blockNumber, protectedUntil: until })
} else if (command === 'unattributed') {
  // Not a payout: a direct deposit by an unregistered address lands in the unattributed bucket.
  requireBroadcast()
  const name = flag('--name')
  const amount = BigInt(flag('--amount', '1000000'))
  if (!name) throw new Error('--name required')
  if (amount <= 0n || amount > MAX_PAYOUT) throw new Error('Deposits are limited to 50 source tUSD')
  const { escrow, token } = await connect()
  await send(token.approve(escrowAddress, amount), 'approve')
  const { tx, receipt } = await send(escrow.depositUnattributed(tokenAddress, amount), 'depositUnattributed')
  const iface = new Interface(abi('SourceEscrow'))
  const log = receipt.logs.map((l) => { try { return iface.parseLog(l) } catch { return null } }).find((e) => e?.name === 'UnattributedDeposit')
  record(name, { step: 'depositUnattributed', txHash: tx.hash, blockNumber: receipt.blockNumber, amount: String(amount), depositSeq: String(log.args.depositSeq), origin: Number(log.args.origin), unattributedBalance: String(await escrow.unattributedBalance(tokenAddress)) })
} else if (command === 'negative') {
  // Static-call misuse checks; nothing is broadcast. Each expectation is a named revert of the escrow.
  const p = persona(flag('--persona'))
  if (!p.deployed) throw new Error('Run payers first')
  const { provider, escrow, token } = await connect()
  const iface = new Interface(abi('SourceEscrow'))
  const stranger = Wallet.createRandom().connect(provider)
  const results = {}
  const expect = async (label, expected, fn) => {
    try {
      await fn()
      results[label] = { ok: false, expected, observed: 'NO_REVERT' }
    } catch (error) {
      const observed = revertName(error, iface)
      results[label] = { ok: observed === expected, expected, observed }
    }
  }
  const ref = flag('--ref', 'never-recognised')
  const obligationRef = id(`${p.obligationPrefix}:${ref}`)
  const strangerEscrow = escrow.connect(stranger)
  await expect('unregistered payer cannot settle', 'NotRegisteredPayer', () =>
    strangerEscrow.settle.staticCall(accountKey, ZeroHash, tokenAddress, 1_000_000n, id('x'), { from: stranger.address }))
  await expect('stranger cannot recognise obligations', 'NotIssuer', () =>
    strangerEscrow.recognizeObligation.staticCall(accountKey, obligationRef, p.deployed.payer, tokenAddress, 1_000_000n, 4_000_000_000n, { from: stranger.address }))
  await expect('stranger cannot cancel a settlement', 'NotIssuer', () =>
    strangerEscrow.cancelPayout.staticCall(1n, { from: stranger.address }))
  await expect('persona payer cannot pay an unknown obligation', 'ObligationNotOpen', () => {
    const payer = new Contract(p.deployed.payer, payerArtifact().abi, deployer.connect(provider))
    return payer.payout.staticCall(accountKey, id(`${p.obligationPrefix}:does-not-exist`), tokenAddress, 1_000_000n, id(`neg:${Date.now()}`))
  })
  await expect('unknown source account is rejected', 'AccountUnknown', () =>
    escrow.recognizeObligation.staticCall(id('mockdepin-testonly:not-registered'), obligationRef, p.deployed.payer, tokenAddress, 1_000_000n, 4_000_000_000n))
  await expect('non-admitted token is rejected', 'TokenNotAdmitted', () =>
    escrow.recognizeObligation.staticCall(accountKey, obligationRef, p.deployed.payer, stranger.address, 1_000_000n, 4_000_000_000n))
  const openRef = flag('--open-ref', null)
  if (openRef) {
    const open = await escrow.obligation(accountKey, id(`${p.obligationPrefix}:${openRef}`))
    const remaining = open.net - open.paid
    await expect('overpayment of an open obligation is rejected', 'Overpayment', () => {
      const payer = new Contract(p.deployed.payer, payerArtifact().abi, deployer.connect(provider))
      return payer.payout.staticCall(accountKey, id(`${p.obligationPrefix}:${openRef}`), tokenAddress, remaining + 1n, id(`neg2:${Date.now()}`))
    })
    await expect('cancel correction that leaves an open amount is rejected', 'CancelMustZeroOpenAmount', () =>
      escrow.correctObligation.staticCall(accountKey, id(`${p.obligationPrefix}:${openRef}`), -1n, CORRECTION_REASONS.CANCEL))
  }
  const protectedUntil = Number(await escrow.protectedUntil(accountKey))
  const now = (await provider.getBlock('latest')).timestamp
  if (protectedUntil > now) {
    await expect('reserved account rejects source mutations until the window closes', 'AccountReserved', () =>
      escrow.recognizeObligation.staticCall(accountKey, id(`${p.obligationPrefix}:while-reserved`), p.deployed.payer, tokenAddress, 1_000_000n, 4_000_000_000n))
  }
  const name = flag('--name', null)
  const summary = { persona: p.name, checks: results, allOk: Object.values(results).every((r) => r.ok), token: await token.getAddress() }
  if (name) record(name, summary)
  else console.log(JSON.stringify(summary, null, 2))
  process.exitCode = summary.allOk ? 0 : 1
} else {
  throw new Error('Use status | payers | recognize | assign | payout | correct | cancel-payout | checkpoint | unattributed | negative')
}
