import React, { useEffect, useState } from 'react'
import { useApp } from '../App.jsx'
import { Badge, ErrorBox, Field, Icon, SectionTitle } from '../ui.jsx'

export default function Replay() {
  const { api, notify } = useApp()
  const [requestId, setRequestId] = useState('')
  const [versions, setVersions] = useState([])
  const [target, setTarget] = useState('')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [running, setRunning] = useState(false)
  useEffect(() => { api('/policy-versions').then(rows => { setVersions(rows); if (rows.length) setTarget(rows[rows.length - 1].id) }).catch(setError) }, [])
  const run = async e => { e.preventDefault(); setRunning(true); setError(null); setResult(null); try { const data = await api(`/requests/${requestId}/replays`, { method: 'POST', body: { target_policy_version_id: target } }); setResult(data); notify('Replay completed without execution') } catch (err) { setError(err); notify(err.message, 'error') } finally { setRunning(false) } }
  return <>
    <SectionTitle eyebrow="Safe what-if analysis" title="Policy replay" description="Evaluate an immutable historical request against another policy version without releasing a job."/>
    <div className="replay-grid"><form className="panel form-panel form-stack" onSubmit={run}><Field label="Historical request ID" hint="Copy an ID from the dashboard or audit explorer." required><input value={requestId} onChange={e => setRequestId(e.target.value)} placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" required/></Field><Field label="Target policy version" required><select value={target} onChange={e => setTarget(e.target.value)} required>{versions.map(version => <option key={version.id} value={version.id}>Version {version.version} · {version.published ? 'published' : 'draft'}</option>)}</select></Field><div className="replay-safety"><Icon name="policy"/><div><strong>Evaluation-only route</strong><p>This endpoint cannot create an approval, job, or tool execution.</p></div></div><button className="button button-primary button-wide" disabled={running}>{running ? 'Evaluating…' : <>Run policy replay<Icon name="replay"/></>}</button></form><section className="panel comparison-panel">{error ? <ErrorBox error={error}/> : result ? <><div className="no-execution"><Icon name="check"/><span>Execution performed: <strong>no</strong></span></div><div className="comparison"><div><span>Original</span><h3>Policy v{result.original.policy_version}</h3><Badge value={result.original.decision}/></div><Icon name="arrow" size={28}/><div><span>Replay</span><h3>Policy v{result.replay.policy_version}</h3><Badge value={result.replay.decision}/><small>{result.replay.reason_code}</small></div></div></> : <div className="result-placeholder"><div className="shield-orbit"><Icon name="replay" size={42}/></div><h3>Compare policy outcomes</h3><p>Replay preserves the original request facts and records a clearly labelled evaluation event.</p></div>}</section></div>
  </>
}
