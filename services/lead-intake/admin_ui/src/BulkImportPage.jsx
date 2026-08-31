/**
 * admin_ui/src/BulkImportPage.jsx
 * Bulk lead import from Excel with user-selected column mapping.
 *
 * Flow:
 *   1. Pick an .xlsx file — header row is read CLIENT-SIDE (SheetJS) only to
 *      drive this mapping UI. Row data itself is never parsed or sent from
 *      the browser — the confirmed mapping + the raw file are both uploaded
 *      together, and the server does the authoritative parse only after the
 *      file clears a virus scan (see api/services/bulk_import_service.py).
 *   2. Map each detected column to a LeadRequest field (or leave unmapped).
 *   3. Submit -> poll job status (queued -> scanning -> processing ->
 *      succeeded/failed) -> show per-row results once it completes.
 */
import { useEffect, useRef, useState } from 'react'
import * as XLSX from 'xlsx'
import { C, Badge, Btn, Input, Select } from './App'
import {
  createBulkImportJob,
  getBulkImportJobStatus,
  getBulkImportJobResults,
} from './services/firebaseService'

// Mirrors REQUIRED_LEAD_FIELDS in api/services/bulk_import_service.py —
// keep in sync if that set changes.
const LEAD_FIELDS = [
  { path: 'firstName', label: 'First Name', required: true },
  { path: 'lastName', label: 'Last Name', required: true },
  { path: 'email', label: 'Email', required: true },
  { path: 'phone', label: 'Phone', required: true },
  { path: 'exposureLocation', label: 'Exposure Location', required: true },
  { path: 'exposureDates.start', label: 'Exposure Start Date', required: true },
  { path: 'exposureDates.end', label: 'Exposure End Date', required: true },
  { path: 'wtcHealthProgramStatus', label: 'WTC Health Program Status', required: true },
  { path: 'priorAttorney', label: 'Prior Attorney (Yes/No)', required: true },
  { path: 'ssn', label: 'SSN', required: false },
  { path: 'dateOfBirth', label: 'Date of Birth', required: false },
  { path: 'address.street', label: 'Address — Street', required: false },
  { path: 'address.city', label: 'Address — City', required: false },
  { path: 'address.state', label: 'Address — State', required: false },
  { path: 'address.zip', label: 'Address — Zip', required: false },
  { path: 'conditions', label: 'Conditions', required: false },
  { path: 'referralCode', label: 'Referral Code', required: false },
]

const REQUIRED_FIELDS = LEAD_FIELDS.filter(f => f.required).map(f => f.path)

// Loose header-text -> field guesses, used only to pre-fill the mapping UI —
// the user always confirms/edits before submitting.
const AUTO_MATCH = {
  firstname: 'firstName', 'first name': 'firstName', fname: 'firstName',
  lastname: 'lastName', 'last name': 'lastName', lname: 'lastName',
  email: 'email', 'email address': 'email',
  phone: 'phone', 'phone number': 'phone', mobile: 'phone',
  ssn: 'ssn', 'social security': 'ssn', 'social security number': 'ssn',
  dob: 'dateOfBirth', 'date of birth': 'dateOfBirth', birthdate: 'dateOfBirth',
  street: 'address.street', address: 'address.street', 'street address': 'address.street',
  city: 'address.city', state: 'address.state', zip: 'address.zip', zipcode: 'address.zip',
  'exposure location': 'exposureLocation', location: 'exposureLocation',
  'exposure start': 'exposureDates.start', 'exposure start date': 'exposureDates.start', 'start date': 'exposureDates.start',
  'exposure end': 'exposureDates.end', 'exposure end date': 'exposureDates.end', 'end date': 'exposureDates.end',
  'wtc health program status': 'wtcHealthProgramStatus', 'wtc status': 'wtcHealthProgramStatus',
  'prior attorney': 'priorAttorney',
  conditions: 'conditions',
  'referral code': 'referralCode', referral: 'referralCode',
}

function guessField(header) {
  const key = header.trim().toLowerCase()
  return AUTO_MATCH[key] || ''
}

const POLL_INTERVAL_MS = 2500

const STAGE_LABELS = {
  queued: 'Queued…',
  scanning: 'Scanning for viruses…',
  processing: 'Importing rows…',
  succeeded: 'Complete',
  failed: 'Failed',
  cancelled: 'Cancelled',
}

const OUTCOME_COLORS = {
  created: C.green, skipped_duplicate: C.yellow, failed: C.red,
}

