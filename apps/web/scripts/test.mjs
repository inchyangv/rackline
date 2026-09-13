import { spawnSync } from 'node:child_process'
import { readdirSync } from 'node:fs'
const files = readdirSync(new URL('../tests', import.meta.url))
  .filter((file) => file.endsWith('.test.mjs'))
  .map((file) => `tests/${file}`)
if (files.length === 0) throw new Error('No unit tests found')
const result = spawnSync(process.execPath, ['--test', ...files], {
  stdio: 'inherit',
})
process.exit(result.status ?? 1)
