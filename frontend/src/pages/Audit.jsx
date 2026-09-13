import React, { useEffect, useState } from 'react'
import { useApp } from '../App.jsx'
import { Badge, CopyId, Empty, ErrorBox, Icon, Loading, Modal, SectionTitle, fmtTime, pretty } from '../ui.jsx'
import { query } from '../api.js'

export default function Audit() {
  const { api } = useApp()
  const [filters, setFilters] = useState({ event_type: '', decision: '', risk: '', q: '' })
  const [events, setEvents] = useState(null)
  const [selected, setSelected] = useState(null)
  const [error, setError] = useState(null)
  const load = () => { setError(null); api(`/audit-events${query({ ...filters, limit: 100 })}`).then(d => setEvents(d.items)).catch(setError) }
  useEffect(() => { load() }, [])
  const submit = e => { e.preventDefault(); load() }
  return <>
    <SectionTitle eyebrow="Append-oriented history" title="Audit explorer" description="Trace every decision from authenticated proposal to human review and execution outcome." actions={<button className="button button-ghost" onClick={load}><Icon name="refresh"/>Refresh</button>}/>
    <form className="filter-bar" onSubmit={submit}><div className="search-control"><Icon name="search"/><input value={filters.q} onChange={e => setFilters({ ...filters, q: e.target.value })} placeholder="Search action ID or reason code" aria-label="Search audit events by action ID or reason code"/></div><select value={filters.event_type} onChange={e => setFilters({ ...filters, event_type: e.target.value })}><option value="">All event types</option>{['POLICY_EVALUATED','POLICY_REEVALUATED','POLICY_REPLAYED','APPROVAL_REQUESTED','APPROVAL_APPROVED','APPROVAL_REJECTED','APPROVAL_EXPIRED','AUTHORIZATION_FAILED','EXECUTION_AUTHORIZATION_REVOKED','EXECUTION_JOB_CLEANED_UP','JOB_CLAIMED','EXECUTION_SUCCEEDED','EXECUTION_FAILED'].map(x => <option key={x}>{x}</option>)}</select><select value={filters.decision} onChange={e => setFilters({ ...filters, decision: e.target.value })}><option value="">All decisions</option><option>ALLOW</option><option>REQUIRE_APPROVAL</option><option>DENY</option></select><select value={filters.risk} onChange={e => setFilters({ ...filters, risk: e.target.value })}><option value="">All risks</option><option>LOW</option><option>MEDIUM</option><option>HIGH</option></select><button className="button button-primary">Apply filters</button></form>
    <section className="panel">{error ? <ErrorBox error={error} retry={load}/> : events === null ? <Loading/> : events.length ? <div className="table-wrap"><table><thead><tr><th>Time</th><th>Event</th><th>Request</th><th>Decision</th><th>Risk</th><th>Reason</th><th/></tr></thead><tbody>{events.map(event => <tr key={event.id}><td className="muted nowrap">{fmtTime(event.created_at)}</td><td><strong>{event.event_type.replaceAll('_', ' ')}</strong><small className="cell-note">{event.actor_type}</small></td><td><CopyId value={event.request_id}/></td><td>{event.decision ? <Badge value={event.decision}/> : '—'}</td><td>{event.risk ? <Badge value={event.risk}/> : '—'}</td><td><code>{event.reason_code || '—'}</code></td><td><button className="button button-small" onClick={() => setSelected(event)}>Inspect</button></td></tr>)}</tbody></table></div> : <Empty title="No events match these filters" detail="Clear filters or run a playground scenario."/>}</section>
    {selected && <Modal wide title={selected.event_type.replaceAll('_', ' ')} subtitle={`Recorded ${fmtTime(selected.created_at)}`} onClose={() => setSelected(null)}><div className="review-grid"><div><span>Event ID</span><CopyId value={selected.id}/></div><div><span>Request</span><CopyId value={selected.request_id}/></div><div><span>Decision</span>{selected.decision ? <Badge value={selected.decision}/> : <strong>None</strong>}</div><div><span>Reason</span><code>{selected.reason_code || '—'}</code></div></div><label className="field"><span className="field-label">Redacted structured details</span><pre>{pretty(selected.details)}</pre></label></Modal>}
  </>
}
