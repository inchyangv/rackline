import { useRef, useState } from 'react'
import type { RefObject } from 'react'
import { Dialog } from 'radix-ui'
import { ArrowDownLeft, ArrowRight, Check, CheckCircle2, ChevronDown, ChevronRight, Clock3, Cpu, FileText, Layers3, Link2, LockKeyhole, Plus, Search, ShieldCheck, Waypoints, X } from 'lucide-react'
import { useDemoStore } from './demo-store'
import './provider-pages.css'

type Provider = 'Aethir' | 'GPU.net'
type Connection = { id: string; provider: Provider; name: string; gpus: number; receivables: number; isNew?: boolean }
type Receivable = { id: string; provider: Provider; period: string; amount: number; due: string; state: 'Sample eligible' | 'Collected'; received: number; applied: number }

const initialConnections: Connection[] = [
  { id: 'sample-aethir', provider: 'Aethir', name: 'Atlas Compute', gpus: 96, receivables: 98000 },
  { id: 'sample-gpunet', provider: 'GPU.net', name: 'Atlas Compute', gpus: 32, receivables: 42000 },
]
const receivables: Receivable[] = [
  { id: 'RCV-0241', provider: 'Aethir', period: 'Sep 01 – Sep 14', amount: 34000, due: 'Oct 06, 2026', state: 'Sample eligible', received: 0, applied: 0 },
  { id: 'RCV-0240', provider: 'Aethir', period: 'Aug 18 – Aug 31', amount: 32000, due: 'Sep 30, 2026', state: 'Sample eligible', received: 0, applied: 0 },
  { id: 'RCV-0239', provider: 'GPU.net', period: 'Sep 01 – Sep 14', amount: 21000, due: 'Sep 28, 2026', state: 'Sample eligible', received: 0, applied: 0 },
  { id: 'RCV-0238', provider: 'Aethir', period: 'Aug 04 – Aug 17', amount: 32000, due: 'Sep 22, 2026', state: 'Sample eligible', received: 0, applied: 0 },
  { id: 'RCV-0237', provider: 'GPU.net', period: 'Aug 18 – Aug 31', amount: 21000, due: 'Sep 20, 2026', state: 'Sample eligible', received: 0, applied: 0 },
  { id: 'RCV-0236', provider: 'Aethir', period: 'Jul 21 – Aug 03', amount: 24800, due: 'Sep 14, 2026', state: 'Collected', received: 24800, applied: 6200 },
]
const money = (value: number) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value)

function ProviderMark({ provider, small = false }: { provider: Provider; small?: boolean }) {
  return <span aria-hidden="true" className={`rlp-provider-mark ${provider === 'Aethir' ? 'rlp-mark-aethir' : 'rlp-mark-gpunet'} ${small ? 'rlp-mark-small' : ''}`}>{provider === 'Aethir' ? <Layers3 size={small ? 17 : 25} strokeWidth={2.3} /> : <Cpu size={small ? 17 : 25} strokeWidth={1.8} />}</span>
}

