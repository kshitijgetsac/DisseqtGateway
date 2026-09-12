import React, { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { api } from './api.js'
import { Icon } from './ui.jsx'
import Overview from './pages/Overview.jsx'
import Playground from './pages/Playground.jsx'
import Approvals from './pages/Approvals.jsx'
import Agents from './pages/Agents.jsx'
import Tools from './pages/Tools.jsx'
import Policies from './pages/Policies.jsx'
import Audit from './pages/Audit.jsx'
import Replay from './pages/Replay.jsx'
import Budgets from './pages/Budgets.jsx'

const ADMIN_ID = '00000000-0000-0000-0000-000000000001'
const REVIEWER_ID = '00000000-0000-0000-0000-000000000002'

const nav = [
  { id: 'overview', label: 'Overview', icon: 'overview' },
  { id: 'playground', label: 'Agent playground', icon: 'playground' },
  { id: 'approvals', label: 'Approvals', icon: 'approval' },
  { id: 'agents', label: 'Agents', icon: 'agents' },
  { id: 'tools', label: 'Tools', icon: 'tools' },
  { id: 'policies', label: 'Policy versions', icon: 'policy' },
  { id: 'audit', label: 'Audit explorer', icon: 'audit' },
  { id: 'replay', label: 'Policy replay', icon: 'replay' },
  { id: 'budgets', label: 'Usage controls', icon: 'budgets' },
]

const AppContext = createContext(null)
export const useApp = () => useContext(AppContext)

function useHashPage() {
  const read = () => window.location.hash.slice(1) || 'overview'
  const [page, setPage] = useState(read)
  useEffect(() => {
    const onHash = () => setPage(read())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  const navigate = value => { window.location.hash = value }
  return [nav.some(x => x.id === page) ? page : 'overview', navigate]
}

function App() {
  const [page, navigate] = useHashPage()
  const [userId, setUserId] = useState(localStorage.getItem('demoUserId') || ADMIN_ID)
  const [users, setUsers] = useState([])
  const [pending, setPending] = useState(0)
  const [toast, setToast] = useState(null)
  const [mobileNav, setMobileNav] = useState(false)

  const notify = (message, tone = 'success') => {
    setToast({ message, tone, key: Date.now() })
    window.setTimeout(() => setToast(current => current?.message === message ? null : current), 3500)
  }

  const loadShell = async () => {
    try {
      const [people, approvals] = await Promise.all([
        api('/users', { userId }),
        api('/approvals?status=PENDING&limit=1', { userId }),
      ])
      setUsers(people)
      setPending(approvals.items.length ? (approvals.next_cursor ? '1+' : approvals.items.length) : 0)
    } catch { /* individual pages surface connection errors */ }
  }

  useEffect(() => { localStorage.setItem('demoUserId', userId); loadShell() }, [userId, page])

  const context = useMemo(() => ({ userId, users, api: (path, options = {}) => api(path, { userId, ...options }), notify, navigate, refreshShell: loadShell }), [userId, users])
  const active = nav.find(item => item.id === page)
  const pages = { overview: Overview, playground: Playground, approvals: Approvals, agents: Agents, tools: Tools, policies: Policies, audit: Audit, replay: Replay, budgets: Budgets }
  const Page = pages[page]

  return <AppContext.Provider value={context}>
    <div className="app-shell">
      <aside className={`sidebar ${mobileNav ? 'sidebar-open' : ''}`}>
        <div className="brand"><div className="brand-mark">D</div><div><strong>Disseqt</strong><span>Governance gateway</span></div></div>
        <div className="nav-label">Workspace</div>
        <nav>{nav.map(item => <a key={item.id} href={`#${item.id}`} className={page === item.id ? 'active' : ''} onClick={() => setMobileNav(false)}><Icon name={item.icon}/><span>{item.label}</span>{item.id === 'approvals' && pending ? <b className="nav-count">{pending}</b> : null}</a>)}</nav>
        <div className="sidebar-foot"><div className="status-dot"/><div><strong>Local environment</strong><span>PostgreSQL-backed POC</span></div></div>
      </aside>
      {mobileNav && <button className="nav-scrim" aria-label="Close menu" onClick={() => setMobileNav(false)}/>}
      <main className="main-panel">
        <header className="topbar">
          <button className="mobile-menu" onClick={() => setMobileNav(true)} aria-label="Open menu">☰</button>
          <div className="breadcrumb"><span>Security workspace</span><Icon name="chevron" size={14}/><strong>{active.label}</strong></div>
          <div className="topbar-actions">
            <span className="live-pill"><i/>System live</span>
            <select aria-label="Demo identity" value={userId} onChange={e => setUserId(e.target.value)}>
              {(users.length ? users : [{ id: ADMIN_ID, name: 'Demo Admin', role: 'ADMIN' }, { id: REVIEWER_ID, name: 'Demo Reviewer', role: 'REVIEWER' }]).map(user => <option key={user.id} value={user.id}>{user.name} · {user.role}</option>)}
            </select>
          </div>
        </header>
        <div className="page"><Page /></div>
      </main>
      {toast && <div key={toast.key} className={`toast toast-${toast.tone}`}><Icon name={toast.tone === 'error' ? 'alert' : 'check'}/>{toast.message}</div>}
    </div>
  </AppContext.Provider>
}

export default App
