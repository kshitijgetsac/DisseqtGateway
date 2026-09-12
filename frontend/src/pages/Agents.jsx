import React, { useEffect, useState } from 'react'
import { useApp } from '../App.jsx'
import { Badge, CopyId, Empty, ErrorBox, Field, Icon, Loading, Modal, SectionTitle } from '../ui.jsx'

export default function Agents() {
  const { api, notify, users } = useApp()
  const [agents, setAgents] = useState(null)
  const [tools, setTools] = useState([])
  const [error, setError] = useState(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [name, setName] = useState('')
  const [ownerId, setOwnerId] = useState('00000000-0000-0000-0000-000000000001')
  const [selectedTools, setSelectedTools] = useState([])
  const [newKey, setNewKey] = useState(null)
  const load = () => Promise.all([api('/agents'), api('/tools')]).then(([a, t]) => { setAgents(a); setTools(t) }).catch(setError)
  useEffect(() => { load() }, [])
  const create = async e => {
    e.preventDefault()
    try { const agent = await api('/agents', { method: 'POST', body: { name, owner_id: ownerId } }); setCreateOpen(false); setName(''); setNewKey(agent.api_key); notify('Agent registered'); load() }
    catch (err) { notify(`${err.code}: ${err.message}`, 'error') }
  }
  const toggle = async agent => {
    try { await api(`/agents/${agent.id}/${agent.active ? 'deactivate' : 'activate'}`, { method: 'POST' }); notify(`Agent ${agent.active ? 'disabled' : 'activated'}`); load() }
    catch (err) { notify(err.message, 'error') }
  }
  const openPermissions = agent => { setEditing(agent); setSelectedTools(agent.tool_ids) }
  const savePermissions = async () => {
    try { await api(`/agents/${editing.id}/permissions`, { method: 'PUT', body: { tool_ids: selectedTools } }); notify('Permissions replaced'); setEditing(null); load() }
    catch (err) { notify(err.message, 'error') }
  }
  const rotate = async agent => {
    try { const result = await api(`/agents/${agent.id}/rotate-key`, { method: 'POST' }); setNewKey(result.api_key); notify('Agent key rotated') }
    catch (err) { notify(err.message, 'error') }
  }
  return <>
    <SectionTitle eyebrow="Registry" title="Agents" description="Register identities, control lifecycle, and grant only the tool actions each agent needs." actions={<button className="button button-primary" onClick={() => setCreateOpen(true)}><Icon name="plus"/>Register agent</button>}/>
    {error ? <ErrorBox error={error} retry={load}/> : agents === null ? <Loading/> : agents.length ? <div className="card-grid">{agents.map(agent => <article className="entity-card" key={agent.id}><div className="entity-top"><div className="entity-icon"><Icon name="agents"/></div><Badge value={agent.active ? 'ACTIVE' : 'INACTIVE'}/></div><h2>{agent.name}</h2><div className="entity-id"><span>Agent ID</span><CopyId value={agent.id}/></div><div className="permission-list"><span>Granted tools</span>{agent.tool_ids.length ? agent.tool_ids.map(id => <small key={id}>{tools.find(t => t.id === id)?.name || id.slice(0, 8)}</small>) : <small className="muted">No tool permissions</small>}</div><div className="card-actions"><button className="button button-small" onClick={() => openPermissions(agent)}>Permissions</button><button className="button button-ghost button-small" onClick={() => rotate(agent)}>Rotate key</button><button className="text-button" onClick={() => toggle(agent)}>{agent.active ? 'Disable' : 'Activate'}</button></div></article>)}</div> : <Empty title="No agents registered" action={<button className="button button-primary" onClick={() => setCreateOpen(true)}>Register first agent</button>}/>}
    {createOpen && <Modal title="Register agent" subtitle="The API key is shown once after creation." onClose={() => setCreateOpen(false)} footer={<><button className="button button-ghost" onClick={() => setCreateOpen(false)}>Cancel</button><button className="button button-primary" form="create-agent">Register</button></>}><form id="create-agent" onSubmit={create} className="form-stack"><Field label="Agent name" required><input autoFocus value={name} onChange={e => setName(e.target.value)} placeholder="finance-assistant" required/></Field><Field label="Owner" required><select value={ownerId} onChange={e => setOwnerId(e.target.value)}>{users.map(user => <option key={user.id} value={user.id}>{user.name}</option>)}</select></Field></form></Modal>}
    {editing && <Modal title={`Permissions · ${editing.name}`} subtitle="This operation replaces the complete permission set." onClose={() => setEditing(null)} footer={<><button className="button button-ghost" onClick={() => setEditing(null)}>Cancel</button><button className="button button-primary" onClick={savePermissions}>Save permissions</button></>}><div className="check-list">{tools.map(tool => <label key={tool.id}><input type="checkbox" checked={selectedTools.includes(tool.id)} onChange={e => setSelectedTools(current => e.target.checked ? [...current, tool.id] : current.filter(id => id !== tool.id))}/><span><strong>{tool.name}</strong><small>{tool.risk} risk · {tool.data_classification}</small></span></label>)}</div></Modal>}
    {newKey && <Modal title="Copy the agent key now" subtitle="Only its SHA-256 digest is retained by the gateway." onClose={() => setNewKey(null)} footer={<button className="button button-primary" onClick={() => setNewKey(null)}>I saved it</button>}><div className="secret-box"><code>{newKey}</code><button className="button button-small" onClick={() => navigator.clipboard?.writeText(newKey)}>Copy</button></div></Modal>}
  </>
}