function ConnectWizard({ open, onOpenChange, onAdd }: { open: boolean; onOpenChange: (value: boolean) => void; onAdd: (provider: Provider, name: string) => void }) {
  const [step, setStep] = useState(0)
  const [provider, setProvider] = useState<Provider>('Aethir')
  const [name, setName] = useState('My compute cluster')
  const [consent, setConsent] = useState(false)
  const [previewConsent, setPreviewConsent] = useState(false)

  function changeOpen(next: boolean) {
    onOpenChange(next)
    if (!next) { setStep(0); setConsent(false); setPreviewConsent(false) }
  }

  return <Dialog.Root open={open} onOpenChange={changeOpen}>
    <Dialog.Portal>
      <Dialog.Overlay className="rlp-dialog-overlay" />
      <Dialog.Content className="rlp-dialog" onCloseAutoFocus={(event) => { event.preventDefault(); document.getElementById('rlp-connect-provider')?.focus() }}>
        <Dialog.Close className="rlp-dialog-close" aria-label="Close connection preview"><X size={19} /></Dialog.Close>
        <span className="rlp-kicker">PROVIDER CONNECTION · PREVIEW</span>
        <Dialog.Title className="rlp-dialog-title">{step === 3 ? 'Your sample account is ready.' : 'Connect your compute.'}</Dialog.Title>
        <Dialog.Description className="rlp-dialog-description">{step === 3 ? 'Explore the onboarding flow with a new local connection.' : 'A guided preview. No provider login, credentials, or funds are used.'}</Dialog.Description>
        {step < 3 && <div className="rlp-wizard-steps" aria-label={`Step ${step + 1} of 3`}>
          {['Choose provider', 'Review terms', 'Confirm'].map((label, index) => <div key={label} className={index <= step ? 'rlp-wizard-step rlp-step-active' : 'rlp-wizard-step'}><span>{index < step ? <Check size={13} /> : index + 1}</span>{label}</div>)}
        </div>}
        {step === 0 && <div className="rlp-wizard-body">
          <div className="rlp-provider-choices" role="group" aria-label="Choose a provider">
            {(['Aethir', 'GPU.net'] as const).map((item) => <button type="button" key={item} className={`rlp-provider-choice ${provider === item ? 'rlp-choice-selected' : ''}`} aria-pressed={provider === item} onClick={() => setProvider(item)}><ProviderMark provider={item} /><strong>{item}</strong><span>{item === 'Aethir' ? 'Cloud Host account' : 'GPU supplier account'}</span>{provider === item && <CheckCircle2 size={18} className="rlp-choice-check" />}</button>)}
          </div>
          <label className="rlp-field-label" htmlFor="provider-connection-name">Connection name</label>
          <input id="provider-connection-name" className="rlp-input" value={name} maxLength={48} onChange={(event) => setName(event.target.value)} placeholder="e.g. Northstar Compute" />
          <p className="rlp-field-hint">Choose a label for this sample account. Do not enter credentials.</p>
        </div>}
        {step === 1 && <div className="rlp-wizard-body">
          <div className="rlp-terms-card"><LockKeyhole size={21} /><div><strong>A clear path from revenue to repayment</strong><p>A live facility would require a separate rights review, enforceable payment control, official evidence, and approved loan terms.</p></div></div>
          <dl className="rlp-summary-list"><div><dt>Provider connection</dt><dd>{provider}</dd></div><div><dt>Payment control</dt><dd>Separate approval required</dd></div><div><dt>Native verification</dt><dd>Official Attestcoin intended</dd></div><div><dt>Current environment</dt><dd>Local simulation</dd></div></dl>
          <label className="rlp-check-label"><input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} /><span>I understand that connecting an account does not approve a loan or establish payment control.</span></label>
          <label className="rlp-check-label"><input type="checkbox" checked={previewConsent} onChange={(event) => setPreviewConsent(event.target.checked)} /><span>I want to create a sample connection in this local preview.</span></label>
        </div>}
        {step === 2 && <div className="rlp-wizard-body">
          <div className="rlp-connection-review"><ProviderMark provider={provider} /><div><strong>{name.trim()}</strong><span>{provider} · Sample supplier account</span></div></div>
          <dl className="rlp-summary-list"><div><dt>Account</dt><dd>Local sample</dd></div><div><dt>Rights & payment control</dt><dd>Pending review</dd></div><div><dt>Underwriting</dt><dd>Not submitted</dd></div><div><dt>Real native proof</dt><dd>Not submitted</dd></div></dl>
          <div className="rlp-inline-note"><FileText size={16} /><span>No provider request or transaction will be sent.</span></div>
        </div>}
        {step === 3 && <div className="rlp-wizard-success"><span><Check size={30} /></span><h3>{name.trim()}</h3><p>Added to your {provider} connections. Rights, payment control, and lending remain pending in this preview.</p></div>}
        <div className="rlp-dialog-footer">
          {step > 0 && step < 3 ? <button type="button" className="rl-button rl-button-secondary" onClick={() => setStep(step - 1)}>Back</button> : <span />}
          {step < 2 && <button type="button" className="rl-button rl-button-primary" disabled={step === 0 ? !name.trim() : !consent || !previewConsent} onClick={() => setStep(step + 1)}>Continue <ArrowRight size={16} /></button>}
          {step === 2 && <button type="button" className="rl-button rl-button-primary" onClick={() => { onAdd(provider, name.trim()); setStep(3) }}>Add sample connection <Plus size={16} /></button>}
          {step === 3 && <button type="button" className="rl-button rl-button-primary" onClick={() => changeOpen(false)}>View connection <ArrowRight size={16} /></button>}
        </div>
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>
}

