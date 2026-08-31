/**
 * admin_ui/src/services/firebaseService.js
 * Firestore real-time queries and case management operations.
 */
import { initializeApp } from 'firebase/app'
import {
  getFirestore,
  collection,
  query,
  where,
  orderBy,
  limit,
  startAfter,
  getDocs,
  getDoc,
  doc,
  updateDoc,
  onSnapshot,
  serverTimestamp,
  getCountFromServer,
} from 'firebase/firestore'

import { getAuth } from 'firebase/auth'

const LEAD_INTAKE_URL = import.meta.env.VITE_LEAD_INTAKE_URL

async function getAuthHeaders() {
  const user = getAuth().currentUser
  if (!user) throw new Error('Not authenticated')
  const token = await user.getIdToken()
  return {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json',
  }
}

// Multipart/form-data requests must NOT set Content-Type manually — the
// browser needs to add its own boundary parameter, which fetch() only does
// when Content-Type is left unset.
async function getMultipartAuthHeaders() {
  const user = getAuth().currentUser
  if (!user) throw new Error('Not authenticated')
  const token = await user.getIdToken()
  return { 'Authorization': `Bearer ${token}` }
}
const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
}

const app = initializeApp(firebaseConfig)
const db = getFirestore(app)

const CASES = 'cases'
const PAGE_SIZE = 50

// ── Fetch cases with filters + cursor pagination ─────────────────────────────

export async function fetchCases(filters = {}, cursorDoc = null) {
  const constraints = [orderBy('createdAt', 'desc'), limit(PAGE_SIZE + 1)]

  if (filters.status) constraints.unshift(where('status', '==', filters.status))
  if (filters.vcfEligibility) constraints.unshift(where('vcfEligibility', '==', filters.vcfEligibility))
  if (filters.source) constraints.unshift(where('marketingSource', '==', filters.source))
  if (filters.assignedTo) constraints.unshift(where('assignedTo', '==', filters.assignedTo))

  // Date range filter
  if (filters.dateFrom) {
    constraints.unshift(where('createdAt', '>=', new Date(filters.dateFrom)))
  }
  if (filters.dateTo) {
    const endDate = new Date(filters.dateTo)
    endDate.setHours(23, 59, 59, 999)
    constraints.unshift(where('createdAt', '<=', endDate))
  }

  let q = query(collection(db, CASES), ...constraints)
  if (cursorDoc) q = query(collection(db, CASES), ...constraints, startAfter(cursorDoc))

  const snap = await getDocs(q)
  const hasMore = snap.docs.length > PAGE_SIZE
  const docs = hasMore ? snap.docs.slice(0, PAGE_SIZE) : snap.docs

  return {
    cases: docs.map(d => ({ id: d.id, ...d.data() })),
    lastDoc: docs[docs.length - 1] || null,
    hasMore,
  }
}

// ── Search by email or name prefix ───────────────────────────────────────────

export async function searchCases(searchTerm) {
  const term = searchTerm.toLowerCase().trim()
  if (!term) return []

  // Email prefix search
  const emailQ = query(
    collection(db, CASES),
    where('email', '>=', term),
    where('email', '<=', term + '\uf8ff'),
    orderBy('email'),
    limit(20)
  )

  const snap = await getDocs(emailQ)
  return snap.docs.map(d => ({ id: d.id, ...d.data() }))
}

// ── Fetch a single case ───────────────────────────────────────────────────────

export async function fetchCase(caseId) {
  const snap = await getDoc(doc(db, CASES, caseId))
  return snap.exists() ? { id: snap.id, ...snap.data() } : null
}

// ── Fetch dashboard stats via aggregation queries ────────────────────────────

export async function fetchDashboardStats() {
  const statusList = ['New Lead', 'Screened', 'Qualified', 'Disqualified', 'Needs Review', 'Active', 'Closed']
  const eligibilityList = ['eligible', 'ineligible', 'needs_review', 'pending']
  const stats = {}

  await Promise.all([
    ...statusList.map(async s => {
      const snap = await getCountFromServer(query(collection(db, CASES), where('status', '==', s)))
      stats[s] = snap.data().count
    }),
    ...eligibilityList.map(async e => {
      const snap = await getCountFromServer(query(collection(db, CASES), where('vcfEligibility', '==', e)))
      stats[e] = snap.data().count
    }),
  ])

  return stats
}

// ── Update a single case status ───────────────────────────────────────────────

export async function updateCaseStatus(caseId, newStatus, updatedBy = 'admin', note = '') {
  const ref = doc(db, CASES, caseId)
  const historyEntry = {
    status: newStatus,
    timestamp: new Date().toISOString(),
    updatedBy,
    note,
  }
  await updateDoc(ref, {
    status: newStatus,
    updatedAt: serverTimestamp(),
    statusHistory: { arrayUnion: historyEntry }, // handled client-side merge
  })
}

