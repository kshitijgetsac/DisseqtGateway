import React, { useEffect, useState } from 'react'
import { useApp } from '../App.jsx'
import { Badge, ErrorBox, Field, Icon, Loading, Modal, SectionTitle, pretty } from '../ui.jsx'

const starter = JSON.stringify([{ id: 'new-high-risk-rule', priority: 70, effect: 'REQUIRE_APPROVAL', reason_code: 'HIGH_RISK_APPROVAL', reason: 'High-risk actions need human review.', conditions: [{ field: 'risk', op: 'eq', value: 'HIGH' }] }, { id: 'default-allow', priority: 1, effect: 'ALLOW', reason_code: 'LOW_RISK_ALLOWED', reason: 'Authorized low-risk action is allowed.', conditions: [] }], null, 2)

export default function Policies() {
  const { api, notify } = useApp()
  const [versions, setVersions] = useState(null)
  const [policies, setPolicies] = useState([])
  const [selected, setSelected] = useState(null)
  const [creating, setCreating] = useState(false)
  const [rules, setRules] = useState(starter)
  const [error, setError] = useState(null)
  const load = () => Promise.all([api('/policy-versions'), api('/policies')]).then(([v, p]) => { setVersions(v); setPolicies(p); if (!selected && v.length) setSelected(v[v.length - 1]) }).catch(setError)
  useEffect(() => { load() }, [])
  const activeId = policies[0]?.active_version_id
  const create = async e => { e.preventDefault(); try { const result = await api('/policy-versions', { method: 'POST', body: { rules: JSON.parse(rules) } }); notify(`Policy version ${result.version} created`); setCreating(false); setSelected(result); load() } catch (err) { notify(err instanceof SyntaxError ? 'Rules must be valid JSON' : `${err.code}: ${err.message}`, 'error') } }
  const activate = async version => { try { const result = await api(`/policy-versions/${version.id}/activate`, { method: 'POST' }); notify(`Policy v${version.version} activated · ${result.changed_seeded_decisions.length} changed decisions`); load() } catch (err) { notify(err.message, 'error') } }
  return <>
    <SectionTitle eyebrow="Deterministic controls" title="Policy versions" description="Inspect immutable rules, create a draft version, and atomically choose the active policy." actions={<button className="button button-primary" onClick={() => setCreating(true)}><Icon name="plus"/>New version</button>}/>
    {error ? <ErrorBox error={error} retry={load}/> : versions === null ? <Loading/> : <div className="policy-layout"><aside className="version-list">{versions.map(version => <button key={version.id} className={selected?.id === version.id ? 'selected' : ''} onClick={() => setSelected(version)}><span>Version {version.version}</span>{version.id === activeId ? <Badge value="ACTIVE"/> : <small>{version.published ? 'Published' : 'Draft'}</small>}<em>{version.rules.length} rules</em></button>)}</aside>{selected && <section className="panel policy-detail"><div className="panel-head"><div><div className="eyebrow">Policy snapshot</div><h2>Version {selected.version}</h2><p>Highest numeric priority wins; tied effects resolve DENY, then REQUIRE APPROVAL, then ALLOW.</p></div>{selected.id === activeId ? <Badge value="ACTIVE"/> : <button className="button button-primary" onClick={() => activate(selected)}>Activate version</button>}</div><div className="rule-stack">{[...selected.rules].sort((a,b) => b.priority-a.priority).map(rule => <article className="rule" key={rule.id}><div className="rule-priority">{rule.priority}</div><div><div className="rule-head"><code>{rule.id}</code><Badge value={rule.effect}/></div><strong>{rule.reason}</strong><p>{rule.conditions.length ? rule.conditions.map(c => `${c.field} ${c.op} ${JSON.stringify(c.value)}`).join('  AND  ') : 'Matches all requests'}</p><small>{rule.reason_code}</small></div></article>)}</div></section>}</div>}
    {creating && <Modal wide title="Create policy version" subtitle="The new version remains inactive until it is explicitly activated." onClose={() => setCreating(false)} footer={<><button className="button button-ghost" onClick={() => setCreating(false)}>Cancel</button><button className="button button-primary" form="create-policy">Create draft</button></>}><form id="create-policy" onSubmit={create}><Field label="Policy rules JSON" hint="Stable IDs, priorities, effects, reason codes, and allowlisted condition fields are validated by the API."><textarea className="code-input" rows="20" value={rules} onChange={e => setRules(e.target.value)}/></Field></form></Modal>}
  </>
}