function ReceivableDetails({ item, onClose, returnFocus }: { item: Receivable | null; onClose: () => void; returnFocus: RefObject<HTMLButtonElement | null> }) {
  const scenario = useDemoStore((state) => state.scenario)
  return <Dialog.Root open={item !== null} onOpenChange={(open) => { if (!open) onClose() }}><Dialog.Portal><Dialog.Overlay className="rlp-dialog-overlay" /><Dialog.Content className="rlp-dialog" onCloseAutoFocus={(event) => { event.preventDefault(); returnFocus.current?.focus() }}>
    <Dialog.Close className="rlp-dialog-close" aria-label="Close receivable details"><X size={19} /></Dialog.Close>
    <span className="rlp-kicker">SAMPLE RECEIVABLE</span><Dialog.Title className="rlp-dialog-title">{item?.id}</Dialog.Title><Dialog.Description className="rlp-dialog-description">Follow the evidence and the money separately. Every entry below is a local fixture.</Dialog.Description>
    {item && <><div className="rlp-receivable-total"><ProviderMark provider={item.provider} /><div><span>{item.provider} · {item.period}</span><strong>{money(item.amount)}</strong></div><span className="rlp-badge rlp-badge-neutral">USD value · demo</span></div>
      <div className="rlp-evidence-timeline">
        {[
          { icon: FileText, title: 'Source statement', detail: `${item.provider} sample statement · ${item.period}`, status: 'Fixture loaded', tone: 'blue' },
          { icon: ShieldCheck, title: 'Official native evidence', detail: 'Attestcoin is the intended verification path. No native proof has been submitted here.', status: 'Simulation only', tone: 'amber' },
          { icon: Layers3, title: 'Economic eligibility', detail: item.state === 'Collected' ? 'Paid receivable excluded from the sample borrowing base.' : scenario === 'healthy' ? 'Included in the simulated borrowing base only. Live source, rights, and native checks are not established.' : 'New demo borrowing is paused by the selected facility scenario. No live eligibility is established.', status: item.state === 'Collected' ? 'Already paid' : scenario === 'healthy' ? 'Sample eligible' : 'Demo credit paused', tone: 'neutral' },
          { icon: ArrowDownLeft, title: 'Destination cash', detail: 'Receipt at the loan-currency destination, separate from a source proof.', status: item.received ? `${money(item.received)} · simulated` : 'Not received', tone: item.received ? 'green' : 'neutral' },
          { icon: CheckCircle2, title: 'Repayment allocation', detail: item.applied ? `${money(item.received - item.applied)} remains outside the sample debt allocation.` : 'Debt changes only after actual cash is received and allocated.', status: item.applied ? `${money(item.applied)} · simulated` : 'Nothing applied', tone: item.applied ? 'green' : 'neutral' },
        ].map(({ icon: Icon, title, detail, status, tone }) => <div className="rlp-evidence-step" key={title}><span className="rlp-evidence-icon"><Icon size={17} /></span><div><strong>{title}</strong><p>{detail}</p><span className={`rlp-badge rlp-badge-${tone}`}>{status}</span></div></div>)}
      </div>
    </>}
    <div className="rlp-dialog-footer"><span /><Dialog.Close className="rl-button rl-button-secondary">Close details</Dialog.Close></div>
  </Dialog.Content></Dialog.Portal></Dialog.Root>
}

