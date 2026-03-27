/**
 * admin_ui/src/App.jsx
 * ZAD Legal — Lead Management Admin UI
 *
 * Features:
 *   - Paginated lead list (50/page) with real-time Firestore updates
 *   - Filters: status, VCF eligibility, date range, source, assigned to
 *   - Full-text search by email (prefix match)
 *   - Bulk actions: assign to paralegal, CSV export
 *   - Lead detail view: all data, VCF screening rules, status timeline
 *   - Status override with confirmation
 *   - Manual qualification override
 *   - Action buttons: Convert to Active, Mark Duplicate, Flag for Review
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import {
  fetchCases,
  fetchDashboardStats,
  updateCaseStatus,
  fetchCase,
  searchCases,
  subscribeToRecentCases,
  assignCase,
  exportToCsv,
} from './services/firebaseService'

// ── Design tokens ─────────────────────────────────────────────────────────────
const C = {
  bg: '#0a0c0f', surface: '#111418', card: '#161b22',
  border: '#21262d', borderHover: '#30363d',
  text: '#e6edf3', textMuted: '#8b949e', textFaint: '#484f58',
  gold: '#d4a853', goldMuted: '#9a7a3a',
  blue: '#388bfd', purple: '#a371f7', green: '#3fb950',
  red: '#f85149', yellow: '#d29922', teal: '#58a6ff',
}

const STATUS_COLORS = {
  'New Lead': C.blue, 'Screened': C.purple, 'Qualified': C.green,
  'Disqualified': C.red, 'Needs Review': C.yellow, 'Active': C.teal, 'Closed': C.textFaint,
}
const VCF_COLORS = {
  eligible: C.green, ineligible: C.red, needs_review: C.yellow, pending: C.textMuted,
}
const ALL_STATUSES = ['New Lead', 'Screened', 'Qualified', 'Disqualified', 'Needs Review', 'Active', 'Closed']
const ALL_VCF = ['eligible', 'ineligible', 'needs_review', 'pending']

// ── Primitive components ──────────────────────────────────────────────────────

function Badge({ label, color }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      padding: '2px 8px', borderRadius: 12, fontSize: 11, fontWeight: 600,
      background: color + '22', color, border: `1px solid ${color}44`,
      letterSpacing: '0.03em', textTransform: 'uppercase', whiteSpace: 'nowrap',
    }}>
      <span style={{ width: 5, height: 5, borderRadius: '50%', background: color, flexShrink: 0 }} />
      {label}
    </span>
  )
}

function Btn({ children, onClick, variant = 'ghost', disabled, style: extraStyle }) {
  const base = {
    border: '1px solid ' + C.borderHover, borderRadius: 6,
    padding: '6px 14px', fontSize: 12, cursor: disabled ? 'not-allowed' : 'pointer',
    fontFamily: 'inherit', transition: 'all 0.15s', opacity: disabled ? 0.5 : 1,
    display: 'inline-flex', alignItems: 'center', gap: 6, ...extraStyle,
  }
  const variants = {
    ghost: { background: 'transparent', color: C.textMuted },
    primary: { background: C.gold + '22', color: C.gold, borderColor: C.gold + '44' },
    danger: { background: C.red + '22', color: C.red, borderColor: C.red + '44' },
    success: { background: C.green + '22', color: C.green, borderColor: C.green + '44' },
  }
  return (
    <button
      onClick={disabled ? undefined : onClick}
      style={{ ...base, ...variants[variant] }}
      onMouseEnter={e => { if (!disabled) Object.assign(e.currentTarget.style, { borderColor: C.gold, color: C.gold }) }}
      onMouseLeave={e => { if (!disabled) Object.assign(e.currentTarget.style, { ...base, ...variants[variant] }) }}
    >
      {children}
    </button>
  )
}

function Input({ value, onChange, placeholder, style: extra }) {
  return (
    <input
      value={value}
      onChange={e => onChange(e.target.value)}
      placeholder={placeholder}
      style={{
        background: C.card, border: `1px solid ${C.borderHover}`, color: C.text,
        borderRadius: 6, padding: '7px 12px', fontSize: 12, fontFamily: 'inherit',
        outline: 'none', width: '100%', ...extra,
      }}
    />
  )
}

function Select({ value, onChange, children, style: extra }) {
  return (
    <select
      value={value}
      onChange={e => onChange(e.target.value)}
      style={{
        background: C.card, border: `1px solid ${C.borderHover}`, color: C.text,
        borderRadius: 6, padding: '7px 12px', fontSize: 12, cursor: 'pointer',
        fontFamily: 'inherit', ...extra,
      }}
    >
      {children}
    </select>
  )
}

function StatCard({ label, value, color, sub }) {
  return (
    <div style={{
      background: C.card, border: `1px solid ${C.border}`, borderRadius: 10,
      padding: '18px 22px', position: 'relative', overflow: 'hidden',
    }}>
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 2, background: color, opacity: 0.7 }} />
      <div style={{ color: C.textMuted, fontSize: 10, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>{label}</div>
      <div style={{ fontSize: 30, fontWeight: 700, color: C.text, fontFamily: "'IBM Plex Mono', monospace", lineHeight: 1 }}>{value ?? '—'}</div>
      {sub && <div style={{ color: C.textMuted, fontSize: 11, marginTop: 5 }}>{sub}</div>}
    </div>
  )
}

// ── Sidebar ───────────────────────────────────────────────────────────────────

function Sidebar({ active, setActive, counts }) {
  const items = [
    { id: 'dashboard', icon: '◈', label: 'Dashboard' },
    { id: 'leads', icon: '◎', label: 'All Leads', count: null },
    { id: 'new', icon: '●', label: 'New Leads', count: counts?.['New Lead'] },
    { id: 'screened', icon: '◇', label: 'Screened', count: counts?.['Screened'] },
    { id: 'qualified', icon: '◆', label: 'Qualified', count: counts?.['Qualified'] },
    { id: 'review', icon: '◈', label: 'Needs Review', count: counts?.['Needs Review'] },
    { id: 'partners', icon: '⬡', label: 'Partners' },
  ]

  return (
    <div style={{
      width: 240, background: C.surface, borderRight: `1px solid ${C.border}`,
      display: 'flex', flexDirection: 'column', position: 'fixed',
      top: 0, left: 0, height: '100vh', zIndex: 100,
    }}>
      <div style={{ padding: '22px 18px 18px', borderBottom: `1px solid ${C.border}` }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{
            width: 32, height: 32,
            background: 'linear-gradient(135deg, #d4a853, #9a7a3a)',
            borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 14, fontWeight: 700, color: C.bg, flexShrink: 0,
          }}>Z</div>
          <div>
            <div style={{ fontFamily: "'DM Serif Display'", fontSize: 14, color: C.text }}>ZAD Legal</div>
            <div style={{ fontSize: 9, color: C.textMuted, letterSpacing: '0.05em' }}>LEAD MANAGEMENT</div>
          </div>
        </div>
      </div>
      <nav style={{ flex: 1, padding: '10px 8px', overflowY: 'auto' }}>
        {items.map(item => (
          <button key={item.id} onClick={() => setActive(item.id)} style={{
            width: '100%', display: 'flex', alignItems: 'center', gap: 10,
            padding: '8px 12px', borderRadius: 6, border: 'none', cursor: 'pointer',
            background: active === item.id ? '#1c2330' : 'transparent',
            color: active === item.id ? C.text : C.textMuted,
            fontSize: 13, fontWeight: active === item.id ? 500 : 400,
            transition: 'all 0.15s', textAlign: 'left', justifyContent: 'space-between',
            borderLeft: active === item.id ? `2px solid ${C.gold}` : '2px solid transparent',
          }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ fontSize: 11, color: active === item.id ? C.gold : C.textFaint }}>{item.icon}</span>
              {item.label}
            </span>
            {item.count != null && (
              <span style={{
                background: C.gold + '33', color: C.gold, fontSize: 10, fontWeight: 700,
                padding: '1px 6px', borderRadius: 10, fontFamily: "'IBM Plex Mono'",
              }}>{item.count}</span>
            )}
          </button>
        ))}
      </nav>
      <div style={{ padding: '12px 18px', borderTop: `1px solid ${C.border}` }}>
        <div style={{ fontSize: 10, color: C.textFaint }}>API v2.0.0 · Module 1</div>
      </div>
    </div>
  )
}

// ── Cases table ───────────────────────────────────────────────────────────────

function CasesTable({ cases, onView, selectedIds, onSelectId, onSelectAll, compact }) {
  const allSelected = cases.length > 0 && cases.every(c => selectedIds.has(c.caseId))

  if (!cases.length) return (
    <div style={{ padding: 48, textAlign: 'center', color: C.textFaint, fontSize: 13 }}>
      No cases found
    </div>
  )

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ borderBottom: `1px solid ${C.border}` }}>
            <th style={{ padding: '10px 16px', width: 40 }}>
              <input type="checkbox" checked={allSelected} onChange={e => onSelectAll(e.target.checked)}
                style={{ cursor: 'pointer', accentColor: C.gold }} />
            </th>
            {['Case ID', 'Name', 'Status', 'VCF', 'Source', 'Assigned', 'Created'].map(h => (
              <th key={h} style={{
                padding: compact ? '9px 14px' : '11px 18px', textAlign: 'left',
                fontSize: 10, fontWeight: 600, color: C.textMuted,
                letterSpacing: '0.07em', textTransform: 'uppercase',
              }}>{h}</th>
            ))}
            <th style={{ width: 60 }} />
          </tr>
        </thead>
        <tbody>
          {cases.map((c, i) => (
            <tr
              key={c.caseId || i}
              style={{
                borderBottom: i < cases.length - 1 ? `1px solid ${C.border}` : 'none',
                background: selectedIds.has(c.caseId) ? C.gold + '0a' : 'transparent',
                transition: 'background 0.1s',
              }}
              onMouseEnter={e => { if (!selectedIds.has(c.caseId)) e.currentTarget.style.background = '#1c2330' }}
              onMouseLeave={e => { if (!selectedIds.has(c.caseId)) e.currentTarget.style.background = 'transparent' }}
            >
              <td style={{ padding: '10px 16px' }}>
                <input type="checkbox" checked={selectedIds.has(c.caseId)} onChange={e => onSelectId(c.caseId, e.target.checked)}
                  style={{ cursor: 'pointer', accentColor: C.gold }} />
              </td>
              <td style={{ padding: compact ? '9px 14px' : '12px 18px' }}>
                <span style={{ fontFamily: "'IBM Plex Mono'", fontSize: 11, color: C.gold }}>{c.caseId}</span>
              </td>
              <td style={{ padding: compact ? '9px 14px' : '12px 18px', color: C.text, fontSize: 12 }}>
                {c.firstName} {c.lastName}
              </td>
              <td style={{ padding: compact ? '9px 14px' : '12px 18px' }}>
                <Badge label={c.status} color={STATUS_COLORS[c.status] || C.textMuted} />
              </td>
              <td style={{ padding: compact ? '9px 14px' : '12px 18px' }}>
                <Badge label={c.vcfEligibility || 'pending'} color={VCF_COLORS[c.vcfEligibility] || C.textMuted} />
              </td>
              <td style={{ padding: compact ? '9px 14px' : '12px 18px', color: C.textMuted, fontSize: 11 }}>
                {c.marketingSource || '—'}
              </td>
              <td style={{ padding: compact ? '9px 14px' : '12px 18px', color: C.textMuted, fontSize: 11 }}>
                {c.assignedTo ? <span style={{ color: C.teal }}>{c.assignedTo.split('@')[0]}</span> : <span style={{ color: C.textFaint }}>—</span>}
              </td>
              <td style={{ padding: compact ? '9px 14px' : '12px 18px', color: C.textFaint, fontSize: 10 }}>
                {c.createdAt
                  ? new Date(c.createdAt?.seconds ? c.createdAt.seconds * 1000 : c.createdAt).toLocaleDateString()
                  : '—'}
              </td>
              <td style={{ padding: '8px 12px', textAlign: 'right' }}>
                <Btn onClick={() => onView(c)}>View</Btn>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Filter panel ──────────────────────────────────────────────────────────────

function FilterPanel({ filters, setFilters, onSearch }) {
  const [searchVal, setSearchVal] = useState('')
  const debounceRef = useRef(null)

  const handleSearch = v => {
    setSearchVal(v)
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => onSearch(v), 400)
  }

  const labelStyle = { fontSize: 10, color: C.textMuted, letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 5 }

  return (
    <div style={{
      background: C.card, border: `1px solid ${C.border}`, borderRadius: 10,
      padding: '16px 20px', marginBottom: 16,
      display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 14, alignItems: 'end',
    }}>
      <div>
        <div style={labelStyle}>Search Email</div>
        <Input value={searchVal} onChange={handleSearch} placeholder="user@example.com" />
      </div>
      <div>
        <div style={labelStyle}>Status</div>
        <Select value={filters.status || ''} onChange={v => setFilters(f => ({ ...f, status: v }))}>
          <option value="">All Statuses</option>
          {ALL_STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
        </Select>
      </div>
      <div>
        <div style={labelStyle}>VCF Result</div>
        <Select value={filters.vcfEligibility || ''} onChange={v => setFilters(f => ({ ...f, vcfEligibility: v }))}>
          <option value="">All VCF</option>
          {ALL_VCF.map(s => <option key={s} value={s}>{s}</option>)}
        </Select>
      </div>
      <div>
        <div style={labelStyle}>From Date</div>
        <input type="date" value={filters.dateFrom || ''} onChange={e => setFilters(f => ({ ...f, dateFrom: e.target.value }))}
          style={{ background: C.card, border: `1px solid ${C.borderHover}`, color: C.text, borderRadius: 6, padding: '7px 10px', fontSize: 12, fontFamily: 'inherit', width: '100%' }} />
      </div>
      <div>
        <div style={labelStyle}>To Date</div>
        <input type="date" value={filters.dateTo || ''} onChange={e => setFilters(f => ({ ...f, dateTo: e.target.value }))}
          style={{ background: C.card, border: `1px solid ${C.borderHover}`, color: C.text, borderRadius: 6, padding: '7px 10px', fontSize: 12, fontFamily: 'inherit', width: '100%' }} />
      </div>
      <div style={{ display: 'flex', alignItems: 'flex-end' }}>
        <Btn onClick={() => { setFilters({}); handleSearch('') }} style={{ width: '100%', justifyContent: 'center' }}>
          Clear Filters
        </Btn>
      </div>
    </div>
  )
}

// ── Bulk actions bar ──────────────────────────────────────────────────────────

function BulkActionsBar({ selectedIds, onAssign, onExport, onClear, cases }) {
  const [assignEmail, setAssignEmail] = useState('')
  const [showAssignInput, setShowAssignInput] = useState(false)
  const count = selectedIds.size

  if (!count) return null

  const handleAssign = () => {
    if (!assignEmail.trim()) return
    onAssign(assignEmail.trim())
    setAssignEmail('')
    setShowAssignInput(false)
  }

  return (
    <div style={{
      background: C.gold + '11', border: `1px solid ${C.gold}33`,
      borderRadius: 8, padding: '12px 18px', marginBottom: 14,
      display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap',
    }}>
      <span style={{ color: C.gold, fontWeight: 600, fontSize: 13 }}>
        {count} case{count !== 1 ? 's' : ''} selected
      </span>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        {showAssignInput ? (
          <>
            <Input
              value={assignEmail}
              onChange={setAssignEmail}
              placeholder="paralegal@zadlegal.com"
              style={{ width: 220 }}
            />
            <Btn variant="primary" onClick={handleAssign}>Assign</Btn>
            <Btn onClick={() => setShowAssignInput(false)}>Cancel</Btn>
          </>
        ) : (
          <Btn variant="primary" onClick={() => setShowAssignInput(true)}>
            ↗ Assign to Staff
          </Btn>
        )}
        <Btn onClick={onExport} variant="success">
          ↓ Export CSV ({count})
        </Btn>
        <Btn onClick={onClear}>Deselect All</Btn>
      </div>
    </div>
  )
}

// ── Leads page ────────────────────────────────────────────────────────────────

function LeadsPage({ statusFilter, onViewCase }) {
  const [cases, setCases] = useState([])
  const [loading, setLoading] = useState(true)
  const [filters, setFilters] = useState({ status: statusFilter || '' })
  const [lastDoc, setLastDoc] = useState(null)
  const [hasMore, setHasMore] = useState(false)
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [searchResults, setSearchResults] = useState(null) // null = not searching
  const [realtime, setRealtime] = useState(true)
  const unsubRef = useRef(null)
  const pageRef = useRef(1)

  // Real-time subscription for first page with no filters
  useEffect(() => {
    const hasFilters = Object.values(filters).some(v => v)
    if (!hasFilters && realtime) {
      if (unsubRef.current) unsubRef.current()
      unsubRef.current = subscribeToRecentCases(updatedCases => {
        setCases(updatedCases)
        setLoading(false)
      }, statusFilter || null)
      return () => { if (unsubRef.current) unsubRef.current() }
    }
  }, [statusFilter, realtime])

  const loadFiltered = useCallback(async (append = false) => {
    if (unsubRef.current) { unsubRef.current(); unsubRef.current = null }
    setLoading(true)
    try {
      const result = await fetchCases(filters, append ? lastDoc : null)
      setCases(prev => append ? [...prev, ...result.cases] : result.cases)
      setLastDoc(result.lastDoc)
      setHasMore(result.hasMore)
    } catch (e) { console.error(e) }
    finally { setLoading(false) }
  }, [filters, lastDoc])

  useEffect(() => {
    const hasFilters = Object.values(filters).some(v => v)
    if (hasFilters || !realtime) loadFiltered(false)
  }, [filters])

  const handleSearch = async (term) => {
    if (!term.trim()) { setSearchResults(null); return }
    setLoading(true)
    try {
      const results = await searchCases(term)
      setSearchResults(results)
    } catch (e) { console.error(e) }
    finally { setLoading(false) }
  }

  const handleSelectId = (caseId, checked) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      checked ? next.add(caseId) : next.delete(caseId)
      return next
    })
  }

  const handleSelectAll = (checked) => {
    const displayed = searchResults ?? cases
    setSelectedIds(checked ? new Set(displayed.map(c => c.caseId)) : new Set())
  }

  const handleBulkAssign = async (email) => {
    for (const caseId of selectedIds) {
      try { await assignCase(caseId, email) } catch (e) { console.error(e) }
    }
    setSelectedIds(new Set())
    loadFiltered(false)
  }

  const handleExport = () => {
    const displayed = searchResults ?? cases
    const toExport = selectedIds.size > 0
      ? displayed.filter(c => selectedIds.has(c.caseId))
      : displayed
    exportToCsv(toExport)
  }

  const displayed = searchResults ?? cases
  const pageTitle = statusFilter ? `${statusFilter} Cases` : 'All Leads'

  return (
    <div>
      <div style={{ marginBottom: 20, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <h1 style={{ fontFamily: "'DM Serif Display'", fontSize: 24, color: C.text, fontWeight: 400 }}>{pageTitle}</h1>
          <p style={{ color: C.textMuted, fontSize: 12, marginTop: 2 }}>
            {displayed.length} case{displayed.length !== 1 ? 's' : ''} shown
            {realtime && !Object.values(filters).some(v => v) && ' · live'}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <Btn onClick={handleExport} variant="ghost">↓ Export All CSV</Btn>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: C.textMuted }}>
            <span style={{
              width: 7, height: 7, borderRadius: '50%',
              background: realtime ? C.green : C.textFaint,
              boxShadow: realtime ? `0 0 6px ${C.green}` : 'none',
            }} />
            {realtime ? 'Live' : 'Static'}
          </div>
        </div>
      </div>

      <FilterPanel filters={filters} setFilters={setFilters} onSearch={handleSearch} />
      <BulkActionsBar
        selectedIds={selectedIds}
        onAssign={handleBulkAssign}
        onExport={handleExport}
        onClear={() => setSelectedIds(new Set())}
        cases={displayed}
      />

      <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 10, overflow: 'hidden' }}>
        {loading && !displayed.length ? (
          <div style={{ padding: 48, textAlign: 'center', color: C.textMuted }}>Loading…</div>
        ) : (
          <>
            <CasesTable
              cases={displayed}
              onView={onViewCase}
              selectedIds={selectedIds}
              onSelectId={handleSelectId}
              onSelectAll={handleSelectAll}
            />
            {hasMore && !searchResults && (
              <div style={{ padding: '14px 20px', borderTop: `1px solid ${C.border}`, textAlign: 'center' }}>
                <Btn onClick={() => loadFiltered(true)} disabled={loading}>
                  {loading ? 'Loading…' : `Load more (page ${++pageRef.current})`}
                </Btn>
              </div>
            )}
            <div style={{ padding: '10px 20px', borderTop: `1px solid ${C.border}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 11, color: C.textFaint }}>{displayed.length} of many · 50 per page</span>
              {searchResults && (
                <Btn onClick={() => setSearchResults(null)}>Clear search results</Btn>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// ── Status timeline ───────────────────────────────────────────────────────────

function StatusTimeline({ history }) {
  if (!history?.length) return (
    <div style={{ color: C.textFaint, fontSize: 12, padding: '8px 0' }}>No history recorded</div>
  )

  return (
    <div style={{ position: 'relative', paddingLeft: 24 }}>
      <div style={{ position: 'absolute', left: 7, top: 8, bottom: 8, width: 1, background: C.border }} />
      {[...history].reverse().map((entry, i) => (
        <div key={i} style={{ marginBottom: 16, position: 'relative' }}>
          <div style={{
            position: 'absolute', left: -20, top: 3, width: 8, height: 8,
            borderRadius: '50%', background: STATUS_COLORS[entry.status] || C.textMuted,
            border: `2px solid ${C.card}`,
            boxShadow: `0 0 0 1px ${STATUS_COLORS[entry.status] || C.textMuted}`,
          }} />
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
            <Badge label={entry.status} color={STATUS_COLORS[entry.status] || C.textMuted} />
            <span style={{ fontSize: 10, color: C.textFaint }}>
              {entry.timestamp
                ? new Date(entry.timestamp).toLocaleString()
                : '—'}
            </span>
            <span style={{ fontSize: 10, color: C.textMuted }}>by {entry.updatedBy || 'system'}</span>
          </div>
          {entry.note && (
            <div style={{ fontSize: 11, color: C.textMuted, marginTop: 4, marginLeft: 2 }}>{entry.note}</div>
          )}
        </div>
      ))}
    </div>
  )
}

// ── VCF rule card ─────────────────────────────────────────────────────────────

function RuleCard({ rule }) {
  const severityColor = rule.severity === 'hard_fail' ? C.red : rule.severity === 'soft_flag' ? C.yellow : C.green
  return (
    <div style={{
      background: C.bg, border: `1px solid ${rule.passed ? C.border : C.red + '33'}`,
      borderRadius: 8, padding: '12px 14px',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5 }}>
        <span style={{ color: rule.passed ? C.green : C.red, fontSize: 13 }}>{rule.passed ? '✓' : '✗'}</span>
        <span style={{ fontFamily: "'IBM Plex Mono'", fontSize: 9, color: C.textMuted }}>{rule.ruleId}</span>
        <span style={{ marginLeft: 'auto', fontSize: 9, color: severityColor, textTransform: 'uppercase', letterSpacing: '0.06em' }}>{rule.severity}</span>
      </div>
      <div style={{ fontSize: 12, color: C.text, fontWeight: 500 }}>{rule.code}</div>
      {rule.reason && <div style={{ fontSize: 11, color: C.textMuted, marginTop: 3, lineHeight: 1.5 }}>{rule.reason}</div>}
    </div>
  )
}

// ── Action confirmation dialog ────────────────────────────────────────────────

function ConfirmDialog({ title, message, onConfirm, onCancel }) {
  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
    }}>
      <div style={{
        background: C.card, border: `1px solid ${C.borderHover}`,
        borderRadius: 12, padding: 28, maxWidth: 400, width: '90%',
      }}>
        <h3 style={{ color: C.text, marginBottom: 10, fontWeight: 600 }}>{title}</h3>
        <p style={{ color: C.textMuted, fontSize: 13, lineHeight: 1.6, marginBottom: 22 }}>{message}</p>
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <Btn onClick={onCancel}>Cancel</Btn>
          <Btn variant="danger" onClick={onConfirm}>Confirm</Btn>
        </div>
      </div>
    </div>
  )
}

// ── Case detail view ──────────────────────────────────────────────────────────

function CaseDetail({ caseData: initialData, onBack }) {
  const [caseData, setCaseData] = useState(initialData)
  const [status, setStatus] = useState(initialData.status)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [confirm, setConfirm] = useState(null) // { action, title, message, onConfirm }
  const [assignInput, setAssignInput] = useState(caseData.assignedTo || '')
  const [assignSaving, setAssignSaving] = useState(false)

  // Refresh latest case data
  useEffect(() => {
    fetchCase(caseData.caseId).then(fresh => { if (fresh) setCaseData(fresh) })
  }, [caseData.caseId])

  const handleStatusChange = async (newStatus) => {
    setSaving(true)
    try {
      await updateCaseStatus(caseData.caseId, newStatus, 'admin')
      setStatus(newStatus)
      const fresh = await fetchCase(caseData.caseId)
      if (fresh) setCaseData(fresh)
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    } catch (e) { console.error(e) }
    finally { setSaving(false) }
  }

  const handleAssign = async () => {
    if (!assignInput.trim()) return
    setAssignSaving(true)
    try {
      await assignCase(caseData.caseId, assignInput.trim())
      const fresh = await fetchCase(caseData.caseId)
      if (fresh) setCaseData(fresh)
    } catch (e) { console.error(e) }
    finally { setAssignSaving(false) }
  }

  const confirmAction = (action, title, message, fn) => {
    setConfirm({ action, title, message, onConfirm: async () => { setConfirm(null); await fn() } })
  }

  const Field = ({ label, value, mono, wide }) => (
    <div style={{ marginBottom: 14, gridColumn: wide ? 'span 2' : undefined }}>
      <div style={{ fontSize: 9, color: C.textFaint, letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 3 }}>{label}</div>
      <div style={{ color: value ? C.text : C.textFaint, fontFamily: mono ? "'IBM Plex Mono'" : 'inherit', fontSize: mono ? 11 : 13, wordBreak: 'break-all' }}>
        {value || '—'}
      </div>
    </div>
  )

  const vcfDetails = caseData.vcfScreeningDetails
  const rules = vcfDetails?.ruleResults || []
  const scoreColor = vcfDetails?.score >= 90 ? C.green : vcfDetails?.score >= 50 ? C.yellow : C.red

  return (
    <div style={{ maxWidth: 1100 }}>
      {confirm && (
        <ConfirmDialog
          title={confirm.title}
          message={confirm.message}
          onConfirm={confirm.onConfirm}
          onCancel={() => setConfirm(null)}
        />
      )}

      <button onClick={onBack} style={{
        background: 'transparent', border: 'none', color: C.textMuted,
        cursor: 'pointer', fontSize: 13, marginBottom: 20, padding: 0,
        display: 'flex', alignItems: 'center', gap: 6,
      }}>
        ← Back to leads
      </button>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 22, flexWrap: 'wrap', gap: 16 }}>
        <div>
          <div style={{ fontFamily: "'IBM Plex Mono'", color: C.gold, fontSize: 22, fontWeight: 500, marginBottom: 6 }}>
            {caseData.caseId}
          </div>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <Badge label={status} color={STATUS_COLORS[status] || C.textMuted} />
            <Badge label={caseData.vcfEligibility || 'pending'} color={VCF_COLORS[caseData.vcfEligibility] || C.textMuted} />
            {caseData.assignedTo && (
              <span style={{ fontSize: 11, color: C.teal, border: `1px solid ${C.teal}44`, borderRadius: 10, padding: '2px 8px' }}>
                → {caseData.assignedTo.split('@')[0]}
              </span>
            )}
          </div>
        </div>

        {/* Status control */}
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          {saved && <span style={{ color: C.green, fontSize: 12 }}>✓ Saved</span>}
          <Select value={status} onChange={newStatus => {
            if (newStatus === 'Disqualified' || newStatus === 'Closed') {
              confirmAction('status', `Set to ${newStatus}?`, `This will mark the case as ${newStatus}. Continue?`, () => handleStatusChange(newStatus))
            } else {
              handleStatusChange(newStatus)
            }
          }} style={{ opacity: saving ? 0.6 : 1 }}>
            {ALL_STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
          </Select>
        </div>
      </div>

      {/* Action buttons */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 22, flexWrap: 'wrap' }}>
        <Btn variant="primary" onClick={() => confirmAction('convert', 'Convert to Active Case?', 'This will convert the lead to an active case and assign it to a paralegal.', () => handleStatusChange('Active'))}>
          ⚡ Convert to Active
        </Btn>
        <Btn variant="ghost" onClick={() => confirmAction('duplicate', 'Mark as Duplicate?', 'This will flag the case as a duplicate and close it.', () => handleStatusChange('Closed'))}>
          ⊘ Mark Duplicate
        </Btn>
        <Btn variant="ghost" onClick={() => handleStatusChange('Needs Review')}>
          ◈ Flag for Review
        </Btn>
      </div>

      {/* 3-column data grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 14, marginBottom: 14 }}>
        {/* Contact */}
        <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 10, padding: 20 }}>
          <div style={{ fontSize: 10, color: C.gold, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 16 }}>Contact</div>
          <Field label="Full Name" value={`${caseData.firstName} ${caseData.lastName}`} />
          <Field label="Email" value={caseData.email} mono />
          <Field label="Phone" value={caseData.phone} mono />
          {caseData.address && <Field label="City/State" value={`${caseData.address.city || ''}, ${caseData.address.state || ''}`} />}
        </div>

        {/* Exposure */}
        <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 10, padding: 20 }}>
          <div style={{ fontSize: 10, color: C.gold, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 16 }}>Exposure</div>
          <Field label="Location" value={caseData.exposureLocation} />
          <Field label="Start Date" value={caseData.exposureDateStart} mono />
          <Field label="End Date" value={caseData.exposureDateEnd} mono />
          <Field label="WTC Program" value={caseData.wtcHealthProgramStatus} />
          <Field label="Prior Attorney" value={caseData.priorAttorney ? 'Yes' : 'No'} />
          {caseData.conditions?.length > 0 && (
            <div style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 9, color: C.textFaint, letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 5 }}>Conditions</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                {caseData.conditions.map((c, i) => (
                  <span key={i} style={{ background: C.purple + '22', color: C.purple, border: `1px solid ${C.purple}44`, borderRadius: 8, padding: '2px 7px', fontSize: 10 }}>{c}</span>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Source / Assignment */}
        <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 10, padding: 20 }}>
          <div style={{ fontSize: 10, color: C.gold, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 16 }}>Source & Assignment</div>
          <Field label="Marketing Source" value={caseData.marketingSource} />
          <Field label="Referral Code" value={caseData.referralCode} mono />
          <Field label="Partner ID" value={caseData.partnerId} mono />
          <Field label="Created" value={caseData.createdAt ? new Date(caseData.createdAt?.seconds ? caseData.createdAt.seconds * 1000 : caseData.createdAt).toLocaleString() : '—'} />
          <div style={{ marginTop: 4 }}>
            <div style={{ fontSize: 9, color: C.textFaint, letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 5 }}>Assign To</div>
            <div style={{ display: 'flex', gap: 6 }}>
              <Input value={assignInput} onChange={setAssignInput} placeholder="paralegal@zadlegal.com" style={{ flex: 1 }} />
              <Btn variant="primary" onClick={handleAssign} disabled={assignSaving}>
                {assignSaving ? '…' : '✓'}
              </Btn>
            </div>
          </div>
        </div>
      </div>

      {/* VCF Screening Results */}
      {vcfDetails && (
        <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 10, padding: 22, marginBottom: 14 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 18 }}>
            <div style={{ fontSize: 10, color: C.gold, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase' }}>VCF Screening Results</div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span style={{ fontSize: 11, color: C.textMuted }}>Confidence Score</span>
              <span style={{ fontFamily: "'IBM Plex Mono'", fontSize: 22, fontWeight: 700, color: scoreColor }}>
                {vcfDetails.score}/100
              </span>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 10, marginBottom: vcfDetails.flags?.length ? 14 : 0 }}>
            {rules.map(rule => <RuleCard key={rule.ruleId} rule={rule} />)}
          </div>

          {vcfDetails.flags?.length > 0 && (
            <div style={{ padding: '12px 16px', background: C.yellow + '15', border: `1px solid ${C.yellow}44`, borderRadius: 8 }}>
              <div style={{ fontSize: 10, color: C.yellow, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 8 }}>Review Flags</div>
              {vcfDetails.flags.map((flag, i) => (
                <div key={i} style={{ fontSize: 12, color: C.text, marginBottom: 5, display: 'flex', gap: 6 }}>
                  <span style={{ color: C.yellow, flexShrink: 0 }}>◆</span>{flag}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Status timeline */}
      <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 10, padding: 22 }}>
        <div style={{ fontSize: 10, color: C.gold, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 18 }}>Status Timeline</div>
        <StatusTimeline history={caseData.statusHistory} />
      </div>
    </div>
  )
}

