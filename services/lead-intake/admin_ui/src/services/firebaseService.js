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