export function ProviderPage() {
  const scenario = useDemoStore((state) => state.scenario)
  const [connections, setConnections] = useState(initialConnections)
  const [expanded, setExpanded] = useState<string | null>(null)
  const [wizardOpen, setWizardOpen] = useState(false)
  const [filter, setFilter] = useState<'All providers' | Provider>('All providers')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<Receivable | null>(null)
  const receivableTrigger = useRef<HTMLButtonElement | null>(null)
  const filtered = receivables.filter((item) => (filter === 'All providers' || item.provider === filter) && `${item.id} ${item.provider} ${item.state}`.toLowerCase().includes(search.toLowerCase()))

  return <div className="rlp-page">
    <div className="rlp-page-intro"><div><p className="rl-eyebrow">YOUR COMPUTE NETWORK</p><h1 className="rl-page-heading">Providers</h1><p className="rlp-page-subtitle">Connect your compute. Bring your revenue into view.</p></div><button id="rlp-connect-provider" className="rl-button rl-button-primary" type="button" onClick={() => setWizardOpen(true)}><Plus size={17} /> Connect provider</button></div>
    <div className="rlp-metrics-grid">
      <div className="rl-panel rlp-metric"><span><Link2 size={16} /> Sample connections</span><strong>{connections.length}<small>across 2 providers</small></strong></div>
      <div className="rl-panel rlp-metric"><span><Cpu size={16} /> Tracked GPUs</span><strong>128<small>illustrative inventory</small></strong></div>
      <div className="rl-panel rlp-metric"><span><FileText size={16} /> Open receivables</span><strong>$140,000<small>sample USD value</small></strong></div>
    </div>
    <div className="rlp-section-heading"><h2>Your connections <span>{connections.length}</span></h2><span className="rlp-subtle-label"><span className="rlp-status-dot" /> Local sample data</span></div>
    <div className="rlp-connections-grid">
      {connections.map((connection) => {
        const controlExpired = scenario === 'control-expired' && connection.provider === 'Aethir'
        const pending = Boolean(connection.isNew)
        const stages = [
          { icon: Link2, label: 'Account', value: 'Sample linked', tone: 'green' },
          { icon: FileText, label: 'Asset rights', value: pending ? 'Review pending' : 'Sample reviewed', tone: pending ? 'neutral' : 'green' },
          { icon: LockKeyhole, label: 'Payment control', value: controlExpired ? 'Expired · demo' : pending ? 'Not established' : 'E2 · simulated', tone: controlExpired ? 'amber' : pending ? 'neutral' : 'blue' },
          { icon: ShieldCheck, label: 'Native evidence', value: scenario === 'proof-pending' || pending ? 'Awaiting proof' : 'Fixture only', tone: 'amber' },
          { icon: Layers3, label: 'Underwriting', value: pending || scenario !== 'healthy' ? 'Review pending' : 'Sample approved', tone: pending || scenario !== 'healthy' ? 'neutral' : 'blue' },
        ]
        return <article key={connection.id} className="rl-panel rlp-connection-card">
          <div className="rlp-connection-heading"><ProviderMark provider={connection.provider} /><div><h3>{connection.provider}</h3><p>{connection.name}</p></div><span className={`rlp-badge ${connection.isNew ? 'rlp-badge-blue' : pending || controlExpired ? 'rlp-badge-amber' : 'rlp-badge-neutral'}`}>{connection.isNew ? 'New sample' : pending || controlExpired ? 'Review needed' : 'Sample connected'}</span></div>
          <div className="rlp-connection-numbers"><div><span>GPU inventory</span><strong>{connection.gpus}<small>{connection.isNew ? 'not added' : ' NVIDIA H100'}</small></strong></div><div><span>Open receivables</span><strong>{money(connection.receivables)}</strong></div></div>
          <div className="rlp-connection-stages">{stages.map(({ icon: Icon, label, value, tone }) => <div key={label}><span><Icon size={15} />{label}</span><span className={`rlp-stage-value rlp-text-${tone}`}>{value}</span></div>)}</div>
          <div className="rlp-connection-bottom"><span><Clock3 size={14} />{connection.isNew ? 'Added in this session' : 'Illustrative account'}</span><button type="button" className="rlp-text-button" aria-expanded={expanded === connection.id} aria-controls={`connection-${connection.id}`} onClick={() => setExpanded(expanded === connection.id ? null : connection.id)}>Connection details <ChevronDown size={15} className={expanded === connection.id ? 'rlp-rotate' : ''} /></button></div>
          {expanded === connection.id && <div className="rlp-connection-details" id={`connection-${connection.id}`}><dl><div><dt>Environment</dt><dd>Local simulation</dd></div><div><dt>Provider authentication</dt><dd>Not performed</dd></div><div><dt>Official native submission</dt><dd>Not submitted</dd></div><div><dt>Live borrowing eligibility</dt><dd>Not established</dd></div></dl><p>Sample stages explain the review process. A real connection requires independent provider, rights, payment-control, and native-proof checks.</p></div>}
        </article>
      })}
    </div>
    <section className="rl-panel rlp-receivables-panel" aria-labelledby="receivables-heading">
      <div className="rlp-table-heading"><div><h2 id="receivables-heading">Revenue receivables</h2><p>A clear view of what is owed, and what has arrived.</p></div><span className="rlp-badge rlp-badge-neutral">Sample ledger</span></div>
      <div className="rlp-table-toolbar"><div className="rlp-filter-group" aria-label="Filter receivables by provider">{(['All providers', 'Aethir', 'GPU.net'] as const).map((item) => <button type="button" key={item} className={filter === item ? 'rlp-filter-active' : ''} aria-pressed={filter === item} onClick={() => setFilter(item)}>{item}</button>)}</div><label className="rlp-search"><Search size={16} /><input aria-label="Search receivables" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search receivables" /></label></div>
      <div className="rlp-table-scroll"><table className="rlp-table"><thead><tr><th>Receivable</th><th>Provider</th><th>Period</th><th>Due date</th><th className="rlp-align-right">Amount</th><th>Status</th><th><span className="rlp-sr-only">Details</span></th></tr></thead><tbody>{filtered.map((item) => <tr key={item.id}><td><button className="rlp-row-link" type="button" onClick={(event) => { receivableTrigger.current = event.currentTarget; setSelected(item) }}>{item.id}</button></td><td><span className="rlp-provider-cell"><ProviderMark provider={item.provider} small />{item.provider}</span></td><td className="rlp-muted-cell">{item.period}</td><td className="rlp-muted-cell">{item.due}</td><td className="rlp-align-right rlp-money-cell">{money(item.amount)}</td><td><span className={`rlp-badge ${item.state === 'Collected' ? 'rlp-badge-green' : scenario !== 'healthy' ? 'rlp-badge-amber' : 'rlp-badge-neutral'}`}>{item.state === 'Collected' ? item.state : scenario === 'healthy' ? 'Sample eligible' : 'Demo credit paused'}</span></td><td><button type="button" className="rlp-table-arrow" aria-label={`View ${item.id} details`} onClick={(event) => { receivableTrigger.current = event.currentTarget; setSelected(item) }}><ChevronRight size={17} /></button></td></tr>)}</tbody></table></div>
      {filtered.length === 0 && <div className="rlp-empty"><Search size={24} /><strong>No matching receivables</strong><p>Try a different provider or search term.</p><button type="button" className="rlp-text-button" onClick={() => { setSearch(''); setFilter('All providers') }}>Clear filters</button></div>}
      <div className="rlp-table-footer"><span>{filtered.length} sample receivable{filtered.length === 1 ? '' : 's'}</span><span><Waypoints size={14} /> Evidence and cash are tracked separately</span></div>
    </section>
    <ConnectWizard open={wizardOpen} onOpenChange={setWizardOpen} onAdd={(provider, name) => { const id = `sample-${Date.now()}`; setConnections((current) => [...current, { id, provider, name, gpus: 0, receivables: 0, isNew: true }]); setExpanded(id) }} />
    <ReceivableDetails item={selected} onClose={() => setSelected(null)} returnFocus={receivableTrigger} />
  </div>
}
