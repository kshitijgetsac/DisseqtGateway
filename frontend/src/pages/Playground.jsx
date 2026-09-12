import React, { useEffect, useMemo, useState } from 'react'
import { useApp } from '../App.jsx'
import { Badge, ErrorBox, Icon, SectionTitle, pretty } from '../ui.jsx'

const scenarios = [
  ['SAFE_INTERNAL_DOCUMENT_SEARCH', 'Safe internal search', 'A low-risk document query that should be allowed.'],
  ['UNAUTHORIZED_CUSTOMER_UPDATE', 'Unauthorized update', 'Use the limited agent to show registry authorization winning.'],
  ['HIGH_RISK_CUSTOMER_UPDATE', 'High-risk customer update', 'A sensitive mutation that requires human approval.'],
  ['INDIRECT_PROMPT_INJECTION', 'Indirect prompt injection', 'Retrieved content tries to exfiltrate confidential data.'],
  ['CONFIDENTIAL_EXTERNAL_SEND', 'External confidential send', 'A classified artifact is proposed for an external destination.'],
  ['MALFORMED_TOOL_ARGUMENTS', 'Malformed tool arguments', 'The model proposes fields outside the registered schema.'],
  ['PROVIDER_UNAVAILABLE', 'Provider unavailable', 'The deterministic provider simulates an outage.'],
]

export default function Playground() {
  const { api, notify, navigate } = useApp()
  const [agents, setAgents] = useState([])
  const [scenario, setScenario] = useState(scenarios[0][0])
  const [agentId, setAgentId] = useState('00000000-0000-0000-0000-000000000010')
  const [prompt, setPrompt] = useState('Find the internal customer report')
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [running, setRunning] = useState(false)
  useEffect(() => { api('/agents').then(setAgents).catch(setError) }, [])
  useEffect(() => {
    if (scenario === 'UNAUTHORIZED_CUSTOMER_UPDATE') setAgentId('00000000-0000-0000-0000-000000000011')
    else setAgentId('00000000-0000-0000-0000-000000000010')
    const selected = scenarios.find(item => item[0] === scenario)
    setPrompt(selected?.[2] || '')
  }, [scenario])
  const selected = useMemo(() => scenarios.find(item => item[0] === scenario), [scenario])
  const run = async e => {
    e.preventDefault(); setRunning(true); setError(null); setResult(null)
    try {
      const data = await api('/agent-runs', { method: 'POST', body: { agent_id: agentId, user_id: agents.find(a => a.id === agentId)?.owner_id || '00000000-0000-0000-0000-000000000001', prompt, scenario } })
      setResult(data); notify(`Gateway returned ${data.gateway_request.decision.toLowerCase().replace('_', ' ')}`)
    } catch (err) { setError(err); notify(err.code || 'Scenario failed', 'error') }
    finally { setRunning(false) }
  }
  return <>
    <SectionTitle eyebrow="Deterministic demonstration" title="Agent playground" description="Let the mock provider propose a tool call, then watch the same production gateway enforce it."/>
    <div className="playground-grid">
      <form className="panel form-panel" onSubmit={run}>
        <div className="scenario-list">{scenarios.map(([id, label, detail]) => <button type="button" key={id} onClick={() => setScenario(id)} className={scenario === id ? 'selected' : ''}><span className="radio-dot"/><span><strong>{label}</strong><small>{detail}</small></span></button>)}</div>
        <div className="form-stack">
          <label className="field"><span className="field-label">Acting agent</span><select value={agentId} onChange={e => setAgentId(e.target.value)}>{agents.map(agent => <option key={agent.id} value={agent.id}>{agent.name}{agent.active ? '' : ' · disabled'}</option>)}</select></label>
          <label className="field"><span className="field-label">Prompt shown to mock provider</span><textarea rows="4" value={prompt} onChange={e => setPrompt(e.target.value)}/><small>The scenario determines the proposal; the prompt remains visible for the demo narrative.</small></label>
          <div className="scenario-callout"><Icon name="alert"/><span>{selected?.[2]}</span></div>
          <button className="button button-primary button-wide" disabled={running}>{running ? <><span className="spinner small"/>Evaluating…</> : <>Run through gateway<Icon name="arrow"/></>}</button>
        </div>
      </form>
      <section className="panel result-panel"><div className="panel-head"><div><h2>Gateway decision</h2><p>Model proposal and enforced result.</p></div>{result && <Badge value={result.gateway_request.decision}/>}</div>
        {error ? <ErrorBox error={error}/> : result ? <div className="result-content"><div className="decision-hero"><span>Final decision</span><strong>{result.gateway_request.decision.replaceAll('_', ' ')}</strong><p>{result.gateway_request.reason}</p></div><div className="result-row"><span>Status</span><Badge value={result.gateway_request.status}/></div><div className="result-row"><span>Reason code</span><code>{result.gateway_request.reason_code}</code></div><div className="result-row"><span>Policy version</span><strong>v{result.gateway_request.policy.version}</strong></div><details><summary>Redacted model proposal</summary><pre>{pretty(result.model_output)}</pre></details>{result.gateway_request.approval_id && <button className="button button-primary button-wide" onClick={() => navigate('approvals')}>Open approval queue<Icon name="arrow"/></button>}</div> : <div className="result-placeholder"><div className="shield-orbit"><Icon name="policy" size={42}/></div><h3>Ready to evaluate</h3><p>Select a scenario to demonstrate that authorization and policy remain in control even when model output is unsafe.</p></div>}
      </section>
    </div>
  </>
}
