import { useEffect, useMemo, useState } from 'react'
import { FileSearch, Info, KeyRound, Play, Search, ShieldAlert, ShieldCheck, UserRound } from 'lucide-react'
import claimsOpen from './data/claims_open.json'
import demoTokens from './data/demo_tokens.json'
import { assess } from './mockApi'
import { decodeJwt } from './jwt'

const REGIONS = ['NORTH', 'SOUTH', 'EAST', 'WEST']
const pretty = (s) => s.replace(/_/g, ' ')

function TokenPreview({ token }) {
  if (!token.trim()) return null
  const decoded = decodeJwt(token)
  if (!decoded) return <p className="token-preview bad">Not a readable JWT</p>
  const { sub, role, regions = [], exp } = decoded.payload
  return (
    <p className="token-preview">
      <span>Token says (unverified):</span> {sub} · {role} · {regions.join(', ') || 'no regions'} · exp{' '}
      {exp ? new Date(exp * 1000).toISOString().slice(0, 10) : '—'}
    </p>
  )
}

function Result({ result }) {
  if (!result) return null
  const granted = result.status === 200
  return (
    <div className="result-stack" aria-live="polite">
      {granted ? (
        <div className="result granted">
          <ShieldCheck size={22} />
          <div>
            <strong>200 · Access granted</strong>
            <p>
              {result.body.user_id} ({pretty(result.body.role)}) may assess <b>{result.body.claim_id}</b> · {result.body.region}
            </p>
            <span className="pill pill-yellow">Simulated · agents not built yet</span>
          </div>
        </div>
      ) : (
        <div className="result refused">
          <ShieldAlert size={22} />
          <div>
            <strong>403 · Refused</strong>
            <p>{result.body.message} No claim data returned.</p>
          </div>
        </div>
      )}
      <div className="audit">
        <div className="audit-head">Audit log (server side, never sent to the user)</div>
        <code>{JSON.stringify(result.audit, null, 1)}</code>
      </div>
    </div>
  )
}

function RequestPanel({ claimId, setClaimId }) {
  const [userId, setUserId] = useState('u-adj-n1')
  const [group, setGroup] = useState('NORTH')
  const [token, setToken] = useState('')
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)

  // A result belongs to the inputs that produced it; drop it as soon as any input changes.
  useEffect(() => setResult(null), [claimId, userId, group, token])

  async function run(event) {
    event.preventDefault()
    setBusy(true)
    setResult(await assess({ claimId, userId, group, token }))
    setBusy(false)
  }

  return (
    <section className="panel request-panel">
      <div className="section-kicker"><FileSearch size={14} /> Request</div>
      <h2>Run a first assessment</h2>
      <p className="muted">Identity comes from the JWT. The typed User ID and Group must match it, or the request is refused.</p>

      <form onSubmit={run} className="request-form">
        <label>
          Claim ID
          <div className="input-wrap"><input value={claimId} onChange={(e) => setClaimId(e.target.value)} placeholder="CLM-2025-3001" spellCheck={false} /></div>
        </label>
        <div className="two-col">
          <label>
            User ID
            <div className="input-wrap"><UserRound size={16} /><input value={userId} onChange={(e) => setUserId(e.target.value)} placeholder="u-adj-n1" spellCheck={false} /></div>
          </label>
          <label>
            Group
            <div className="input-wrap select">
              <select value={group} onChange={(e) => setGroup(e.target.value)}>
                {REGIONS.map((r) => <option key={r}>{r}</option>)}
              </select>
            </div>
          </label>
        </div>
        <label>
          JWT
          <div className="input-wrap textarea"><KeyRound size={16} /><textarea rows={4} value={token} onChange={(e) => setToken(e.target.value)} placeholder="Paste a token, or pick a demo token below" spellCheck={false} /></div>
        </label>
        <TokenPreview token={token} />
        <div className="demo-box">
          Demo tokens (fill the JWT only)
          <div className="demo-chips">
            {demoTokens.map((t) => (
              <button type="button" key={t.label} onClick={() => setToken(t.token)} title={t.user_id}>{t.label}</button>
            ))}
          </div>
        </div>
        <button className="button primary full" type="submit" disabled={busy}>
          <Play size={16} /> {busy ? 'Checking…' : 'Run assessment'}
        </button>
      </form>
      <Result result={result} />
    </section>
  )
}

function ClaimsPanel({ selected, onSelect }) {
  const [query, setQuery] = useState('')
  const [region, setRegion] = useState('ALL')
  const rows = useMemo(() => {
    const q = query.trim().toLowerCase()
    return claimsOpen.filter((c) =>
      (region === 'ALL' || c.region === region) &&
      (!q || [c.claim_id, c.adjuster_name, c.assigned_adjuster, c.vehicle, c.loss_type].some((v) => v.toLowerCase().includes(q))))
  }, [query, region])

  return (
    <section className="panel claims-panel">
      <div className="claims-head">
        <div>
          <div className="section-kicker">Open claims</div>
          <h2>{rows.length} of {claimsOpen.length} open</h2>
        </div>
        <div className="glossary-search"><Search size={16} /><input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search claim, adjuster, vehicle" /></div>
      </div>
      <div className="filter-row">
        {['ALL', ...REGIONS].map((r) => (
          <button key={r} type="button" className={r === region ? 'active' : ''} onClick={() => setRegion(r)}>{r === 'ALL' ? 'All regions' : r}</button>
        ))}
      </div>
      <p className="data-notice"><Info size={14} /> Demo view: lists every synthetic claim. In the real system this list comes from the backend, filtered to the claims the token is entitled to.</p>
      <div className="table-scroll">
        <table className="claims-table">
          <thead><tr><th>Claim</th><th>Region</th><th>Loss</th><th>Date</th><th>Adjuster</th></tr></thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.claim_id} className={c.claim_id === selected ? 'selected' : ''} onClick={() => onSelect(c.claim_id)}>
                <td><button type="button" className="claim-link" onClick={() => onSelect(c.claim_id)}>{c.claim_id}</button><small>{c.vehicle}</small></td>
                <td><span className="region-tag">{c.region}</span></td>
                <td>{pretty(c.loss_type)}</td>
                <td className="nowrap">{c.loss_at.slice(0, 10)}</td>
                <td><strong>{c.adjuster_name}</strong><small>{c.assigned_adjuster}</small></td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={5} className="empty">No open claims match.</td></tr>}
          </tbody>
        </table>
      </div>
    </section>
  )
}

export default function App() {
  const [claimId, setClaimId] = useState('CLM-2025-3001')
  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand"><span className="brand-mark">CS</span> ClaimSense</div>
        <div className="header-context">Adjuster console · synthetic data</div>
        <span className="demo-badge">Simulated backend</span>
      </header>
      <main className="split">
        <RequestPanel claimId={claimId} setClaimId={setClaimId} />
        <ClaimsPanel selected={claimId.trim().toUpperCase()} onSelect={setClaimId} />
      </main>
    </div>
  )
}
