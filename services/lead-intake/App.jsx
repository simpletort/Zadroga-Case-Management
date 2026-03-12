import { useState, useEffect, useCallback } from 'react'
import { fetchCases, fetchDashboardStats, updateCaseStatus, fetchCase } from './services/firebaseService'

// ── Design tokens (inline for portability) ────────────────────────────────────
const S = {
  layout: { display: 'flex', minHeight: '100vh', background: '#0a0c0f' },
  sidebar: {
    width: 240, background: '#111418', borderRight: '1px solid #21262d',
    display: 'flex', flexDirection: 'column', position: 'fixed',
    top: 0, left: 0, height: '100vh', zIndex: 100,
  },
  main: { marginLeft: 240, flex: 1, display: 'flex', flexDirection: 'column', minHeight: '100vh' },
  header: {
    background: '#111418', borderBottom: '1px solid #21262d',
    padding: '16px 28px', display: 'flex', alignItems: 'center',
    justifyContent: 'space-between', position: 'sticky', top: 0, zIndex: 90,
  },
  content: { padding: '28px', flex: 1 },
}

const STATUS_COLORS = {
  'New Lead': '#388bfd', 'Screened': '#a371f7', 'Qualified': '#3fb950',
  'Disqualified': '#f85149', 'Active': '#58a6ff', 'Closed': '#484f58',
}
const VCF_COLORS = {
  eligible: '#3fb950', ineligible: '#f85149', needs_review: '#d29922', pending: '#8b949e',
}

function Badge({ label, color }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      padding: '2px 8px', borderRadius: 12, fontSize: 11, fontWeight: 600,
      background: color + '22', color, border: `1px solid ${color}44`,
      letterSpacing: '0.03em', textTransform: 'uppercase',
    }}>
      <span style={{ width: 5, height: 5, borderRadius: '50%', background: color }} />
      {label}
    </span>
  )
}

