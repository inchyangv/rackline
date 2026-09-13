import { useEffect, useRef, useState } from 'react'
import { ArrowDownLeft, ArrowRight, Check, ChevronRight, Clock3, FileCheck2, FileText, Flag, Inbox, Layers3, LockKeyhole, RefreshCw, Search, ShieldCheck, UserRound, Waypoints } from 'lucide-react'
import { useDemoStore } from './demo-store'
import './provider-pages.css'

type CaseStatus = 'Open' | 'Requested' | 'Awaiting proof' | 'Acknowledged'
type CaseType = 'Proof' | 'Control' | 'Reconciliation'
type Activity = { text: string; detail: string }
type OperationCase = { id: string; title: string; provider: string; account: string; type: CaseType; status: CaseStatus; priority: 'High' | 'Normal'; amount: string; owner: string; age: string; reference: string; description: string; activity: Activity[] }

const initialCases: OperationCase[] = [
  { id: 'OPS-1042', title: 'Source evidence awaiting proof', provider: 'Aethir', account: 'Atlas Compute', type: 'Proof', status: 'Open', priority: 'Normal', amount: '$28,400', owner: 'Unassigned', age: '18 min', reference: 'RCV-0251', description: 'An additional sample statement is awaiting official evidence. This exception is outside the $140,000 seeded borrowing base. Retrying demonstrates a facility-wide proof-pending scenario; it never produces a real native proof.', activity: [{ text: 'Additional sample statement loaded', detail: 'RCV-0251 · illustrative USD value $28,400 · excluded from the demo borrowing base' }, { text: 'Native evidence required', detail: 'No official verification or economic consumption recorded.' }] },
  { id: 'OPS-1041', title: 'Payment-control review required', provider: 'GPU.net', account: 'Atlas Compute · expansion', type: 'Control', status: 'Open', priority: 'High', amount: '$16,200', owner: 'Unassigned', age: '42 min', reference: 'RCV-0252', description: 'A separate expansion account needs enforceable payment routing and recovery-rights review. This pending account is outside the seeded facility and has no E2 approval, including in the simulation.', activity: [{ text: 'Sample expansion account linked', detail: 'Atlas Compute · proposed additional capacity · local fixture' }, { text: 'Control terms need review', detail: 'Receiver changes and recovery rights are not established for this expansion.' }] },
  { id: 'OPS-1040', title: 'Unmatched destination receipt', provider: 'GPU.net', account: 'Atlas Compute', type: 'Reconciliation', status: 'Open', priority: 'Normal', amount: '$2,400', owner: 'M. Chen · sample', age: '1 hr', reference: 'CASH-0087', description: 'A simulated destination receipt has no facility allocation. The amount is held outside debt repayment and LP cash totals until its ownership and destination are reconciled.', activity: [{ text: 'Sample destination receipt observed', detail: '$2,400 · simulated cash record, not a real transaction' }, { text: 'Allocation not found', detail: 'No borrower debt was reduced.' }] },
  { id: 'OPS-1039', title: 'Statement revision in review', provider: 'Aethir', account: 'Atlas Compute', type: 'Proof', status: 'Awaiting proof', priority: 'Normal', amount: '$32,000', owner: 'J. Park · sample', age: '2 hr', reference: 'RCV-0240 · revision', description: 'A proposed revision references a statement already in the seeded borrowing base. The revision is quarantined and contributes no additional credit. Reprocessing must preserve the original economic ID and avoid duplicate revenue.', activity: [{ text: 'Sample revision identified', detail: 'Original economic reference RCV-0240 is retained; no additional borrowing-base value.' }, { text: 'Waiting for official evidence', detail: 'The local preview has not contacted a proof service.' }] },
]

const caseIcon = { Proof: ShieldCheck, Control: LockKeyhole, Reconciliation: ArrowDownLeft }

