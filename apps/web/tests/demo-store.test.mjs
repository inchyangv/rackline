import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'

// Exercise the actual TS store without a browser, RPC, temporary build files, or new dependencies.
const source = readFileSync(new URL('../src/features/preview/demo-store.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText
const require = createRequire(import.meta.url)

function demo({ saved = new Map(), unavailable = false, connect = true } = {}) {
  const storage = {
    getItem(name) { if (unavailable) throw new Error('Storage blocked'); return saved.get(name) ?? null },
    setItem(name, value) { if (unavailable) throw new Error('Quota exceeded'); saved.set(name, value) },
    removeItem(name) { if (unavailable) throw new Error('Storage blocked'); saved.delete(name) },
  }
  const module = { exports: {} }
  runInNewContext(compiled, { module, exports: module.exports, require, localStorage: storage, console })
  const { useDemoStore: store, getDemoMaxAmount: max, getDemoQuote: quote, DEMO_STORAGE_KEY: key } = module.exports
  const state = () => store.getState()
  if (connect) state().connect()
  return { store, state, max, quote, key, saved }
}

test('starts disconnected and refuses transactions without a demo wallet', () => {
  const { state } = demo({ connect: false })
  assert.equal(state().connected, false)
  assert.equal(state().transact('supply', 250).ok, false)
  assert.equal(state().walletBalance, 85_000)
})

test('supply updates wallet, supplied, vault liquidity and NAV exactly', () => {
  const { state } = demo()
  assert.equal(state().transact('supply', 250).ok, true)
  assert.equal(state().walletBalance, 84_750)
  assert.equal(state().supplied, 12_750)
  assert.equal(state().vaultCash, 782_250)
  assert.equal(state().vaultAssets, 2_480_250)
})

test('borrow increases principal and wallet but leaves vault NAV unchanged', () => {
  const { state } = demo()
  assert.equal(state().transact('borrow', 100).ok, true)
  assert.equal(state().debt, 42_100)
  assert.equal(state().walletBalance, 85_100)
  assert.equal(state().vaultCash, 781_900)
  assert.equal(state().vaultAssets, 2_480_000)
})

test('a partial repayment pays unpaid interest before principal', () => {
  const { state } = demo()
  assert.equal(state().transact('repay', 50).ok, true)
  assert.equal(state().interest, 76)
  assert.equal(state().debt, 42_000)
  assert.equal(state().walletBalance, 84_950)
  assert.equal(state().vaultCash, 782_050)
  assert.equal(state().vaultAssets, 2_480_000)
})

test('repayment above interest applies only the remainder to principal', () => {
  const { state } = demo()
  assert.equal(state().transact('repay', 200).ok, true)
  assert.equal(state().interest, 0)
  assert.equal(state().debt, 41_926)
})

test('proof pending blocks borrowing without changing debt and allows repayment', () => {
  const { state } = demo()
  state().setScenario('proof-pending')
  assert.equal(state().debt, 42_000)
  assert.equal(state().interest, 126)
  assert.equal(state().transact('borrow', 1).ok, false)
  assert.equal(state().transact('repay', 50).ok, true)
  assert.equal(state().interest, 76)
})

test('expired control blocks borrowing but not repayment; restoring checks does not erase debt', () => {
  const { state } = demo()
  state().setScenario('control-expired')
  assert.equal(state().transact('borrow', 1).ok, false)
  assert.equal(state().transact('repay', 126).ok, true)
  state().setScenario('healthy')
  assert.equal(state().debt, 42_000)
  assert.equal(state().transact('borrow', 1).ok, true)
})

test('rejects non-finite, negative, zero, sub-cent and excessive inputs', () => {
  const { state } = demo()
  for (const amount of [NaN, Infinity, -1, 0, 0.001, 1_000_000_000_001]) {
    assert.equal(state().transact('supply', amount).ok, false, String(amount))
  }
  assert.equal(state().walletBalance, 85_000)
})

test('insufficient wallet and supplied balances never create negative balances', () => {
  const { state } = demo()
  assert.equal(state().transact('supply', 85_000.01).ok, false)
  assert.equal(state().transact('withdraw', 12_500.01).ok, false)
  assert.equal(state().walletBalance, 85_000)
  assert.equal(state().supplied, 12_500)
})

test('credit headroom includes accrued interest and enforces the last cent', () => {
  const { state, max } = demo()
  assert.equal(max(state(), 'borrow'), 55_874)
  assert.equal(state().transact('borrow', 55_874.01).ok, false)
  assert.equal(state().transact('borrow', 55_874).ok, true)
  assert.equal(max(state(), 'borrow'), 0)
})

test('borrow also respects vault cash independently of the credit cap', () => {
  const { state, store, max } = demo()
  store.setState({ vaultCash: 75 })
  assert.equal(max(state(), 'borrow'), 75)
  assert.equal(state().transact('borrow', 75.01).ok, false)
  assert.equal(state().transact('borrow', 75).ok, true)
  assert.equal(state().vaultCash, 0)
})

test('MAX repayment clears precisely principal plus interest, without overpayment', () => {
  const { state, max } = demo()
  assert.equal(max(state(), 'repay'), 42_126)
  assert.equal(state().transact('repay', 42_126.01).ok, false)
  assert.equal(state().transact('repay', 42_126).ok, true)
  assert.equal(state().debt, 0)
  assert.equal(state().interest, 0)
  assert.equal(max(state(), 'repay'), 0)
})

test('immediate withdrawal returns wallet funds and reduces cash, supplied and NAV', () => {
  const { state } = demo()
  assert.equal(state().transact('withdraw', 250).ok, true)
  assert.equal(state().walletBalance, 85_250)
  assert.equal(state().supplied, 12_250)
  assert.equal(state().vaultCash, 781_750)
  assert.equal(state().vaultAssets, 2_479_750)
  assert.equal(state().queue.length, 0)
})

test('queued withdrawal reserves supplied without pretending the wallet received cash', () => {
  const { state, store } = demo()
  store.setState({ vaultCash: 100 })
  assert.equal(state().transact('withdraw', 200).message, 'Withdrawal queued')
  const id = state().queue[0].id
  assert.equal(state().supplied, 12_300)
  assert.equal(state().walletBalance, 85_000)
  assert.equal(state().vaultCash, 100)
  assert.equal(state().settleWithdrawal(id).ok, false)
  assert.equal(state().claimWithdrawal(id).ok, false)
})

test('settlement reserves liquidity and a withdrawal can be claimed only once', () => {
  const { state, store } = demo()
  store.setState({ vaultCash: 100 })
  state().transact('withdraw', 200)
  const id = state().queue[0].id
  state().transact('supply', 100)
  assert.equal(state().settleWithdrawal(id).ok, true)
  assert.equal(state().vaultCash, 0)
  assert.equal(state().queue[0].status, 'claimable')
  assert.equal(state().settleWithdrawal(id).ok, false)
  assert.equal(state().cancelWithdrawal(id).ok, false)
  assert.equal(state().claimWithdrawal(id).ok, true)
  assert.equal(state().walletBalance, 85_100)
  assert.equal(state().claimWithdrawal(id).ok, false)
})

test('cancelling a pending withdrawal restores the reserved position only once', () => {
  const { state, store } = demo()
  store.setState({ vaultCash: 0 })
  state().transact('withdraw', 200)
  const id = state().queue[0].id
  assert.equal(state().cancelWithdrawal(id).ok, true)
  assert.equal(state().supplied, 12_500)
  assert.equal(state().queue.length, 0)
  assert.equal(state().cancelWithdrawal(id).ok, false)
})

test('new small withdrawals cannot bypass earlier requests; settlements remain FIFO', () => {
  const { state, store } = demo()
  store.setState({ vaultCash: 100 })
  state().transact('withdraw', 200)
  assert.equal(state().transact('withdraw', 50).message, 'Withdrawal queued')
  const [first, second] = state().queue
  state().transact('supply', 200)
  assert.equal(state().settleWithdrawal(second.id).ok, false)
  assert.equal(state().settleWithdrawal(first.id).ok, true)
  assert.equal(state().settleWithdrawal(second.id).ok, true)
  assert.equal(state().walletBalance, 84_800)
})

test('one hundred cent-sized transactions have no floating-point balance drift', () => {
  const { state } = demo()
  for (let i = 0; i < 100; i++) assert.equal(state().transact('supply', 0.01).ok, true)
  assert.equal(state().walletBalance, 84_999)
  assert.equal(state().supplied, 12_501)
})

test('isolated versioned persistence reloads reserved withdrawals without replacing actions', () => {
  const { state, store, key, saved } = demo()
  store.setState({ vaultCash: 0 })
  state().transact('withdraw', 200)
  const payload = JSON.parse(saved.get(key))
  assert.equal(key, 'rackline:gpu:preview:v1')
  assert.equal(payload.version, 1)
  assert.equal(payload.state.transact, undefined)
  assert.equal(saved.size, 1)
  const reloaded = demo({ saved })
  assert.equal(reloaded.state().supplied, 12_300)
  assert.equal(reloaded.state().queue.length, 1)
  assert.equal(typeof reloaded.state().transact, 'function')
})

test('malformed stored balances reset safely and cannot overwrite transaction methods', () => {
  const { key, saved } = demo()
  const payload = JSON.parse(saved.get(key))
  payload.state.walletBalance = -1
  payload.state.transact = 'injected'
  saved.set(key, JSON.stringify(payload))
  const { state } = demo({ saved, connect: false })
  assert.equal(state().walletBalance, 85_000)
  assert.equal(state().connected, false)
  assert.equal(typeof state().transact, 'function')
})

test('blocked or quota-exceeded storage still permits an in-memory demo', () => {
  const { state } = demo({ unavailable: true })
  assert.equal(state().transact('supply', 1).ok, true)
  assert.equal(state().supplied, 12_501)
})

test('reset restores all original disconnected balances and clears the queue', () => {
  const { state, store } = demo()
  store.setState({ vaultCash: 0 })
  state().transact('withdraw', 200)
  state().setScenario('control-expired')
  state().reset()
  assert.equal(state().connected, false)
  assert.equal(state().scenario, 'healthy')
  assert.equal(state().debt, 42_000)
  assert.equal(state().interest, 126)
  assert.equal(state().supplied, 12_500)
  assert.equal(state().vaultCash, 782_000)
  assert.equal(state().queue.length, 0)
})

test('liquidity stress reallocates only synthetic vault cash, never user funds or NAV', () => {
  const { state } = demo()
  assert.equal(state().simulateLiquidityStress().ok, true)
  assert.equal(state().vaultCash, 5_000)
  assert.equal(state().vaultAssets, 2_480_000)
  assert.equal(state().walletBalance, 85_000)
  assert.equal(state().supplied, 12_500)
  assert.equal(state().debt, 42_000)
  assert.equal(state().interest, 126)
  assert.match(state().activities[0].detail, /Synthetic reallocation/)
  assert.equal(state().simulateLiquidityStress().ok, false)
})

test('stress cannot change a queued withdrawal; actual demo repayment enables settlement', () => {
  const { state } = demo()
  state().simulateLiquidityStress()
  assert.equal(state().transact('withdraw', 6_000).message, 'Withdrawal queued')
  const id = state().queue[0].id
  assert.equal(state().simulateLiquidityStress().ok, false)
  assert.equal(state().settleWithdrawal(id).ok, false)
  assert.equal(state().transact('repay', 1_000).ok, true)
  assert.equal(state().vaultCash, 6_000)
  assert.equal(state().settleWithdrawal(id).ok, true)
  assert.equal(state().vaultCash, 0)
  assert.equal(state().claimWithdrawal(id).ok, true)
  assert.equal(state().walletBalance, 90_000)
  assert.equal(state().debt, 41_126)
  assert.equal(state().interest, 0)
  assert.equal(state().claimWithdrawal(id).ok, false)
})
