/** Prepare actual source proof artifacts using the pinned official SDK command, never an alternate decoder. */
import fs from 'node:fs'
import { spawnSync } from 'node:child_process'
const source = JSON.parse(fs.readFileSync('broadcast/DeployGpuSource.s.sol/11155111/run-latest.json', 'utf8'))
const manifestPath = 'config/attestcoin/cc3-testnet.sepolia.release.json'
const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'))
const outputDir = '.artifacts/native-testnet'
fs.mkdirSync(outputDir, { recursive: true })
// `--refresh` (checkpoint-refresh) or `--refresh settle-refresh` proves one later source transition recorded by native_tools.
const refreshIndex = process.argv.indexOf('--refresh')
const refresh = refreshIndex >= 0
  ? (/^[a-z0-9-]+$/.test(process.argv[refreshIndex + 1] || '') ? process.argv[refreshIndex + 1] : 'checkpoint-refresh') : null
const selected = refresh ? [{hash:JSON.parse(fs.readFileSync(`${outputDir}/${refresh}.json`, 'utf8')).txHash,
  function:`${refresh}(`}] : source.transactions.filter(t => /^(recognizeObligation|assignObligation|settle|reserveCheckpoint)\(/.test(t.function || ''))
if (!refresh && selected.length !== 4) throw new Error(`Expected four native source transitions, found ${selected.length}`)
let pending = false
for (const transaction of selected) {
  const name = transaction.function.split('(')[0]
  const target = `${outputDir}/${name}.proof.json`
  const stored = fs.existsSync(target) ? JSON.parse(fs.readFileSync(target, 'utf8')) : null
  if (stored?.status === 'PROOF_READY' && stored.txHash.toLowerCase() === transaction.hash.toLowerCase()) {
    console.log(`${name}: stored PROOF_READY`)
    continue
  }
  const result = spawnSync('node', ['offchain/attestcoin/dist/src/cli.js', 'proof', '--manifest', manifestPath], {
    input: JSON.stringify({ version: 1, txHash: transaction.hash.toLowerCase(), manifestHash: manifest.manifestHash }),
    encoding: 'utf8', timeout: 45000, maxBuffer: 4_194_304,
  })
  if (result.status !== 0) { console.log(`${name}: official service pending`); pending = true; continue }
  const proof = JSON.parse(result.stdout)
  fs.writeFileSync(target, JSON.stringify(proof, null, 2) + '\n')
  console.log(`${name}: ${proof.status} (${proof.code || 'ready for native verification'})`)
  if (proof.status !== 'PROOF_READY') pending = true
}
process.exitCode = pending ? 2 : 0
