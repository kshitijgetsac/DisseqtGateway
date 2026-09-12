import React, { useEffect, useState } from 'react'
import { useApp } from '../App.jsx'
import { Badge, CopyId, Empty, ErrorBox, Icon, Loading, Modal, SectionTitle, fmtTime, pretty } from '../ui.jsx'

export default function Approvals() {
  const { api, notify, refreshShell } = useApp()
  const [status, setStatus] = useState('PENDING')
  const [rows, setRows] = useState(null)
  const [selected, setSelected] = useState(null)
  const [note, setNote] = useState('Reviewed destination, data classification, and policy findings.')
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)
  const load = () => { setError(null); api(`/approvals${status ? `?status=${status}` : ''}`).then(d => setRows(d.items)).catch(setError) }
  useEffect(load, [status])
  const resolve = async approve => {
    setSaving(true)
    try {
      await api(`/approvals/${selected.id}/${approve ? 'approve' : 'reject'}`, { method: 'POST', body: { note } })
      notify(`Request ${approve ? 'approved and queued' : 'rejected'}`); setSelected(null); load(); refreshShell()
    } catch (err) { notify(`${err.code}: ${err.message}`, 'error'); load() }
    finally { setSaving(false) }
  }
  return <>
    <SectionTitle eyebrow="Human control" title="Approval queue" description="Resolve sensitive actions transactionally. The first valid decision wins." actions={<button className="button button-ghost" onClick={load}><Icon name="refresh"/>Refresh</button>}/>
    <div className="segmented">{['PENDING', 'APPROVED', 'REJECTED', 'EXPIRED', ''].map(value => <button key={value || 'ALL'} className={status === value ? 'active' : ''} onClick={() => setStatus(value)}>{value || 'ALL'}</button>)}</div>
    <section className="panel">{error ? <ErrorBox error={error} retry={load}/> : rows === null ? <Loading/> : rows.length ? <div className="table-wrap"><table><thead><tr><th>Request</th><th>Tool</th><th>Risk</th><th>Reason</th><th>Expires</th><th/></tr></thead><tbody>{rows.map(row => <tr key={row.id}><td><CopyId value={row.request_id}/></td><td><strong>{row.tool}</strong><small className="cell-note">Agent {row.agent_id.slice(0, 8)}</small></td><td><Badge value={row.risk}/></td><td>{row.reason}</td><td>{fmtTime(row.expires_at)}</td><td><button className="button button-small" onClick={() => setSelected(row)}>Review</button></td></tr>)}</tbody></table></div> : <Empty title={`No ${status ? status.toLowerCase() : ''} approvals`} detail="Approval-required gateway decisions will appear here."/>}</section>
    {selected && <Modal wide title="Review requested action" subtitle={`Approval ${selected.id}`} onClose={() => setSelected(null)} footer={<><button className="button button-danger" disabled={saving} onClick={() => resolve(false)}>Reject</button><button className="button button-primary" disabled={saving} onClick={() => resolve(true)}><Icon name="check"/>Approve and queue</button></>}>
      <div className="review-grid"><div><span>Tool action</span><strong>{selected.tool}</strong></div><div><span>Risk</span><Badge value={selected.risk}/></div><div><span>Reason code</span><code>{selected.reason_code}</code></div><div><span>Expires</span><strong>{fmtTime(selected.expires_at)}</strong></div></div>
      <div className="policy-explanation"><Icon name="policy"/><div><strong>Policy explanation</strong><p>{selected.reason}</p></div></div>
      <label className="field"><span className="field-label">Redacted arguments</span><pre>{pretty(selected.arguments)}</pre></label>
      <label className="field"><span className="field-label">Decision note</span><textarea rows="3" value={note} onChange={e => setNote(e.target.value)}/></label>
    </Modal>}
  </>
}
