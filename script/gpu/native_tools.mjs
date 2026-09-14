/** Explicit testnet deployment tooling. Private material is generated/read only in ignored keys/. */
import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'
import { spawnSync } from 'node:child_process'
const require = createRequire(path.resolve('apps/web/package.json'))
const { Wallet, JsonRpcProvider, Contract, keccak256, id } = require('ethers')
const roleFile = 'keys/gpu-native-testnet.json'
const args = process.argv.slice(2)
const command = args[0]
const rootKeys = [...new Set(fs.readFileSync('keys/PRIVATE_KEYS.txt', 'utf8').match(/(?:0x)?[a-fA-F0-9]{64}/g) || [])]
if (rootKeys.length !== 1) throw new Error('Expected one unambiguous existing testnet deployment key')
const deployer = new Wallet(rootKeys[0].startsWith('0x') ? rootKeys[0] : `0x${rootKeys[0]}`)
if (!fs.existsSync(roleFile)) {
  if (command !== 'wallets') throw new Error('Run wallets to prepare isolated test roles first')
  const roles = Object.fromEntries(['underwriter', 'treasury', 'borrower', 'lp', 'keeper'].map(name => {
    const wallet = Wallet.createRandom()
    return [name, { address: wallet.address, privateKey: wallet.privateKey }]
  }))
  fs.writeFileSync(roleFile, JSON.stringify(roles, null, 2) + '\n', { mode: 0o600, flag: 'wx' })
}
const roles = JSON.parse(fs.readFileSync(roleFile, 'utf8'))

async function executeRpcPlan(file, provider) {
  const folder = `broadcast/${file}.s.sol/102031`
  const plan = JSON.parse(fs.readFileSync(`${folder}/dry-run/run-latest.json`, 'utf8'))
  const signers = new Map([deployer, ...Object.values(roles).map(role => new Wallet(role.privateKey))]
    .map(wallet => [wallet.address.toLowerCase(), wallet.connect(provider)]))
  const output = {...plan, receipts: [], pending: [], transactions: [], planTransactionCount: plan.transactions.length, complete: false}
  const record = () => {
    const value = JSON.stringify(output, (_, value) => typeof value === 'bigint' ? `0x${value.toString(16)}` : value, 2) + '\n'
    fs.writeFileSync(`${folder}/run-latest.json`, value)
    fs.writeFileSync(`${folder}/run-rpc-estimated.json`, value)
  }
  for (const planned of plan.transactions) {
    const raw = planned.transaction
    const signer = signers.get(raw.from.toLowerCase())
    if (!signer) throw new Error('Unapproved signer in testnet plan')
    const nonce = Number(raw.nonce)
    if (await provider.getTransactionCount(signer.address, 'pending') !== nonce) throw new Error('Nonce changed; refuse stale plan')
    const tx = {from: signer.address, to: raw.to || undefined, data: raw.input || raw.data,
      value: BigInt(raw.value || 0), nonce}
    const estimated = await provider.estimateGas(tx)
    const sent = await signer.sendTransaction({...tx, gasLimit: estimated * 3n / 2n})
    output.transactions.push({...planned, hash: sent.hash, transaction: {...raw, gas: `0x${(estimated*3n/2n).toString(16)}`}})
    output.pending = [sent.hash]
    record()
    await sent.wait()
    // A load-balanced public RPC can answer null for a receipt its peer just mined; re-ask before declaring failure.
    let receipt = null
    for (let attempt = 0; attempt < 10 && !receipt; attempt++) {
      receipt = await provider.send('eth_getTransactionReceipt', [sent.hash]).catch(() => null)
      if (!receipt) await new Promise(resolve => setTimeout(resolve, 3000))
    }
    if (!receipt || Number(receipt.status) !== 1) throw new Error(`Execution halted after failed transaction ${sent.hash}`)
    output.pending = []
    output.receipts.push(receipt)
    record()
    console.log(JSON.stringify({step:output.receipts.length,total:plan.transactions.length,contract:planned.contractName,
      function:planned.function || 'CREATE',gasEstimate:estimated.toString(),txHash:sent.hash}))
  }
  output.complete = true
  record()
  console.log('All transactions confirmed using live RPC gas estimation')
}

