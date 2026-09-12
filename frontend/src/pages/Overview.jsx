import React, { useEffect, useState } from 'react'
import { useApp } from '../App.jsx'
import { Badge, CopyId, Empty, ErrorBox, Icon, Loading, SectionTitle, fmtTime } from '../ui.jsx'

export default function Overview() {
  const { api, navigate } = useApp()
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const load = () => { setError(null); api('/dashboard/summary').then(setData).catch(setError) }
  useEffect(() => { load() }, [])
  if (error) return <><SectionTitle eyebrow="Security posture" title="Gateway overview"/><ErrorBox error={error} retry={load}/></>
  if (!data) return <Loading/>
  const cards = [
    ['Denied actions', data.denied_actions_24h, 'Blocked during the last 24 hours', 'danger'],
    ['High-risk events', data.high_risk_events_24h, 'Observed during the last 24 hours', 'warning'],
    ['Pending approvals', data.pending_approvals, 'Waiting for a human decision', 'violet'],
    ['Queue depth', data.queue_depth, 'Pending or currently running', 'blue'],
  ]
  return <>
    <SectionTitle eyebrow="Security posture" title="Gateway overview" description="A concise view of policy decisions, human review, and durable execution." actions={<><button className="button button-ghost" onClick={load}><Icon name="refresh"/>Refresh</button><button className="button button-primary" onClick={() => navigate('playground')}>Run a scenario<Icon name="arrow"/></button></>}/>
    <div className="metric-grid">{cards.map(([label, value, detail, tone]) => <article className={`metric-card metric-${tone}`} key={label}><span>{label}</span><strong>{value}</strong><p>{detail}</p></article>)}</div>
    <div className="overview-grid">
      <section className="panel"><div className="panel-head"><div><h2>Recent decisions</h2><p>The latest actions evaluated by the active policy.</p></div><button className="text-button" onClick={() => navigate('audit')}>View audit <Icon name="arrow" size={14}/></button></div>
        {data.recent_decisions.length ? <div className="table-wrap"><table><thead><tr><th>Request</th><th>Decision</th><th>Reason</th><th>Received</th></tr></thead><tbody>{data.recent_decisions.map(row => <tr key={row.request_id}><td><CopyId value={row.request_id}/></td><td><Badge value={row.decision}/></td><td>{row.reason_code?.replaceAll('_', ' ')}</td><td className="muted">{fmtTime(row.created_at)}</td></tr>)}</tbody></table></div> : <Empty title="No decisions recorded" detail="Use the agent playground to send the first proposal through the gateway."/>}
      </section>
      <aside className="panel worker-panel"><div className="panel-head"><div><h2>Execution workers</h2><p>Heartbeat status for durable jobs.</p></div></div>
        {data.workers.length ? data.workers.map(worker => <div className="worker" key={worker.id}><div className={`worker-icon ${worker.healthy ? 'healthy' : ''}`}>W</div><div><strong>{worker.id}</strong><span>Last seen {fmtTime(worker.last_seen_at)}</span></div><Badge value={worker.healthy ? 'HEALTHY' : 'STALE'}/></div>) : <Empty title="No worker heartbeat" detail="Start the worker service to execute approved jobs."/>}
        <div className="trust-note"><Icon name="policy"/><div><strong>Default-deny boundary</strong><p>Model claims never grant permissions. Every action must pass registry authorization and deterministic policy.</p></div></div>
      </aside>
    </div>
  </>
}