// ── Assign case ───────────────────────────────────────────────────────────────

export async function assignCase(caseId, assignTo) {
  await updateDoc(doc(db, CASES, caseId), {
    assignedTo: assignTo,
    updatedAt: serverTimestamp(),
  })
}

// ── Real-time subscription ────────────────────────────────────────────────────

export function subscribeToRecentCases(callback, statusFilter = null) {
  const constraints = [orderBy('createdAt', 'desc'), limit(PAGE_SIZE)]
  if (statusFilter) constraints.unshift(where('status', '==', statusFilter))
  const q = query(collection(db, CASES), ...constraints)
  return onSnapshot(q, snap => {
    callback(snap.docs.map(d => ({ id: d.id, ...d.data() })))
  })
}

// ── Export to CSV (client-side) ───────────────────────────────────────────────

export function exportToCsv(cases) {
  const headers = [
    'Case ID', 'First Name', 'Last Name', 'Email', 'Phone',
    'Status', 'VCF Eligibility', 'Exposure Location',
    'Exposure Start', 'Exposure End', 'WTC Program',
    'Prior Attorney', 'Marketing Source', 'Assigned To', 'Created At',
  ]
  const rows = cases.map(c => [
    c.caseId, c.firstName, c.lastName, c.email, c.phone,
    c.status, c.vcfEligibility, c.exposureLocation,
    c.exposureDateStart, c.exposureDateEnd, c.wtcHealthProgramStatus,
    c.priorAttorney ? 'Yes' : 'No', c.marketingSource, c.assignedTo || '',
    c.createdAt ? new Date(c.createdAt?.seconds ? c.createdAt.seconds * 1000 : c.createdAt).toISOString() : '',
  ])

  const csv = [headers, ...rows].map(r => r.map(cell => `"${String(cell || '').replace(/"/g, '""')}"`).join(',')).join('\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `leads_export_${new Date().toISOString().slice(0, 10)}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

export async function createPartner(name) {
  const headers = await getAuthHeaders()
  const resp = await fetch(`${LEAD_INTAKE_URL}/api/v1/admin/partners`, {
    method: 'POST', headers,
    body: JSON.stringify({ name, allowedIps: [], requireHmac: false }),
  })
  return resp.json()
}

export async function generateApiKey(partnerId, label) {
  const headers = await getAuthHeaders()
  const resp = await fetch(`${LEAD_INTAKE_URL}/api/v1/admin/partners/${partnerId}/keys`, {
    method: 'POST', headers,
    body: JSON.stringify({ label }),
  })
  return resp.json()
}

export async function listPartners() {
  const headers = await getAuthHeaders()
  const resp = await fetch(`${LEAD_INTAKE_URL}/api/v1/admin/partners`, { headers })
  return resp.json()
}

export async function updateLeadStatus(caseId, status, note = '') {
  const headers = await getAuthHeaders()
  const resp = await fetch(`${LEAD_INTAKE_URL}/api/v1/leads/${caseId}/status`, {
    method: 'PATCH', headers,
    body: JSON.stringify({ status, note }),
  })
  return resp.json()
}

export async function bulkAssignLeads(caseIds, assignTo) {
  const headers = await getAuthHeaders()
  const resp = await fetch(`${LEAD_INTAKE_URL}/api/v1/leads/bulk-assign`, {
    method: 'POST', headers,
    body: JSON.stringify({ caseIds, assignTo }),
  })
  return resp.json()
}

// ── Bulk import (Excel with column mapping) ──────────────────────────────────

export async function createBulkImportJob(file, mapping) {
  const headers = await getMultipartAuthHeaders()
  const formData = new FormData()
  formData.append('file', file)
  formData.append('mapping', JSON.stringify(mapping))

  const resp = await fetch(`${LEAD_INTAKE_URL}/api/v1/leads/bulk-import`, {
    method: 'POST', headers, body: formData,
  })
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}))
    throw new Error(body?.message || `Bulk import failed (${resp.status})`)
  }
  return resp.json()
}

export async function getBulkImportJobStatus(jobId) {
  const headers = await getAuthHeaders()
  const resp = await fetch(`${LEAD_INTAKE_URL}/api/v1/leads/bulk-import/${jobId}`, { headers })
  return resp.json()
}

export async function getBulkImportJobResults(jobId, { pageSize = 100, pageToken, outcome } = {}) {
  const headers = await getAuthHeaders()
  const params = new URLSearchParams({ pageSize: String(pageSize) })
  if (pageToken) params.set('pageToken', pageToken)
  if (outcome) params.set('outcome', outcome)
  const resp = await fetch(`${LEAD_INTAKE_URL}/api/v1/leads/bulk-import/${jobId}/results?${params}`, { headers })
  return resp.json()
}