function StatCard({ label, value, color, sub }) {
  return (
    <div style={{
      background: '#161b22', border: '1px solid #21262d', borderRadius: 10,
      padding: '20px 24px', position: 'relative', overflow: 'hidden',
    }}>
      <div style={{
        position: 'absolute', top: 0, left: 0, right: 0, height: 2,
        background: color, opacity: 0.7,
      }} />
      <div style={{ color: '#8b949e', fontSize: 11, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>{label}</div>
      <div style={{ fontSize: 32, fontWeight: 700, color: '#e6edf3', fontFamily: "'IBM Plex Mono', monospace", lineHeight: 1 }}>{value ?? '—'}</div>
      {sub && <div style={{ color: '#8b949e', fontSize: 12, marginTop: 6 }}>{sub}</div>}
    </div>
  )
}

function Sidebar({ active, setActive }) {
  const items = [
    { id: 'dashboard', icon: '◈', label: 'Dashboard' },
    { id: 'leads', icon: '◎', label: 'All Leads' },
    { id: 'new', icon: '◉', label: 'New Lead', badge: null },
    { id: 'screened', icon: '◇', label: 'Screened' },
    { id: 'qualified', icon: '◆', label: 'Qualified' },
    { id: 'review', icon: '◈', label: 'Needs Review' },
  ]

  return (
    <div style={S.sidebar}>
      {/* Logo */}
      <div style={{ padding: '24px 20px 20px', borderBottom: '1px solid #21262d' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{
            width: 32, height: 32, background: 'linear-gradient(135deg, #d4a853, #9a7a3a)',
            borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 14, fontWeight: 700, color: '#0a0c0f',
          }}>Z</div>
          <div>
            <div style={{ fontFamily: "'DM Serif Display'", fontSize: 15, color: '#e6edf3', letterSpacing: '0.02em' }}>ZAD Legal</div>
            <div style={{ fontSize: 10, color: '#8b949e', letterSpacing: '0.05em' }}>LEAD MANAGEMENT</div>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav style={{ flex: 1, padding: '12px 8px' }}>
        {items.map(item => (
          <button key={item.id} onClick={() => setActive(item.id)} style={{
            width: '100%', display: 'flex', alignItems: 'center', gap: 10,
            padding: '8px 12px', borderRadius: 6, border: 'none', cursor: 'pointer',
            background: active === item.id ? '#1c2330' : 'transparent',
            color: active === item.id ? '#e6edf3' : '#8b949e',
            fontSize: 13, fontWeight: active === item.id ? 500 : 400,
            transition: 'all 0.15s', textAlign: 'left',
            borderLeft: active === item.id ? '2px solid #d4a853' : '2px solid transparent',
          }}>
            <span style={{ fontSize: 12, color: active === item.id ? '#d4a853' : '#484f58' }}>{item.icon}</span>
            {item.label}
          </button>
        ))}
      </nav>

      {/* Bottom */}
      <div style={{ padding: '12px 20px', borderTop: '1px solid #21262d' }}>
        <div style={{ fontSize: 11, color: '#484f58' }}>API v1.0.0 • Module 1</div>
      </div>
    </div>
  )
}

function Dashboard({ onViewCase }) {
  const [stats, setStats] = useState(null)
  const [recentCases, setRecentCases] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([fetchDashboardStats(), fetchCases()])
      .then(([s, { cases }]) => {
        setStats(s)
        setRecentCases(cases.slice(0, 8))
      })
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  const total = stats ? Object.values(stats).filter((_, i) => i < 6).reduce((a, b) => a + b, 0) : 0

  return (
    <div>
      <div style={{ marginBottom: 28 }}>
        <h1 style={{ fontFamily: "'DM Serif Display'", fontSize: 26, color: '#e6edf3', fontWeight: 400, marginBottom: 4 }}>
          Lead Dashboard
        </h1>
        <p style={{ color: '#8b949e', fontSize: 13 }}>Real-time overview of all incoming 9/11 VCF leads</p>
      </div>

      {loading ? (
        <div style={{ color: '#8b949e', padding: 40, textAlign: 'center' }}>Loading stats…</div>
      ) : (
        <>
          {/* Stats grid */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 12, marginBottom: 28 }}>
            <StatCard label="Total Cases" value={total} color="#d4a853" sub="All time" />
            <StatCard label="New Leads" value={stats?.['New Lead']} color="#388bfd" />
            <StatCard label="Screened" value={stats?.['Screened']} color="#a371f7" />
            <StatCard label="Qualified" value={stats?.['Qualified']} color="#3fb950" />
            <StatCard label="Disqualified" value={stats?.['Disqualified']} color="#f85149" />
            <StatCard label="VCF Eligible" value={stats?.eligible} color="#3fb950" sub="Passed screening" />
          </div>

          {/* Recent cases */}
          <div style={{ background: '#161b22', border: '1px solid #21262d', borderRadius: 10, overflow: 'hidden' }}>
            <div style={{ padding: '16px 20px', borderBottom: '1px solid #21262d', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ fontWeight: 600, color: '#e6edf3' }}>Recent Leads</span>
              <span style={{ fontSize: 11, color: '#8b949e' }}>Last 8 entries</span>
            </div>
            <CasesTable cases={recentCases} onView={onViewCase} compact />
          </div>
        </>
      )}
    </div>
  )
}

function CasesTable({ cases, onView, compact }) {
  if (!cases.length) return (
    <div style={{ padding: 40, textAlign: 'center', color: '#484f58' }}>No cases found</div>
  )

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ borderBottom: '1px solid #21262d' }}>
            {['Case ID', 'Status', 'VCF Eligibility', 'Source', 'Partner', 'Created'].map(h => (
              <th key={h} style={{
                padding: compact ? '10px 16px' : '12px 20px', textAlign: 'left',
                fontSize: 11, fontWeight: 600, color: '#8b949e',
                letterSpacing: '0.06em', textTransform: 'uppercase',
              }}>{h}</th>
            ))}
            <th style={{ padding: '12px 16px', width: 70 }} />
          </tr>
        </thead>
        <tbody>
          {cases.map((c, i) => (
            <tr key={c.id} style={{
              borderBottom: i < cases.length - 1 ? '1px solid #21262d' : 'none',
              transition: 'background 0.1s',
            }}
              onMouseEnter={e => e.currentTarget.style.background = '#1c2330'}
              onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
            >
              <td style={{ padding: compact ? '10px 16px' : '14px 20px' }}>
                <span style={{ fontFamily: "'IBM Plex Mono'", fontSize: 12, color: '#d4a853' }}>{c.caseId}</span>
              </td>
              <td style={{ padding: compact ? '10px 16px' : '14px 20px' }}>
                <Badge label={c.status} color={STATUS_COLORS[c.status] || '#8b949e'} />
              </td>
              <td style={{ padding: compact ? '10px 16px' : '14px 20px' }}>
                <Badge
                  label={c.vcfEligibility || 'pending'}
                  color={VCF_COLORS[c.vcfEligibility] || '#8b949e'}
                />
              </td>
              <td style={{ padding: compact ? '10px 16px' : '14px 20px', color: '#8b949e', fontSize: 12 }}>
                {c.marketingSource || '—'}
              </td>
              <td style={{ padding: compact ? '10px 16px' : '14px 20px', color: '#8b949e', fontSize: 12, fontFamily: "'IBM Plex Mono'" }}>
                {(c.partnerId || '').slice(0, 12)}…
              </td>
              <td style={{ padding: compact ? '10px 16px' : '14px 20px', color: '#484f58', fontSize: 11 }}>
                {c.createdAt ? new Date(c.createdAt).toLocaleDateString() : '—'}
              </td>
              <td style={{ padding: compact ? '10px 16px' : '14px 16px' }}>
                <button onClick={() => onView(c)} style={{
                  background: 'transparent', border: '1px solid #30363d',
                  color: '#8b949e', borderRadius: 5, padding: '4px 10px',
                  fontSize: 11, cursor: 'pointer', transition: 'all 0.15s',
                }}
                  onMouseEnter={e => { e.target.style.borderColor = '#d4a853'; e.target.style.color = '#d4a853' }}
                  onMouseLeave={e => { e.target.style.borderColor = '#30363d'; e.target.style.color = '#8b949e' }}
                >View</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function LeadsPage({ statusFilter, onViewCase }) {
  const [cases, setCases] = useState([])
  const [loading, setLoading] = useState(true)
  const [filters, setFilters] = useState({ status: statusFilter || '', vcfEligibility: '' })
  const [lastDoc, setLastDoc] = useState(null)
  const [hasMore, setHasMore] = useState(false)

  const load = useCallback(async (append = false) => {
    setLoading(true)
    try {
      const result = await fetchCases(filters, append ? lastDoc : null)
      setCases(prev => append ? [...prev, ...result.cases] : result.cases)
      setLastDoc(result.lastDoc)
      setHasMore(result.hasMore)
    } catch (e) { console.error(e) }
    finally { setLoading(false) }
  }, [filters, lastDoc])

  useEffect(() => { load(false) }, [filters])

  return (
    <div>
      <div style={{ marginBottom: 24, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <h1 style={{ fontFamily: "'DM Serif Display'", fontSize: 24, color: '#e6edf3', fontWeight: 400 }}>
          {statusFilter ? `${statusFilter} Cases` : 'All Leads'}
        </h1>
        <div style={{ display: 'flex', gap: 10 }}>
          <select
            value={filters.status}
            onChange={e => setFilters(f => ({ ...f, status: e.target.value }))}
            style={{
              background: '#161b22', border: '1px solid #30363d', color: '#e6edf3',
              borderRadius: 6, padding: '6px 12px', fontSize: 12, cursor: 'pointer',
            }}
          >
            <option value="">All Statuses</option>
            {['New Lead', 'Screened', 'Qualified', 'Disqualified', 'Active', 'Closed'].map(s => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          <select
            value={filters.vcfEligibility}
            onChange={e => setFilters(f => ({ ...f, vcfEligibility: e.target.value }))}
            style={{
              background: '#161b22', border: '1px solid #30363d', color: '#e6edf3',
              borderRadius: 6, padding: '6px 12px', fontSize: 12, cursor: 'pointer',
            }}
          >
            <option value="">All VCF Status</option>
            {['eligible', 'ineligible', 'needs_review', 'pending'].map(s => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>
      </div>

      <div style={{ background: '#161b22', border: '1px solid #21262d', borderRadius: 10, overflow: 'hidden' }}>
        {loading && !cases.length ? (
          <div style={{ padding: 48, textAlign: 'center', color: '#8b949e' }}>Loading…</div>
        ) : (
          <>
            <CasesTable cases={cases} onView={onViewCase} />
            {hasMore && (
              <div style={{ padding: '14px 20px', borderTop: '1px solid #21262d', textAlign: 'center' }}>
                <button onClick={() => load(true)} disabled={loading} style={{
                  background: 'transparent', border: '1px solid #30363d', color: '#8b949e',
                  borderRadius: 6, padding: '7px 20px', fontSize: 12, cursor: 'pointer',
                }}>
                  {loading ? 'Loading…' : 'Load more'}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function CaseDetail({ caseData, onBack }) {
  const [status, setStatus] = useState(caseData.status)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  const handleStatusChange = async (newStatus) => {
    setSaving(true)
    try {
      await updateCaseStatus(caseData.caseId, newStatus)
      setStatus(newStatus)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (e) { console.error(e) }
    finally { setSaving(false) }
  }

  const Field = ({ label, value, mono }) => (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 10, color: '#484f58', letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 3 }}>{label}</div>
      <div style={{ color: value ? '#e6edf3' : '#484f58', fontFamily: mono ? "'IBM Plex Mono'" : 'inherit', fontSize: mono ? 12 : 14 }}>
        {value || '—'}
      </div>
    </div>
  )

  const vcfDetails = caseData.vcfScreeningDetails
  const rules = vcfDetails?.ruleResults || []

  return (
    <div>
      <button onClick={onBack} style={{
        background: 'transparent', border: 'none', color: '#8b949e',
        cursor: 'pointer', fontSize: 13, marginBottom: 20, padding: 0,
        display: 'flex', alignItems: 'center', gap: 6,
      }}>
        ← Back to leads
      </button>

      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 24 }}>
        <div>
          <div style={{ fontFamily: "'IBM Plex Mono'", color: '#d4a853', fontSize: 20, fontWeight: 500, marginBottom: 4 }}>
            {caseData.caseId}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <Badge label={status} color={STATUS_COLORS[status] || '#8b949e'} />
            <Badge label={caseData.vcfEligibility || 'pending'} color={VCF_COLORS[caseData.vcfEligibility] || '#8b949e'} />
          </div>
        </div>

        {/* Status updater */}
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {saved && <span style={{ color: '#3fb950', fontSize: 12 }}>✓ Saved</span>}
          <select
            value={status}
            onChange={e => handleStatusChange(e.target.value)}
            disabled={saving}
            style={{
              background: '#161b22', border: '1px solid #30363d', color: '#e6edf3',
              borderRadius: 6, padding: '7px 12px', fontSize: 12, cursor: 'pointer',
            }}
          >
            {['New Lead', 'Screened', 'Qualified', 'Disqualified', 'Active', 'Closed'].map(s => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 16 }}>
        {/* Contact info */}
        <div style={{ background: '#161b22', border: '1px solid #21262d', borderRadius: 10, padding: '20px' }}>
          <div style={{ fontSize: 11, color: '#d4a853', fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 16 }}>Contact</div>
          <Field label="Name" value={`${caseData.firstName} ${caseData.lastName}`} />
          <Field label="Email" value={caseData.email} mono />
          <Field label="Phone" value={caseData.phone} mono />
          {caseData.address && (
            <Field label="Address" value={`${caseData.address.city}, ${caseData.address.state}`} />
          )}
        </div>

        {/* Exposure info */}
        <div style={{ background: '#161b22', border: '1px solid #21262d', borderRadius: 10, padding: '20px' }}>
          <div style={{ fontSize: 11, color: '#d4a853', fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 16 }}>Exposure</div>
          <Field label="Location" value={caseData.exposureLocation} />
          <Field label="Start Date" value={caseData.exposureDateStart} mono />
          <Field label="End Date" value={caseData.exposureDateEnd} mono />
          <Field label="WTC Program" value={caseData.wtcHealthProgramStatus} />
          <Field label="Prior Attorney" value={caseData.priorAttorney ? 'Yes' : 'No'} />
        </div>

        {/* Source info */}
        <div style={{ background: '#161b22', border: '1px solid #21262d', borderRadius: 10, padding: '20px' }}>
          <div style={{ fontSize: 11, color: '#d4a853', fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 16 }}>Source</div>
          <Field label="Marketing Source" value={caseData.marketingSource} />
          <Field label="Referral Code" value={caseData.referralCode} mono />
          <Field label="Partner ID" value={caseData.partnerId} mono />
          <Field label="Created" value={caseData.createdAt ? new Date(caseData.createdAt).toLocaleString() : '—'} />
          <Field label="Request ID" value={(caseData.requestId || '').slice(0, 12) + '…'} mono />
        </div>
      </div>

      {/* VCF Screening Results */}
      {vcfDetails && (
        <div style={{ marginTop: 16, background: '#161b22', border: '1px solid #21262d', borderRadius: 10, padding: '20px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
            <div style={{ fontSize: 11, color: '#d4a853', fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase' }}>VCF Screening Results</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span style={{ fontSize: 12, color: '#8b949e' }}>Score:</span>
              <span style={{ fontFamily: "'IBM Plex Mono'", fontSize: 18, fontWeight: 700, color: vcfDetails.score >= 90 ? '#3fb950' : vcfDetails.score >= 50 ? '#d29922' : '#f85149' }}>
                {vcfDetails.score}/100
              </span>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 10 }}>
            {rules.map(rule => (
              <div key={rule.ruleId} style={{
                background: '#0a0c0f', border: `1px solid ${rule.passed ? '#21262d' : '#f8514933'}`,
                borderRadius: 8, padding: '12px 14px',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  <span style={{ color: rule.passed ? '#3fb950' : '#f85149', fontSize: 14 }}>{rule.passed ? '✓' : '✗'}</span>
                  <span style={{ fontFamily: "'IBM Plex Mono'", fontSize: 10, color: '#8b949e' }}>{rule.ruleId}</span>
                </div>
                <div style={{ fontSize: 12, color: '#e6edf3' }}>{rule.code}</div>
                {rule.reason && <div style={{ fontSize: 11, color: '#8b949e', marginTop: 3 }}>{rule.reason}</div>}
              </div>
            ))}
          </div>

          {vcfDetails.flags?.length > 0 && (
            <div style={{ marginTop: 14, padding: '10px 14px', background: '#d2992222', border: '1px solid #d2992244', borderRadius: 7 }}>
              <div style={{ fontSize: 11, color: '#d29922', fontWeight: 600, marginBottom: 6 }}>Review Flags</div>
              {vcfDetails.flags.map((flag, i) => (
                <div key={i} style={{ fontSize: 12, color: '#e6edf3', marginBottom: 3 }}>• {flag}</div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Root App ──────────────────────────────────────────────────────────────────

export default function App() {
  const [active, setActive] = useState('dashboard')
  const [selectedCase, setSelectedCase] = useState(null)

  const handleViewCase = (caseData) => {
    setSelectedCase(caseData)
    setActive('case-detail')
  }

  const handleBack = () => {
    setSelectedCase(null)
    setActive('leads')
  }

  const renderContent = () => {
    if (selectedCase && active === 'case-detail') {
      return <CaseDetail caseData={selectedCase} onBack={handleBack} />
    }
    switch (active) {
      case 'dashboard': return <Dashboard onViewCase={handleViewCase} />
      case 'leads': return <LeadsPage onViewCase={handleViewCase} />
      case 'new': return <LeadsPage statusFilter="New Lead" onViewCase={handleViewCase} />
      case 'screened': return <LeadsPage statusFilter="Screened" onViewCase={handleViewCase} />
      case 'qualified': return <LeadsPage statusFilter="Qualified" onViewCase={handleViewCase} />
      case 'review': return <LeadsPage statusFilter="Needs Review" onViewCase={handleViewCase} />
      default: return <Dashboard onViewCase={handleViewCase} />
    }
  }

  return (
    <div style={S.layout}>
      <Sidebar active={active} setActive={v => { setSelectedCase(null); setActive(v) }} />
      <div style={S.main}>
        <header style={S.header}>
          <div style={{ fontSize: 13, color: '#8b949e' }}>
            {active === 'case-detail' && selectedCase
              ? <span><span style={{ color: '#484f58' }}>Leads / </span><span style={{ fontFamily: "'IBM Plex Mono'", color: '#d4a853' }}>{selectedCase.caseId}</span></span>
              : <span style={{ textTransform: 'capitalize', color: '#e6edf3' }}>{active}</span>
            }
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <div style={{ width: 7, height: 7, borderRadius: '50%', background: '#3fb950', boxShadow: '0 0 6px #3fb950' }} />
            <span style={{ fontSize: 11, color: '#8b949e' }}>Firestore Live</span>
            <div style={{
              width: 28, height: 28, borderRadius: '50%',
              background: 'linear-gradient(135deg, #d4a853, #9a7a3a)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 11, fontWeight: 700, color: '#0a0c0f',
            }}>A</div>
          </div>
        </header>
        <main style={S.content}>
          {renderContent()}
        </main>
      </div>
    </div>
  )
}