if (command === 'wallets') {
  console.log(JSON.stringify({ deployer: deployer.address, ...Object.fromEntries(Object.entries(roles).map(([k,v]) => [k,v.address])) }, null, 2))
} else if (command === 'source-manifest') {
  const { computeManifestHash, validateManifest } = require(path.resolve('offchain/attestcoin/dist/src/manifest.js'))
  const run = JSON.parse(fs.readFileSync('broadcast/DeployGpuSource.s.sol/11155111/run-latest.json', 'utf8'))
  const source = run.transactions.find(t => t.contractName === 'SourceEscrow' && t.transactionType === 'CREATE')
  const token = run.transactions.find(t => t.contractName === 'GpuTestToken' && t.transactionType === 'CREATE')
  if (!source || !token) throw new Error('Source deployment is incomplete')
  const receipt = run.receipts.find(r => r.transactionHash.toLowerCase() === source.hash.toLowerCase())
  const manifest = JSON.parse(fs.readFileSync('config/attestcoin/cc3-testnet.sepolia.json', 'utf8'))
  manifest.manifestId = 'cc3-testnet.sepolia.release-20260914'
  manifest.source.emitters = [{ address: source.contractAddress, kind: 'TEST_ONLY_SOURCE_ESCROW',
    deploymentBlock: Number(receipt.blockNumber), note: 'Real Sepolia transactions; partnerRevenue=SIMULATED, partnerSourceBinding=UNCONFIGURED' }]
  manifest.source.tokens = [{ address: token.contractAddress, symbol: 'tUSD', decimals: 6 }]
  manifest.notes.push('Dedicated source technical integration authorized 2026-09-14. No actual partner or production financial approval.')
  manifest.manifestHash = computeManifestHash(manifest)
  const validation = validateManifest(manifest)
  if (!validation.ok) throw new Error(validation.errors.join('; '))
  const target = 'config/attestcoin/cc3-testnet.sepolia.release.json'
  fs.writeFileSync(target, JSON.stringify(manifest, null, 2) + '\n')
  console.log(JSON.stringify({ path: target, manifestHash: manifest.manifestHash, source: source.contractAddress, token: token.contractAddress }))
} else if (command === 'deployment-manifest') {
  const run = JSON.parse(fs.readFileSync('broadcast/DeployGpu.s.sol/102031/run-latest.json', 'utf8'))
  const planned = JSON.parse(fs.readFileSync('broadcast/DeployGpu.s.sol/102031/dry-run/run-latest.json', 'utf8'))
  if (run.pending.length || run.transactions.length !== planned.transactions.length ||
      run.transactions.length !== run.receipts.length || run.receipts.some(r => Number(r.status) !== 1)) {
    throw new Error('Destination deployment is not fully confirmed')
  }
  const rpcUrl = 'https://rpc.cc3-testnet.creditcoin.network'
  const provider = new JsonRpcProvider(rpcUrl)
  if (Number((await provider.getNetwork()).chainId) !== 102031) throw new Error('Chain mismatch')
  const contracts = {}
  for (const t of run.transactions.filter(t => t.transactionType === 'CREATE')) {
    const name = t.contractName === 'GovernanceTimelock' && contracts.GovernanceTimelock ? 'TreasuryTimelock' : t.contractName
    contracts[name] = t.contractAddress.toLowerCase()
  }
  const codeHashes = {}
  for (const [name, address] of Object.entries(contracts)) {
    const code = await provider.getCode(address)
    if (code === '0x') throw new Error(`Missing deployed code: ${name}`)
    codeHashes[name] = keccak256(code)
  }
  const environment = JSON.parse(fs.readFileSync('config/attestcoin/cc3-testnet.sepolia.release.json', 'utf8'))
  const verifier = new Contract(contracts.AttestcoinRevenueVerifier, ['function manifestHash() view returns(bytes32)', 'function verificationMethod() view returns(uint8)'], provider)
  if ((await verifier.manifestHash()) !== environment.manifestHash.replace('sha256:', '0x') || Number(await verifier.verificationMethod()) !== 0) {
    throw new Error('Official verifier deployment binding mismatch')
  }
  const target = 'config/gpu/deployments/cc3-testnet.json'
  const old = fs.existsSync(target) ? JSON.parse(fs.readFileSync(target, 'utf8')) : null
  const id = old?.contracts?.LendingVaultV2 === contracts.LendingVaultV2 ? old.deploymentId : '01K54G0000' + Array.from({length:16},()=> '0123456789ABCDEFGHJKMNPQRSTVWXYZ'[Math.floor(Math.random()*32)]).join('')
  const manifest = { schemaVersion: '1.0', deploymentId: id, executionProfile: 'NATIVE_TESTNET', envId: 'cc3-testnet',
    chainId: 102031, manifestHash: environment.manifestHash, requiredVerification: 'ATTESTCOIN_NATIVE',
    deploymentBlock: Math.min(...run.receipts.map(r => Number(r.blockNumber))), finalityDepth: 6,
    rpcUrl, explorerUrl: 'https://creditcoin-testnet.blockscout.com', contracts, contractCodeHashes: codeHashes,
    asset: {chainId: 102031, address: contracts.GpuTestToken, decimals: 6, symbol: 'tUSD', testOnly: true},
    nativeStatus: 'NOT_SUBMITTED', partnerRevenue: 'SIMULATED', partnerSourceBinding: 'UNCONFIGURED',
    source: {chainId:11155111, emitter:environment.source.emitters[0].address, token:environment.source.tokens[0].address},
    deploymentEvidence: {approval:'user-20260914', transactionCount:run.receipts.length} }
  fs.mkdirSync(path.dirname(target), {recursive:true})
  fs.writeFileSync(target, JSON.stringify(manifest,null,2)+'\n')
  console.log(JSON.stringify({path:target,deploymentId:id,contracts:Object.keys(contracts).length,block:manifest.deploymentBlock}))
} else if (command === 'checkpoint') {
  if (!args.includes('--broadcast') || !args.includes('--approval=user-20260914')) throw new Error('Explicit testnet broadcast and approval reference required')
  const environment = JSON.parse(fs.readFileSync('config/attestcoin/cc3-testnet.sepolia.release.json', 'utf8'))
  const provider = new JsonRpcProvider('https://ethereum-sepolia-rpc.publicnode.com')
  if (Number((await provider.getNetwork()).chainId) !== 11155111) throw new Error('Source chain mismatch')
  const source = new Contract(environment.source.emitters[0].address,
    JSON.parse(fs.readFileSync('test/fixtures/gpu/abi/SourceEscrow.json', 'utf8')), deployer.connect(provider))
  const until = (await provider.getBlock('latest')).timestamp + 850
  const account = id('mockdepin-testonly:native-integration')
  const estimate = await source.reserveCheckpoint.estimateGas(account, until)
  const tx = await source.reserveCheckpoint(account, until, {gasLimit: estimate * 3n / 2n})
  const receipt = await tx.wait()
  if (receipt.status !== 1) throw new Error('Source checkpoint failed')
  const directory = '.artifacts/native-testnet'
  fs.mkdirSync(directory, {recursive:true})
  fs.writeFileSync(`${directory}/checkpoint-refresh.json`, JSON.stringify({txHash:tx.hash,blockNumber:receipt.blockNumber,protectedUntil:until},null,2)+'\n')
  console.log(JSON.stringify({sourceCheckpoint:tx.hash,block:receipt.blockNumber,protectedUntil:until}))
} else if (command === 'settle') {
  // TEST_ONLY source payout by the registered payer. Renews receivable evidence once proven and consumed.
  if (!args.includes('--broadcast') || !args.includes('--approval=user-20260914')) throw new Error('Explicit testnet broadcast and approval reference required')
  const environment = JSON.parse(fs.readFileSync('config/attestcoin/cc3-testnet.sepolia.release.json', 'utf8'))
  const provider = new JsonRpcProvider('https://ethereum-sepolia-rpc.publicnode.com')
  if (Number((await provider.getNetwork()).chainId) !== 11155111) throw new Error('Source chain mismatch')
  const signer = deployer.connect(provider)
  const escrowAddress = environment.source.emitters[0].address
  const tokenAddress = environment.source.tokens[0].address
  const source = new Contract(escrowAddress, JSON.parse(fs.readFileSync('test/fixtures/gpu/abi/SourceEscrow.json', 'utf8')), signer)
  const token = new Contract(tokenAddress, JSON.parse(fs.readFileSync('test/fixtures/gpu/abi/GpuTestToken.json', 'utf8')), signer)
  const amount = BigInt(args.includes('--amount') ? args[args.indexOf('--amount') + 1] : '1000000')
  if (amount <= 0n || amount > 1_000_000n) throw new Error('Scenario payouts are limited to 1 source tUSD')
  const account = id('mockdepin-testonly:native-integration')
  const obligationRef = id('gpu080-obligation-v2')
  const settlementId = id(`scenario-settlement-${Date.now()}`)
  if ((await token.allowance(deployer.address, escrowAddress)) < amount) {
    const approval = await token.approve(escrowAddress, amount)
    if ((await approval.wait()).status !== 1) throw new Error('Source approval failed')
  }
  const estimate = await source.settle.estimateGas(account, obligationRef, tokenAddress, amount, settlementId)
  const tx = await source.settle(account, obligationRef, tokenAddress, amount, settlementId, {gasLimit: estimate * 3n / 2n})
  const receipt = await tx.wait()
  if (receipt.status !== 1) throw new Error('Source settlement failed')
  const directory = '.artifacts/native-testnet'
  fs.mkdirSync(directory, {recursive:true})
  fs.writeFileSync(`${directory}/settle-refresh.json`, JSON.stringify({txHash:tx.hash,blockNumber:receipt.blockNumber,amount:String(amount)},null,2)+'\n')
  console.log(JSON.stringify({sourceSettlement:tx.hash,block:receipt.blockNumber,amount:String(amount)}))
} else if (command === 'obligation') {
  // TEST_ONLY issuer recognises and assigns a NEW simulated obligation. Consumption creates a receivable with fresh evidence.
  if (!args.includes('--broadcast') || !args.includes('--approval=user-20260914')) throw new Error('Explicit testnet broadcast and approval reference required')
  const environment = JSON.parse(fs.readFileSync('config/attestcoin/cc3-testnet.sepolia.release.json', 'utf8'))
  const provider = new JsonRpcProvider('https://ethereum-sepolia-rpc.publicnode.com')
  if (Number((await provider.getNetwork()).chainId) !== 11155111) throw new Error('Source chain mismatch')
  const signer = deployer.connect(provider)
  const source = new Contract(environment.source.emitters[0].address,
    JSON.parse(fs.readFileSync('test/fixtures/gpu/abi/SourceEscrow.json', 'utf8')), signer)
  const amount = BigInt(args.includes('--amount') ? args[args.indexOf('--amount') + 1] : '10000000')
  if (amount <= 0n || amount > 100_000_000n) throw new Error('Scenario obligations are limited to 100 source tUSD')
  const account = id('mockdepin-testonly:native-integration')
  const obligationRef = id(`scenario-obligation-${Date.now()}`)
  const facilityName = args.includes('--facility') ? args[args.indexOf('--facility') + 1] : 'gpu080-facility-v2'
  const facilityKey = keccak256(id(facilityName))
  const dueAt = (await provider.getBlock('latest')).timestamp + 86400
  const recognized = await source.recognizeObligation(account, obligationRef, deployer.address, environment.source.tokens[0].address, amount, dueAt)
  const recognizedReceipt = await recognized.wait()
  if (recognizedReceipt.status !== 1) throw new Error('Source recognition failed')
  const assigned = await source.assignObligation(account, obligationRef, facilityKey)
  const assignedReceipt = await assigned.wait()
  if (assignedReceipt.status !== 1) throw new Error('Source assignment failed')
  const directory = '.artifacts/native-testnet'
  fs.mkdirSync(directory, {recursive:true})
  fs.writeFileSync(`${directory}/recognize-refresh.json`, JSON.stringify({txHash:recognized.hash,blockNumber:recognizedReceipt.blockNumber,obligationRef,amount:String(amount),dueAt},null,2)+'\n')
  fs.writeFileSync(`${directory}/assign-refresh.json`, JSON.stringify({txHash:assigned.hash,blockNumber:assignedReceipt.blockNumber,obligationRef,facilityKey,facilityName},null,2)+'\n')
  console.log(JSON.stringify({sourceRecognition:recognized.hash,sourceAssignment:assigned.hash,obligationRef,facilityName,amount:String(amount),dueAt}))
} else if (command === 'observe') {
  // Operator refreshes the SIMULATED control observation (ControlRegistry.lastObservedAt gates draws for 15 minutes).
  if (!args.includes('--broadcast') || !args.includes('--approval=user-20260914')) throw new Error('Explicit testnet broadcast and approval reference required')
  const manifest = JSON.parse(fs.readFileSync('config/gpu/deployments/cc3-testnet.json', 'utf8'))
  const provider = new JsonRpcProvider(manifest.rpcUrl)
  if (Number((await provider.getNetwork()).chainId) !== 102031) throw new Error('Chain mismatch')
  const agreementName = args.includes('--agreement') ? args[args.indexOf('--agreement') + 1] : 'gpu080-SIMULATED-control-v2'
  const control = new Contract(manifest.contracts.ControlRegistry,
    JSON.parse(fs.readFileSync('test/fixtures/gpu/abi/ControlRegistry.json', 'utf8')), deployer.connect(provider))
  const tx = await control.observe(id(agreementName), 2, manifest.source.emitter)
  const receipt = await tx.wait(2)
  if (receipt.status !== 1) throw new Error('Control observation failed')
  console.log(JSON.stringify({controlObservation:tx.hash,block:receipt.blockNumber,agreement:id(agreementName)}))
} else if (command === 'open-facility') {
  // Opens an additional TEST_ONLY facility (OpenGpuFacility.s.sol) through the same dry-run + live-RPC execution path as setup.
  if (!args.includes('--broadcast') || !args.includes('--approval=user-20260914')) throw new Error('Explicit testnet broadcast and approval reference required')
  const flag = (name, fallback) => args.includes(name) ? args[args.indexOf(name) + 1] : fallback
  const rpc = 'https://rpc.cc3-testnet.creditcoin.network'
  const provider = new JsonRpcProvider(rpc)
  if (Number((await provider.getNetwork()).chainId) !== 102031) throw new Error('Chain mismatch')
  const manifest = JSON.parse(fs.readFileSync('config/gpu/deployments/cc3-testnet.json', 'utf8'))
  const environment = {...process.env, PRIVATE_KEY: deployer.privateKey,
    GPU_MANAGER: manifest.contracts.CreditFacilityManager,
    GPU_BORROWER: roles.borrower.address, GPU_UNDERWRITER_PRIVATE_KEY: roles.underwriter.privateKey,
    GPU_SOURCE_EMITTER: manifest.source.emitter, GPU_SOURCE_TOKEN: manifest.source.token,
    GPU_FACILITY_NAME: flag('--facility', 'gpu080-facility-v3'), GPU_AGREEMENT_NAME: flag('--agreement', 'gpu080-SIMULATED-control-v3'),
    GPU_FACILITY_LIMIT: flag('--limit', '37500000'), GPU_APPROVAL_NONCE: flag('--nonce', '2')}
  // The public RPC is load-balanced over replicas that lag by a few blocks; pinning the dry run a little behind
  // the head (GPU_FORK_BLOCK_LAG, default 0 = latest) avoids "Expect block number from id" from a lagging peer.
  const lag = Number(process.env.GPU_FORK_BLOCK_LAG || 0)
  const pin = lag > 0 ? ['--fork-block-number', String(await provider.getBlockNumber() - lag)] : []
  const result = spawnSync('forge', ['script', 'script/gpu/OpenGpuFacility.s.sol:OpenGpuFacility',
    '--rpc-url', rpc, '--gas-estimate-multiplier', '500', ...pin], {env: environment, stdio: 'inherit'})
  if (result.status !== 0) process.exit(result.status || 1)
  if (args.includes('--dry-run')) { console.log('Dry run only; no transaction sent'); process.exit(0) }
  await executeRpcPlan('OpenGpuFacility', provider)
  const run = JSON.parse(fs.readFileSync('broadcast/OpenGpuFacility.s.sol/102031/run-latest.json', 'utf8'))
  const target = flag('--receipt', '.artifacts/native-testnet/open-facility-receipt.json')
  fs.mkdirSync(path.dirname(target), {recursive:true})
  fs.writeFileSync(target, JSON.stringify({receipts: run.receipts, facilityName: environment.GPU_FACILITY_NAME,
    agreementName: environment.GPU_AGREEMENT_NAME, facilityId: id(environment.GPU_FACILITY_NAME), agreementId: id(environment.GPU_AGREEMENT_NAME)}, null, 2)+'\n')
  console.log(JSON.stringify({facilityId: id(environment.GPU_FACILITY_NAME), agreementId: id(environment.GPU_AGREEMENT_NAME), receipt: target, transactions: run.receipts.length}))
} else if (command === 'fund-roles' || command === 'setup') {
  if (!args.includes('--broadcast') || !args.includes('--approval=user-20260914')) throw new Error('Explicit testnet broadcast and approval reference required')
  const rpc = 'https://rpc.cc3-testnet.creditcoin.network'
  const provider = new JsonRpcProvider(rpc)
  if (Number((await provider.getNetwork()).chainId) !== 102031) throw new Error('Chain mismatch')
  if (command === 'fund-roles') {
    const signer = deployer.connect(provider)
    let nonce = await provider.getTransactionCount(deployer.address, 'pending')
    for (const [role, wallet] of Object.entries(roles)) {
      const balance = await provider.getBalance(wallet.address)
      if (balance < 1_000_000_000_000_000_000n) {
        const tx = await signer.sendTransaction({ to: wallet.address, value: 2_000_000_000_000_000_000n - balance,
          nonce: nonce++, gasLimit: 100000n })
        const receipt = await tx.wait()
        if (receipt.status !== 1) throw new Error(`Role funding failed: ${role}`)
        console.log(JSON.stringify({role, address: wallet.address, txHash: tx.hash}))
      }
    }
  } else {
    const manifest = JSON.parse(fs.readFileSync('config/gpu/deployments/cc3-testnet.json', 'utf8'))
    const environment = {...process.env, PRIVATE_KEY: deployer.privateKey,
      GPU_MANAGER: manifest.contracts.CreditFacilityManager,
      GPU_BORROWER_PRIVATE_KEY: roles.borrower.privateKey, GPU_UNDERWRITER_PRIVATE_KEY: roles.underwriter.privateKey,
      GPU_SOURCE_EMITTER: manifest.source.emitter, GPU_SOURCE_TOKEN: manifest.source.token}
    const result = spawnSync('forge', ['script', 'script/gpu/SetupGpuFacility.s.sol:SetupGpuFacility',
      '--rpc-url', rpc, '--gas-estimate-multiplier', '500'], {env: environment, stdio: 'inherit'})
    if (result.status !== 0) process.exit(result.status || 1)
    await executeRpcPlan('SetupGpuFacility', provider)
  }
} else if (command === 'source' || command === 'destination') {
  if (!args.includes('--broadcast') || !args.includes('--approval=user-20260914')) throw new Error('Explicit testnet broadcast and approval reference required')
  const source = command === 'source'
  const chainId = source ? 11155111 : 102031
  const rpc = source ? 'https://ethereum-sepolia-rpc.publicnode.com' : 'https://rpc.cc3-testnet.creditcoin.network'
  const provider = new JsonRpcProvider(rpc)
  if (Number((await provider.getNetwork()).chainId) !== chainId) throw new Error('Chain mismatch')
  const environment = { ...process.env, PRIVATE_KEY: deployer.privateKey, GPU_UNDERWRITER: roles.underwriter.address,
    GPU_TREASURY: roles.treasury.address, GPU_BORROWER: roles.borrower.address, GPU_KEEPER: roles.keeper.address,
    GPU_GOVERNANCE_DELAY: '60', GPU_SOURCE_ISSUER: deployer.address }
  const manifestPath = 'config/attestcoin/cc3-testnet.sepolia.release.json'
  if (!source && fs.existsSync(manifestPath)) {
    const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'))
    environment.GPU_MANIFEST_HASH = manifest.manifestHash.replace('sha256:', '0x')
    environment.GPU_SOURCE_EMITTER = manifest.source.emitters[0].address
    environment.GPU_SOURCE_TOKEN = manifest.source.tokens[0].address
  }
  const file = source ? 'DeployGpuSource' : 'DeployGpu'
  const result = spawnSync('forge', ['script', `script/gpu/${file}.s.sol:${file}`, '--rpc-url', rpc,
    ...(source ? ['--broadcast', '--slow'] : []), '--gas-estimate-multiplier', source ? '150' : '500'], { env: environment, stdio: 'inherit' })
  if (result.status !== 0) process.exit(result.status || 1)
  if (!source) {
    // Creditcoin charges runtime-specific gas beyond Forge's local EVM simulation. Estimate each real
    // transaction after its dependencies are mined; never seal wiring after a failed setup transaction.
    await executeRpcPlan('DeployGpu', provider)
  }
} else {
  throw new Error('Use wallets, source or destination')
}
