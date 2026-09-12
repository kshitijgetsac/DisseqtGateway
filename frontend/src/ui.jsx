import React from 'react'

const paths = {
  overview: <><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></>,
  agents: <><circle cx="12" cy="8" r="4"/><path d="M4 21c0-4.2 3.3-7 8-7s8 2.8 8 7"/></>,
  tools: <><path d="M14 7a5 5 0 0 0-7 7l-4 4a2 2 0 0 0 3 3l4-4a5 5 0 0 0 7-7l-3 3-3-3z"/></>,
  policy: <><path d="M12 2 4 6v6c0 5 3.5 8.5 8 10 4.5-1.5 8-5 8-10V6z"/><path d="m9 12 2 2 4-4"/></>,
  approval: <><rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4.5V3h6v1.5M9 12l2 2 4-4"/></>,
  audit: <><path d="M4 4h16v16H4zM8 9h8M8 13h8M8 17h5"/></>,
  replay: <><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 7v5l3 2"/></>,
  playground: <><path d="m8 4-6 8 6 8M16 4l6 8-6 8M14 3l-4 18"/></>,
  budgets: <><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 9h18M7 15h3"/></>,
  chevron: <path d="m9 18 6-6-6-6"/>,
  refresh: <><path d="M20 11a8 8 0 1 0-2 6M20 4v7h-7"/></>,
  plus: <path d="M12 5v14M5 12h14"/>,
  close: <path d="M5 5l14 14M19 5 5 19"/>,
  search: <><circle cx="11" cy="11" r="7"/><path d="m16.5 16.5 4.5 4.5"/></>,
  arrow: <path d="M5 12h14m-6-6 6 6-6 6"/>,
  check: <path d="m4 12 5 5L20 6"/>,
  alert: <><path d="M12 3 2 21h20z"/><path d="M12 9v5m0 3h.01"/></>,
}

export function Icon({ name, size = 18, className = '' }) {
  return <svg className={className} width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name] || paths.overview}</svg>
}

export function Badge({ value }) {
  const normalized = String(value || 'UNKNOWN').toLowerCase().replaceAll('_', '-')
  return <span className={`badge badge-${normalized}`}>{String(value || 'UNKNOWN').replaceAll('_', ' ')}</span>
}

export function Empty({ title = 'Nothing here yet', detail, action }) {
  return <div className="empty"><div className="empty-symbol">◇</div><h3>{title}</h3>{detail && <p>{detail}</p>}{action}</div>
}

export function Loading() { return <div className="loading"><span className="spinner"/>Loading workspace…</div> }

export function ErrorBox({ error, retry }) {
  return <div className="error-box"><Icon name="alert"/><div><strong>{error?.code || 'Could not load data'}</strong><p>{error?.message || 'Please try again.'}</p></div>{retry && <button className="button button-ghost" onClick={retry}>Retry</button>}</div>
}

export function SectionTitle({ eyebrow, title, description, actions }) {
  return <div className="page-heading"><div>{eyebrow && <div className="eyebrow">{eyebrow}</div>}<h1>{title}</h1>{description && <p>{description}</p>}</div>{actions && <div className="heading-actions">{actions}</div>}</div>
}

export function Field({ label, hint, children, required }) {
  return <label className="field"><span className="field-label">{label}{required && <em> *</em>}</span>{children}{hint && <small>{hint}</small>}</label>
}

export function Modal({ title, subtitle, onClose, children, footer, wide = false }) {
  return <div className="modal-backdrop" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}><div className={`modal ${wide ? 'modal-wide' : ''}`} role="dialog" aria-modal="true" aria-label={title}><div className="modal-head"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div><button className="icon-button" aria-label="Close" onClick={onClose}><Icon name="close"/></button></div><div className="modal-body">{children}</div>{footer && <div className="modal-footer">{footer}</div>}</div></div>
}

export function shortId(value) { return value ? `${String(value).slice(0, 8)}…` : '—' }
export function fmtTime(value) { return value ? new Intl.DateTimeFormat('en-IN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value)) : '—' }
export function pretty(value) { return JSON.stringify(value, null, 2) }

export function CopyId({ value }) {
  return <button className="copy-id" title="Copy ID" onClick={() => navigator.clipboard?.writeText(value)}>{shortId(value)}</button>
}