export default function BulkImportPage() {
  const [file, setFile] = useState(null)
  const [headers, setHeaders] = useState([])
  const [mapping, setMapping] = useState({}) // { leadField: excelColumn }
  const [marketingSource, setMarketingSource] = useState('')
  const [defaultReferralCode, setDefaultReferralCode] = useState('')
  const [parseError, setParseError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState('')
  const [job, setJob] = useState(null)
  const [results, setResults] = useState(null)
  const [resultsFilter, setResultsFilter] = useState('')
  const pollRef = useRef(null)

  useEffect(() => () => clearTimeout(pollRef.current), [])

  const handleFileChange = (e) => {
    const f = e.target.files?.[0]
    setFile(f || null)
    setHeaders([])
    setMapping({})
    setParseError('')
    setJob(null)
    setResults(null)
    if (!f) return

    const reader = new FileReader()
    reader.onload = (evt) => {
      try {
        const workbook = XLSX.read(evt.target.result, { type: 'array' })
        const sheet = workbook.Sheets[workbook.SheetNames[0]]
        const rows = XLSX.utils.sheet_to_json(sheet, { header: 1, blankrows: false })
        const headerRow = (rows[0] || []).map(String).filter(h => h.trim())
        if (!headerRow.length) {
          setParseError('No header row found in the first sheet.')
          return
        }
        setHeaders(headerRow)
        const initialMapping = {}
        headerRow.forEach(h => {
          const guess = guessField(h)
          if (guess && !initialMapping[guess]) initialMapping[guess] = h
        })
        setMapping(initialMapping)
      } catch (err) {
        setParseError(`Could not read this file: ${err.message}`)
      }
    }
    reader.readAsArrayBuffer(f)
  }

  const missingRequired = REQUIRED_FIELDS.filter(f => !mapping[f])
  const canSubmit = file && headers.length > 0 && missingRequired.length === 0 && marketingSource.trim() && !submitting

  const handleSubmit = async () => {
    setSubmitting(true)
    setSubmitError('')
    try {
      const columnMappings = Object.entries(mapping)
        .filter(([, excelColumn]) => excelColumn)
        .map(([leadField, excelColumn]) => ({ excelColumn, leadField }))

      const payload = {
        columnMappings,
        headerRowIndex: 0,
        sheetName: null,
        marketingSource: marketingSource.trim(),
        defaultReferralCode: defaultReferralCode.trim() || null,
      }

      const createdJob = await createBulkImportJob(file, payload)
      setJob(createdJob)
      schedulePoll(createdJob.jobId)
    } catch (err) {
      setSubmitError(err.message || 'Failed to start the import job.')
    } finally {
      setSubmitting(false)
    }
  }

  const schedulePoll = (jobId) => {
    clearTimeout(pollRef.current)
    pollRef.current = setTimeout(async () => {
      try {
        const updated = await getBulkImportJobStatus(jobId)
        setJob(updated)
        if (['succeeded', 'failed', 'cancelled'].includes(updated.status)) {
          const page = await getBulkImportJobResults(jobId, { pageSize: 200 })
          setResults(page)
        } else {
          schedulePoll(jobId)
        }
      } catch (err) {
        console.error(err)
        schedulePoll(jobId)
      }
    }, POLL_INTERVAL_MS)
  }

  const loadFilteredResults = async (outcome) => {
    setResultsFilter(outcome)
    if (!job) return
    const page = await getBulkImportJobResults(job.jobId, { pageSize: 200, outcome: outcome || undefined })
    setResults(page)
  }

  const startOver = () => {
    clearTimeout(pollRef.current)
    setFile(null); setHeaders([]); setMapping({}); setMarketingSource('')
    setDefaultReferralCode(''); setJob(null); setResults(null); setResultsFilter('')
  }

  const labelStyle = { fontSize: 10, color: C.textMuted, letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 5 }

  return (
    <div style={{ maxWidth: 900 }}>
      <div style={{ marginBottom: 20 }}>
        <h1 style={{ fontFamily: "'DM Serif Display'", fontSize: 24, color: C.text, fontWeight: 400 }}>Bulk Import Leads</h1>
        <p style={{ color: C.textMuted, fontSize: 12, marginTop: 2 }}>
          Upload an Excel file, map its columns, and import leads through the same
          screening pipeline as manual entry.
        </p>
      </div>

      {!job && (
        <>
          <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 10, padding: 20, marginBottom: 16 }}>
            <div style={labelStyle}>Excel file (.xlsx)</div>
            <input type="file" accept=".xlsx" onChange={handleFileChange} style={{ color: C.text, fontSize: 12 }} />
            {parseError && <div style={{ color: C.red, fontSize: 12, marginTop: 10 }}>{parseError}</div>}
          </div>

          {headers.length > 0 && (
            <>
              <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 10, padding: 20, marginBottom: 16 }}>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
                  <div>
                    <div style={labelStyle}>Marketing Source (applied to every row) *</div>
                    <Input value={marketingSource} onChange={setMarketingSource} placeholder="e.g. bulk_import_2026" />
                  </div>
                  <div>
                    <div style={labelStyle}>Default Referral Code (optional)</div>
                    <Input value={defaultReferralCode} onChange={setDefaultReferralCode} placeholder="optional" />
                  </div>
                </div>
              </div>

              <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 10, padding: 20, marginBottom: 16 }}>
                <div style={{ fontSize: 10, color: C.gold, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', marginBottom: 14 }}>
                  Column Mapping
                </div>
                {LEAD_FIELDS.map(field => (
                  <div key={field.path} style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10 }}>
                    <div style={{ width: 220, fontSize: 12, color: C.text }}>
                      {field.label}{field.required && <span style={{ color: C.red }}> *</span>}
                    </div>
                    <Select
                      value={mapping[field.path] || ''}
                      onChange={v => setMapping(prev => ({ ...prev, [field.path]: v }))}
                      style={{ flex: 1 }}
                    >
                      <option value="">— Not mapped —</option>
                      {headers.map(h => <option key={h} value={h}>{h}</option>)}
                    </Select>
                  </div>
                ))}
                {missingRequired.length > 0 && (
                  <div style={{ color: C.yellow, fontSize: 11, marginTop: 8 }}>
                    Still required: {missingRequired.map(f => LEAD_FIELDS.find(lf => lf.path === f)?.label).join(', ')}
                  </div>
                )}
              </div>

              {submitError && <div style={{ color: C.red, fontSize: 12, marginBottom: 12 }}>{submitError}</div>}

              <Btn variant="primary" onClick={handleSubmit} disabled={!canSubmit}>
                {submitting ? 'Starting import…' : '⇪ Start Bulk Import'}
              </Btn>
            </>
          )}
        </>
      )}

      {job && (
        <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 10, padding: 22 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
            <div>
              <div style={{ fontSize: 13, color: C.text, fontWeight: 600 }}>{job.fileName}</div>
              <div style={{ fontSize: 11, color: C.textFaint, fontFamily: "'IBM Plex Mono'" }}>{job.jobId}</div>
            </div>
            <Badge label={STAGE_LABELS[job.status] || job.status} color={
              job.status === 'succeeded' ? C.green : job.status === 'failed' ? C.red : C.blue
            } />
          </div>

          {job.status === 'processing' && job.summary.totalRows > 0 && (
            <div style={{ marginBottom: 16 }}>
              <div style={{ height: 6, background: C.border, borderRadius: 3, overflow: 'hidden' }}>
                <div style={{
                  height: '100%', background: C.gold,
                  width: `${Math.min(100, (job.summary.processed / job.summary.totalRows) * 100)}%`,
                  transition: 'width 0.3s',
                }} />
              </div>
              <div style={{ fontSize: 11, color: C.textMuted, marginTop: 6 }}>
                {job.summary.processed} / {job.summary.totalRows} rows processed
              </div>
            </div>
          )}

          {job.errorMessage && (
            <div style={{ color: C.red, fontSize: 12, marginBottom: 16 }}>{job.errorMessage}</div>
          )}

          {['succeeded', 'failed'].includes(job.status) && (
            <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
              <StatChip label="Created" value={job.summary.created} color={C.green} />
              <StatChip label="Duplicates" value={job.summary.skipped} color={C.yellow} />
              <StatChip label="Failed" value={job.summary.failed} color={C.red} />
            </div>
          )}

          {results && (
            <div style={{ marginTop: 8 }}>
              <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
                {['', 'created', 'skipped_duplicate', 'failed'].map(o => (
                  <Btn key={o || 'all'} variant={resultsFilter === o ? 'primary' : 'ghost'} onClick={() => loadFilteredResults(o)}>
                    {o ? o.replace('_', ' ') : 'All'}
                  </Btn>
                ))}
              </div>
              <div style={{ maxHeight: 360, overflowY: 'auto', border: `1px solid ${C.border}`, borderRadius: 8 }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr style={{ borderBottom: `1px solid ${C.border}` }}>
                      {['Row', 'Outcome', 'Case ID', 'Detail'].map(h => (
                        <th key={h} style={{ padding: '8px 12px', textAlign: 'left', fontSize: 10, color: C.textMuted, textTransform: 'uppercase' }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {results.results.map(r => (
                      <tr key={r.rowNumber} style={{ borderBottom: `1px solid ${C.border}` }}>
                        <td style={{ padding: '8px 12px', fontSize: 11, color: C.textMuted }}>{r.rowNumber}</td>
                        <td style={{ padding: '8px 12px' }}>
                          <Badge label={r.outcome.replace('_', ' ')} color={OUTCOME_COLORS[r.outcome] || C.textMuted} />
                        </td>
                        <td style={{ padding: '8px 12px', fontSize: 11, fontFamily: "'IBM Plex Mono'", color: C.gold }}>{r.caseId || '—'}</td>
                        <td style={{ padding: '8px 12px', fontSize: 11, color: C.textMuted }}>{r.error?.message || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div style={{ marginTop: 18 }}>
            <Btn onClick={startOver}>← Import another file</Btn>
          </div>
        </div>
      )}
    </div>
  )
}

function StatChip({ label, value, color }) {
  return (
    <div style={{ background: C.bg, border: `1px solid ${color}44`, borderRadius: 8, padding: '8px 14px' }}>
      <div style={{ fontSize: 9, color: C.textFaint, textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 700, color, fontFamily: "'IBM Plex Mono'" }}>{value}</div>
    </div>
  )
}