export function OperationsPage() {
  const scenario = useDemoStore((state) => state.scenario)
  const setScenario = useDemoStore((state) => state.setScenario)
  const [cases, setCases] = useState(initialCases)
  const [selectedId, setSelectedId] = useState('OPS-1042')
  const [filter, setFilter] = useState('All cases')
  const [search, setSearch] = useState('')
  const [reason, setReason] = useState('')
  const [notice, setNotice] = useState('')
  const retryTimers = useRef<ReturnType<typeof setTimeout>[]>([])
  useEffect(() => () => { retryTimers.current.forEach(clearTimeout) }, [])
  const selected = cases.find((item) => item.id === selectedId) ?? cases[0]
  const needsAction = cases.filter((item) => item.status === 'Open').length
  const awaiting = cases.filter((item) => item.status === 'Awaiting proof' || item.status === 'Requested').length
  const acknowledged = cases.filter((item) => item.status === 'Acknowledged').length
  const filtered = cases.filter((item) => (filter === 'All cases' || filter === 'Needs action' && item.status === 'Open' || filter === 'Awaiting' && (item.status === 'Awaiting proof' || item.status === 'Requested') || filter === 'Acknowledged' && item.status === 'Acknowledged') && `${item.id} ${item.title} ${item.provider} ${item.account}`.toLowerCase().includes(search.toLowerCase()))
  const canAct = reason.trim().length >= 5 && selected.status !== 'Requested'

  function action(kind: 'assign' | 'acknowledge' | 'retry') {
    if (!canAct) return
    const currentId = selected.id
    const detail = reason.trim()
    setCases((current) => current.map((item) => item.id !== currentId ? item : {
      ...item,
      owner: kind === 'assign' ? 'You · demo operator' : item.owner,
      status: kind === 'acknowledge' ? 'Acknowledged' : kind === 'retry' ? 'Requested' : item.status,
      activity: [...item.activity, { text: kind === 'assign' ? 'Assigned to you · simulation' : kind === 'acknowledge' ? 'Case acknowledged · simulation' : 'Proof retry requested · simulation', detail }],
    }))
    setReason('')
    setNotice(kind === 'retry' ? 'Local retry queued. No external request has been sent.' : kind === 'assign' ? 'Assigned to you in this preview. Your reason was added to the audit trail.' : 'Acknowledged locally. Financial and verification states are unchanged.')
    if (kind === 'retry') {
      setScenario('proof-pending')
      retryTimers.current.push(setTimeout(() => {
        setCases((current) => current.map((item) => item.id === currentId ? { ...item, status: 'Awaiting proof', activity: [...item.activity, { text: 'Awaiting official proof · simulation', detail: 'Retry does not mark the event verified or change any debt.' }] } : item))
      }, 900))
    }
  }

  return <div className="rlp-page">
    <div className="rlp-page-intro"><div><p className="rl-eyebrow">THE OPERATING DESK</p><h1 className="rl-page-heading">Operations</h1><p className="rlp-page-subtitle">Every exception, with the context to act.</p></div><label className="rlp-scenario-select"><span>Demo scenario</span><select value={scenario} onChange={(event) => { setScenario(event.target.value as 'healthy' | 'proof-pending' | 'control-expired'); setNotice('Demo scenario updated. No live state has changed.') }}><option value="healthy">Healthy facility</option><option value="proof-pending">Proof pending</option><option value="control-expired">Control expired</option></select></label></div>
    <div className="rlp-ops-stats"><div className="rl-panel rlp-ops-stat"><span><Inbox size={17} />Needs attention</span><strong>{needsAction}<small>open cases</small></strong><div className="rlp-stat-bottom">Review before new credit is considered</div></div><div className="rl-panel rlp-ops-stat"><span><Clock3 size={17} />Awaiting evidence</span><strong>{awaiting}<small>pending</small></strong><div className="rlp-stat-bottom">Official proof remains a separate step</div></div><div className="rl-panel rlp-ops-stat"><span><FileCheck2 size={17} />Acknowledged</span><strong>{acknowledged}<small>this session</small></strong><div className="rlp-stat-bottom">Triage only · no financial state changed</div></div></div>
    <div className="rlp-ops-workspace">
      <section className="rl-panel rlp-cases-panel" aria-labelledby="case-queue-heading">
        <div className="rlp-table-heading"><div><h2 id="case-queue-heading">Exception queue</h2><p>Illustrative cases across your provider network.</p></div><span className="rlp-queue-count">{cases.length}</span></div>
        <div className="rlp-case-filters" aria-label="Filter operation cases">{['All cases', 'Needs action', 'Awaiting', 'Acknowledged'].map((item) => <button type="button" key={item} className={filter === item ? 'rlp-case-filter-active' : ''} aria-pressed={filter === item} onClick={() => setFilter(item)}>{item}</button>)}</div>
        <label className="rlp-search rlp-case-search"><Search size={16} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search cases, accounts, or providers" aria-label="Search operation cases" /></label>
        <div className="rlp-case-list">{filtered.map((item) => { const Icon = caseIcon[item.type]; return <button type="button" key={item.id} className={`rlp-case-row ${selectedId === item.id ? 'rlp-case-selected' : ''}`} aria-pressed={selectedId === item.id} onClick={() => { setSelectedId(item.id); setReason(''); setNotice('') }}><span className={`rlp-case-icon ${item.priority === 'High' ? 'rlp-case-icon-amber' : ''}`}><Icon size={19} /></span><span className="rlp-case-row-main"><span className="rlp-case-row-meta">{item.id}<span>·</span>{item.provider}<span>·</span>{item.age}</span><strong>{item.title}</strong><span className="rlp-case-account">{item.account} <span>· {item.reference}</span></span><span className="rlp-case-row-tags"><span className={`rlp-badge ${item.status === 'Acknowledged' ? 'rlp-badge-green' : item.status === 'Open' ? 'rlp-badge-neutral' : 'rlp-badge-amber'}`}>{item.status === 'Requested' && <RefreshCw size={11} className="rlp-spin" />}{item.status}</span>{item.priority === 'High' && <span className="rlp-priority"><Flag size={11} />High priority</span>}</span></span><ChevronRight size={17} className="rlp-case-chevron" /></button> })}</div>
        {filtered.length === 0 && <div className="rlp-empty"><Inbox size={26} /><strong>No cases in this view</strong><p>Try another filter, or clear your search.</p><button type="button" className="rlp-text-button" onClick={() => { setFilter('All cases'); setSearch('') }}>Show all cases</button></div>}
        <div className="rlp-table-footer"><span>{filtered.length} of {cases.length} sample cases</span><span><LockKeyhole size={13} />Local operator preview</span></div>
      </section>
      <section className="rl-panel rlp-case-detail" aria-labelledby="selected-case-heading">
        <div className="rlp-case-detail-heading"><span className="rlp-kicker">CASE DETAIL</span><span className="rlp-badge rlp-badge-neutral">{selected.id}</span></div>
        <h2 id="selected-case-heading">{selected.title}</h2><p className="rlp-case-description">{selected.description}</p>
        <dl className="rlp-case-facts"><div><dt>Provider / account</dt><dd>{selected.provider}<span>{selected.account}</span></dd></div><div><dt>Amount in review</dt><dd>{selected.amount}<span>USD value · sample</span></dd></div><div><dt>Assigned to</dt><dd><UserRound size={13} />{selected.owner}</dd></div><div><dt>Case status</dt><dd>{selected.status}</dd></div></dl>
        <div className="rlp-proof-path"><h3><Waypoints size={15} />Evidence & cash trace</h3><div><span><FileText size={14} />Source fixture</span><ArrowRight size={13} /><span className="rlp-proof-path-pending"><ShieldCheck size={14} />Native pending</span></div><div><span><Layers3 size={14} />Eligibility review</span><ArrowRight size={13} /><span><ArrowDownLeft size={14} />{selected.type === 'Reconciliation' ? 'Cash unallocated' : 'Cash not received'}</span></div><p>Intended path: official Attestcoin. This trace is simulated; no native verification or repayment is claimed.</p></div>
        <div className="rlp-audit"><h3>Activity</h3><ol>{selected.activity.map((entry, index) => <li key={`${selected.id}-${index}`}><span className="rlp-audit-dot" /><div><strong>{entry.text}</strong><p>{entry.detail}</p></div></li>)}</ol></div>
        <div className="rlp-case-actions"><label className="rlp-field-label" htmlFor="case-action-reason">Action note <span>Required</span></label><textarea id="case-action-reason" className="rlp-textarea" rows={3} maxLength={400} placeholder="Add a reason for the audit trail…" value={reason} onChange={(event) => setReason(event.target.value)} /><span className="rlp-field-hint">At least 5 characters. Actions affect this local preview only.</span><div className="rlp-action-buttons"><button type="button" className="rl-button rl-button-secondary" disabled={!canAct || selected.owner === 'You · demo operator'} onClick={() => action('assign')}><UserRound size={14} />Assign to me</button>{selected.type === 'Proof' && selected.status !== 'Acknowledged' ? <button type="button" className="rl-button rl-button-primary" disabled={!canAct} onClick={() => action('retry')}><RefreshCw size={14} className={selected.status === 'Requested' ? 'rlp-spin' : ''} />{selected.status === 'Requested' ? 'Requesting…' : 'Simulate retry'}</button> : <button type="button" className="rl-button rl-button-primary" disabled={!canAct || selected.status === 'Acknowledged'} onClick={() => action('acknowledge')}><Check size={15} />Acknowledge</button>}</div>{selected.type === 'Proof' && selected.status !== 'Acknowledged' && <button type="button" className="rlp-text-button rlp-acknowledge-link" disabled={!canAct} onClick={() => action('acknowledge')}>Acknowledge without retry</button>}</div>
      </section>
    </div>
    <div className="rlp-ops-notice" role="status" aria-live="polite">{notice || 'All cases and actions on this page are local simulations. No partner, proof service, or blockchain is contacted.'}</div>
  </div>
}
