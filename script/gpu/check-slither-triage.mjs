/** Exact finding IDs only; a reviewed contract change requires re-review, not silent suppression. */
import fs from 'node:fs'
import { createHash } from 'node:crypto'
const rows = JSON.parse(fs.readFileSync('.slither.db.json', 'utf8'))
if (!Array.isArray(rows) || rows.length === 0) throw new Error('Missing reviewed findings')
const ids = new Set()
for (const row of rows) {
  if (!/^[a-f0-9]{64}$/.test(row.id) || ids.has(row.id) || row.disposition !== 'FALSE_POSITIVE' ||
      !row.justification || !row.tests?.length || row.slitherVersion !== '0.11.6') throw new Error('Invalid triage record')
  ids.add(row.id)
  const hash = createHash('sha256').update(fs.readFileSync(row.source)).digest('hex')
  if (hash !== row.sourceSha256) throw new Error(`Security re-review required: ${row.source}`)
  for (const test of row.tests) if (!fs.existsSync(test)) throw new Error(`Missing review regression: ${test}`)
}
console.log(`Validated ${rows.length} exact reviewed Slither IDs and source hashes; all other findings remain enabled`)