// ── Dashboard ─────────────────────────────────────────────────────────────────

function Dashboard({ onViewCase }) {
  const [stats, setStats] = useState(null)
  const [recentCases, setRecentCases] = useState([])
  const [loading, setLoading] = useState(true)
  const [selectedIds, setSelectedIds] = useState(new Set())
  const unsubRef = useRef(null)

  useEffect(() => {
    fetchDashboardStats().then(setStats).catch(console.error)

    unsubRef.current = subscribeToRecentCases(cases => {
      setRecentCases(cases.slice(0, 8))
      setLoading(false)
    })
    return () => { if (unsubRef.current) unsubRef.current() }
  }, [])

  const total = stats ? Object.values(stats).filter((_, i) => i < 7).reduce((a, b) => a + b, 0) : 0

  return (
    <div>
      <div style={{ marginBottom: 26 }}>
        <h1 style={{ fontFamily: "'DM Serif Display'", fontSize: 26, color: C.text, fontWeight: 400, marginBottom: 4 }}>Lead Dashboard</h1>
        <p style={{ color: C.textMuted, fontSize: 13 }}>Real-time overview · 9/11 VCF leads</p>
      </div>

      {loading ? (
        <div style={{ color: C.textMuted, padding: 48, textAlign: 'center' }}>Loading…</div>
      ) : (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(170px, 1fr))', gap: 12, marginBottom: 28 }}>
            <StatCard label="Total Cases" value={total} color={C.gold} sub="All time" />
            <StatCard label="New Leads" value={stats?.['New Lead']} color={C.blue} />
            <StatCard label="Screened" value={stats?.['Screened']} color={C.purple} />
            <StatCard label="Qualified" value={stats?.['Qualified']} color={C.green} />
            <StatCard label="Needs Review" value={stats?.['Needs Review']} color={C.yellow} />
            <StatCard label="Disqualified" value={stats?.['Disqualified']} color={C.red} />
            <StatCard label="VCF Eligible" value={stats?.eligible} color={C.green} sub="Passed screening" />
          </div>

          <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 10, overflow: 'hidden' }}>
            <div style={{ padding: '14px 20px', borderBottom: `1px solid ${C.border}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ fontWeight: 600, color: C.text, fontSize: 13 }}>Recent Leads</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div style={{ width: 7, height: 7, borderRadius: '50%', background: C.green, boxShadow: `0 0 6px ${C.green}` }} />
                <span style={{ fontSize: 11, color: C.textMuted }}>Live</span>
              </div>
            </div>
            <CasesTable
              cases={recentCases}
              onView={onViewCase}
              selectedIds={selectedIds}
              onSelectId={(id, checked) => setSelectedIds(p => { const n = new Set(p); checked ? n.add(id) : n.delete(id); return n })}
              onSelectAll={checked => setSelectedIds(checked ? new Set(recentCases.map(c => c.caseId)) : new Set())}
              compact
            />
          </div>
        </>
      )}
    </div>
  )
}

// ── Partners stub page ────────────────────────────────────────────────────────

function PartnersPage() {
  return (
    <div>
      <h1 style={{ fontFamily: "'DM Serif Display'", fontSize: 24, color: C.text, fontWeight: 400, marginBottom: 8 }}>Partner Management</h1>
      <p style={{ color: C.textMuted, fontSize: 13, marginBottom: 24 }}>Manage API keys and marketing partner access.</p>
      <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 10, padding: 32, textAlign: 'center' }}>
        <div style={{ color: C.gold, fontSize: 28, marginBottom: 12 }}>⬡</div>
        <div style={{ color: C.text, fontSize: 14, marginBottom: 6 }}>Partner management available via API</div>
        <div style={{ color: C.textMuted, fontSize: 12 }}>
          Use <code style={{ fontFamily: "'IBM Plex Mono'", color: C.gold, fontSize: 11 }}>POST /api/v1/admin/partners</code> to create partners
          and <code style={{ fontFamily: "'IBM Plex Mono'", color: C.gold, fontSize: 11 }}>POST /api/v1/admin/partners/&#123;id&#125;/keys</code> to generate API keys.
        </div>
      </div>
    </div>
  )
}

// ── Root App ──────────────────────────────────────────────────────────────────

export default function App() {
  const [active, setActive] = useState('dashboard')
  const [selectedCase, setSelectedCase] = useState(null)
  const [sidebarCounts, setSidebarCounts] = useState({})

  useEffect(() => {
    fetchDashboardStats().then(setSidebarCounts).catch(console.error)
  }, [])

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
      case 'partners': return <PartnersPage />
      default: return <Dashboard onViewCase={handleViewCase} />
    }
  }

  return (
    <div style={{ display: 'flex', minHeight: '100vh', background: C.bg }}>
      <Sidebar
        active={active}
        setActive={v => { setSelectedCase(null); setActive(v) }}
        counts={sidebarCounts}
      />
      <div style={{ marginLeft: 240, flex: 1, display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
        <header style={{
          background: C.surface, borderBottom: `1px solid ${C.border}`,
          padding: '14px 28px', display: 'flex', alignItems: 'center',
          justifyContent: 'space-between', position: 'sticky', top: 0, zIndex: 90,
        }}>
          <div style={{ fontSize: 13, color: C.textMuted }}>
            {active === 'case-detail' && selectedCase
              ? <span><span style={{ color: C.textFaint }}>Leads / </span><span style={{ fontFamily: "'IBM Plex Mono'", color: C.gold }}>{selectedCase.caseId}</span></span>
              : <span style={{ textTransform: 'capitalize', color: C.text }}>{active.replace('-', ' ')}</span>}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <div style={{ width: 7, height: 7, borderRadius: '50%', background: C.green, boxShadow: `0 0 6px ${C.green}` }} />
            <span style={{ fontSize: 11, color: C.textMuted }}>Firestore Live</span>
            <div style={{
              width: 28, height: 28, borderRadius: '50%',
              background: `linear-gradient(135deg, ${C.gold}, ${C.goldMuted})`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 11, fontWeight: 700, color: C.bg,
            }}>A</div>
          </div>
        </header>
        <main style={{ padding: 28, flex: 1 }}>
          {renderContent()}
        </main>
      </div>
    </div>
  )
}
