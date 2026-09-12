import React, { useEffect, useState } from 'react'
import { useApp } from '../App.jsx'
import { Badge, CopyId, Empty, ErrorBox, Field, Icon, Loading, Modal, SectionTitle, pretty } from '../ui.jsx'

const defaultSchema = JSON.stringify({ type: 'object', properties: { query: { type: 'string' } }, required: ['query'], additionalProperties: false }, null, 2)

export default function Tools() {
  const { api, notify } = useApp()
  const [tools, setTools] = useState(null)
  const [error, setError] = useState(null)
  const [view, setView] = useState(null)
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState({ name: '', adapter_name: 'documents_search', risk: 'LOW', data_classification: 'INTERNAL', schema: defaultSchema })
  const load = () => api('/tools').then(setTools).catch(setError)
  useEffect(() => { load() }, [])
  const toggle = async tool => { try { await api(`/tools/${tool.id}/${tool.active ? 'deactivate' : 'activate'}`, { method: 'POST' }); notify(`Tool ${tool.active ? 'disabled' : 'activated'}`); load() } catch (err) { notify(err.message, 'error') } }
  const create = async e => {
    e.preventDefault()
    try { await api('/tools', { method: 'POST', body: { ...form, schema: JSON.parse(form.schema) } }); setCreating(false); notify('Tool registered'); load() }
    catch (err) { notify(err instanceof SyntaxError ? 'Schema must be valid JSON' : `${err.code}: ${err.message}`, 'error') }
  }
  return <>
    <SectionTitle eyebrow="Registry" title="Tools" description="Every callable action has a closed schema, trusted metadata, and an allowlisted adapter." actions={<button className="button button-primary" onClick={() => setCreating(true)}><Icon name="plus"/>Register tool</button>}/>
    {error ? <ErrorBox error={error} retry={load}/> : tools === null ? <Loading/> : tools.length ? <section className="panel"><div className="table-wrap"><table><thead><tr><th>Tool action</th><th>Adapter</th><th>Risk</th><th>Data class</th><th>Status</th><th/></tr></thead><tbody>{tools.map(tool => <tr key={tool.id}><td><strong>{tool.name}</strong><small className="cell-note"><CopyId value={tool.id}/></small></td><td><code>{tool.adapter_name}</code></td><td><Badge value={tool.risk}/></td><td><Badge value={tool.data_classification}/></td><td><Badge value={tool.active ? 'ACTIVE' : 'INACTIVE'}/></td><td className="row-actions"><button className="button button-small" onClick={() => setView(tool)}>Inspect</button><button className="text-button" onClick={() => toggle(tool)}>{tool.active ? 'Disable' : 'Activate'}</button></td></tr>)}</tbody></table></div></section> : <Empty title="No tools registered"/>}
    {view && <Modal wide title={view.name} subtitle={`Adapter ${view.adapter_name}`} onClose={() => setView(null)}><div className="review-grid"><div><span>Risk</span><Badge value={view.risk}/></div><div><span>Classification</span><Badge value={view.data_classification}/></div><div><span>Status</span><Badge value={view.active ? 'ACTIVE' : 'INACTIVE'}/></div><div><span>Tool ID</span><CopyId value={view.id}/></div></div><label className="field"><span className="field-label">Registered JSON Schema</span><pre>{pretty(view.schema)}</pre></label></Modal>}
    {creating && <Modal wide title="Register tool action" subtitle="Adapters are intentionally limited to the three POC mock implementations." onClose={() => setCreating(false)} footer={<><button className="button button-ghost" onClick={() => setCreating(false)}>Cancel</button><button className="button button-primary" form="create-tool">Register tool</button></>}><form id="create-tool" className="form-stack" onSubmit={create}><div className="form-row"><Field label="Tool name" required><input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} placeholder="documents.lookup" required/></Field><Field label="Allowlisted adapter"><select value={form.adapter_name} onChange={e => setForm({ ...form, adapter_name: e.target.value })}><option value="documents_search">documents_search</option><option value="customers_update">customers_update</option><option value="messages_send">messages_send</option></select></Field></div><div className="form-row"><Field label="Risk"><select value={form.risk} onChange={e => setForm({ ...form, risk: e.target.value })}>{['LOW','MEDIUM','HIGH'].map(x => <option key={x}>{x}</option>)}</select></Field><Field label="Data classification"><select value={form.data_classification} onChange={e => setForm({ ...form, data_classification: e.target.value })}>{['PUBLIC','INTERNAL','CONFIDENTIAL','RESTRICTED'].map(x => <option key={x}>{x}</option>)}</select></Field></div><Field label="Closed JSON Schema" hint="additionalProperties must be false."><textarea className="code-input" rows="12" value={form.schema} onChange={e => setForm({ ...form, schema: e.target.value })}/></Field></form></Modal>}
  </>
}
