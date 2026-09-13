import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { test } from 'node:test'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
import { keccak256, toUtf8Bytes } from 'ethers'

const source = readFileSync(
  new URL('../src/features/gpu/client.ts', import.meta.url),
  'utf8',
).replace('import.meta.env.VITE_GPU_API_URL', "''")
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText
const module = { exports: {} }
runInNewContext(compiled, {
  module,
  exports: module.exports,
  require: createRequire(import.meta.url),
  console,
})
const {
  parseAmount,
  exactAmount,
  validateConfig,
  validateRead,
  validateLogin,
} = module.exports
const address = '0x1111111111111111111111111111111111111111'
const config = {
  schemaVersion: '1.0',
  executionProfile: 'NATIVE_TESTNET',
  chainId: 102031,
  appDomain: 'rackline.test',
  deploymentId: 'test-v2',
  manifestHash: 'sha256:fixture',
  configured: true,
  contracts: {
    vault: address,
    asset: address,
    manager: address,
    repaymentRouter: address,
  },
  asset: { chainId: 102031, address, decimals: 6, symbol: 'TEST' },
  rpcUrl: 'https://rpc.example.test',
  explorerUrl: 'https://explorer.example.test',
  requiredVerification: 'ATTESTCOIN_NATIVE',
  capabilities: {},
}

test('token amounts retain every integer unit beyond JavaScript safe-number precision', () => {
  assert.equal(
    parseAmount('9007199254740993.123456', 6),
    9007199254740993123456n,
  )
  assert.equal(
    exactAmount('9007199254740993123456', 6),
    '9,007,199,254,740,993.123456',
  )
  assert.equal(exactAmount(null), 'Unavailable')
})
test('zero, exponent notation, excess decimals, negative and uint256 overflow amounts are rejected', () => {
  for (const value of [
    '0',
    '0.0000000',
    '1e6',
    '-1',
    '1,000',
    '.5',
    '0.0000001',
    (2n ** 256n).toString(),
  ])
    assert.throws(() => parseAmount(value, 6))
  assert.equal(parseAmount('0.000001', 6), 1n)
  assert.equal(parseAmount('123', 0), 123n)
})
test('configuration refuses wrong-chain tokens, missing/zero contracts, and native downgrade', () => {
  assert.equal(validateConfig(config).chainId, 102031)
  assert.throws(() =>
    validateConfig({ ...config, asset: { ...config.asset, chainId: 1 } }),
  )
  assert.throws(() =>
    validateConfig({
      ...config,
      contracts: {
        ...config.contracts,
        manager: '0x0000000000000000000000000000000000000000',
      },
    }),
  )
  assert.throws(() =>
    validateConfig({ ...config, requiredVerification: 'LOCAL_MOCK' }),
  )
  assert.throws(() =>
    validateConfig({ ...config, rpcUrl: 'javascript:alert(1)' }),
  )
})
test('stale reads remain inspectable but cross-profile and replaced manifest reads are rejected', () => {
  const meta = {
    executionProfile: config.executionProfile,
    chainId: config.chainId,
    deploymentId: config.deploymentId,
    manifestHash: config.manifestHash,
    freshness: 'STALE',
  }
  assert.doesNotThrow(() => validateRead(meta, config))
  assert.throws(() =>
    validateRead({ ...meta, executionProfile: 'LOCAL_MOCK' }, config),
  )
  assert.throws(() => validateRead({ ...meta, manifestHash: 'other' }, config))
})
test('API login signatures are bound to auxiliary purpose, domain, wallet, chain and expiration', () => {
  const td = {
    domain: {
      name: 'Rackline API Login',
      version: '1',
      chainId: 102031,
      salt: keccak256(toUtf8Bytes(config.appDomain)),
    },
    primaryType: 'Login',
    message: {
      wallet: address,
      chainId: 102031,
      appDomain: config.appDomain,
      purpose: 'API_LOGIN',
      expiresAt: Math.floor(Date.now() / 1000) + 300,
    },
  }
  assert.doesNotThrow(() => validateLogin(td, config, address))
  for (const message of [
    { ...td.message, purpose: 'CREDIT_APPROVAL' },
    { ...td.message, wallet: '0x2222222222222222222222222222222222222222' },
    { ...td.message, expiresAt: 1 },
    { ...td.message, chainId: 1 },
  ])
    assert.throws(() => validateLogin({ ...td, message }, config, address))
  assert.throws(() =>
    validateLogin(
      { ...td, domain: { ...td.domain, verifyingContract: address } },
      config,
      address,
    ),
  )
})
