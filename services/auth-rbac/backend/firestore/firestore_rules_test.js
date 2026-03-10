/**
 * Firestore Security Rules — Emulator Test Suite
 *
 * Tests every role against every collection to verify:
 *   ✓ Client isolation (cannot read/write other clients' cases)
 *   ✓ Role-based access (each role gets exactly its permissions)
 *   ✓ PHI field protection (blocked below junior_partner)
 *   ✓ Audit log immutability (no client writes ever)
 *   ✓ Internal collections locked (sessions, rate_limits, portal_invites)
 *
 * Run:
 *   firebase emulators:exec --only firestore "npx jest firestore.rules.test.js"
 *   or:
 *   firebase emulators:start --only firestore &
 *   npx jest firestore.rules.test.js --watchAll
 *
 * Install deps (in project root, not functions/):
 *   npm install --save-dev jest @firebase/rules-unit-testing firebase
 */

const {
  initializeTestEnvironment,
  assertFails,
  assertSucceeds,
} = require('@firebase/rules-unit-testing');
const { readFileSync } = require('fs');
const { doc, getDoc, setDoc, updateDoc, deleteDoc, collection, addDoc } = require('firebase/firestore');

// ── Test environment setup ────────────────────────────────────────────────────
const PROJECT_ID  = 'legal-portal-test';
const RULES_PATH  = './firestore/firestore.rules';

let testEnv;

beforeAll(async () => {
  testEnv = await initializeTestEnvironment({
    projectId: PROJECT_ID,
    firestore: {
      rules: readFileSync(RULES_PATH, 'utf8'),
      host: 'localhost',
      port: 8080,
    },
  });
});

afterAll(async () => {
  await testEnv.cleanup();
});

afterEach(async () => {
  await testEnv.clearFirestore();
});

// ── Auth context factories ─────────────────────────────────────────────────────
const makeAuth = (uid, role, active = true) => ({
  uid,
  token: { role, active, email_verified: true },
});

const CLIENT_A      = makeAuth('client_a_uid',        'client');
const CLIENT_B      = makeAuth('client_b_uid',        'client');
const ADMIN_STAFF   = makeAuth('admin_staff_uid',     'admin_staff');
const PARALEGAL     = makeAuth('paralegal_uid',       'paralegal');
const JUNIOR        = makeAuth('junior_uid',          'junior_partner');
const SENIOR        = makeAuth('senior_uid',          'senior_partner');
const SUSPENDED     = makeAuth('suspended_uid',       'paralegal', false); // active=false
const UNAUTHENTICATED = null;

// Helper to get a Firestore instance for a given auth context
const db = (auth) => auth
  ? testEnv.authenticatedContext(auth.uid, auth.token).firestore()
  : testEnv.unauthenticatedContext().firestore();

// Seed helper — uses admin context (bypasses rules like Admin SDK does)
const seed = async (path, data) => {
  await testEnv.withSecurityRulesDisabled(async (ctx) => {
    await setDoc(doc(ctx.firestore(), path), data);
  });
};

// ════════════════════════════════════════════════════════════════════════════
// SECTION 1 — users collection
// ════════════════════════════════════════════════════════════════════════════
describe('users collection', () => {

  beforeEach(async () => {
    await seed('users/client_a_uid', {
      uid: 'client_a_uid', email: 'a@test.com', display_name: 'Client A',
      role: 'client', status: 'active',
    });
    await seed('users/admin_staff_uid', {
      uid: 'admin_staff_uid', email: 'admin@test.com', display_name: 'Admin',
      role: 'admin_staff', status: 'active',
    });
    await seed('users/paralegal_uid', {
      uid: 'paralegal_uid', email: 'para@test.com', display_name: 'Para',
      role: 'paralegal', status: 'active',
      phi_data: { health: 'sensitive' }, ssn: '123-45-6789',
    });
  });

  describe('READ', () => {
    test('client can read own profile', async () => {
      await assertSucceeds(getDoc(doc(db(CLIENT_A), 'users/client_a_uid')));
    });

    test('client CANNOT read another user profile', async () => {
      await assertFails(getDoc(doc(db(CLIENT_A), 'users/admin_staff_uid')));
    });

    test('admin_staff can read any user profile', async () => {
      await assertSucceeds(getDoc(doc(db(ADMIN_STAFF), 'users/client_a_uid')));
    });

    test('paralegal can read any user profile', async () => {
      await assertSucceeds(getDoc(doc(db(PARALEGAL), 'users/client_a_uid')));
    });

    test('senior_partner can read any user profile', async () => {
      await assertSucceeds(getDoc(doc(db(SENIOR), 'users/paralegal_uid')));
    });

    test('unauthenticated CANNOT read any profile', async () => {
      await assertFails(getDoc(doc(db(UNAUTHENTICATED), 'users/client_a_uid')));
    });

    test('suspended user CANNOT read profiles', async () => {
      await assertFails(getDoc(doc(db(SUSPENDED), 'users/client_a_uid')));
    });
  });

  describe('CREATE', () => {
    test('admin_staff can create a user', async () => {
      await assertSucceeds(setDoc(doc(db(ADMIN_STAFF), 'users/new_user'), {
        uid: 'new_user', email: 'new@test.com', display_name: 'New',
        role: 'client', status: 'active',
      }));
    });

    test('client CANNOT create a user', async () => {
      await assertFails(setDoc(doc(db(CLIENT_A), 'users/new_user'), {
        uid: 'new_user', email: 'new@test.com', role: 'client', status: 'active',
      }));
    });

    test('paralegal CANNOT create a user (not canManageUsers)', async () => {
      await assertFails(setDoc(doc(db(PARALEGAL), 'users/new_user'), {
        uid: 'new_user', role: 'client', status: 'active',
      }));
    });
  });

  describe('UPDATE — own profile (client)', () => {
    test('client can update own display_name', async () => {
      await assertSucceeds(updateDoc(doc(db(CLIENT_A), 'users/client_a_uid'), {
        display_name: 'Client A Updated', updated_at: new Date(),
      }));
    });

    test('client CANNOT change own role', async () => {
      await assertFails(updateDoc(doc(db(CLIENT_A), 'users/client_a_uid'), {
        role: 'senior_partner',
      }));
    });

    test('client CANNOT change own uid', async () => {
      await assertFails(updateDoc(doc(db(CLIENT_A), 'users/client_a_uid'), {
        uid: 'different_uid',
      }));
    });

    test('client CANNOT write PHI fields to own profile', async () => {
      await assertFails(updateDoc(doc(db(CLIENT_A), 'users/client_a_uid'), {
        phi_data: { health: 'injected' },
      }));
    });
  });

  describe('UPDATE — PHI field protection', () => {
    test('junior_partner CAN write PHI fields', async () => {
      await assertSucceeds(updateDoc(doc(db(JUNIOR), 'users/paralegal_uid'), {
        phi_data: { health: 'updated' }, updated_at: new Date(),
      }));
    });

    test('admin_staff CANNOT write PHI fields', async () => {
      await assertFails(updateDoc(doc(db(ADMIN_STAFF), 'users/paralegal_uid'), {
        phi_data: { health: 'injected' },
      }));
    });

    test('paralegal CANNOT write PHI fields', async () => {
      await assertFails(updateDoc(doc(db(PARALEGAL), 'users/paralegal_uid'), {
        ssn: '999-99-9999',
      }));
    });
  });

  describe('DELETE', () => {
    test('NOBODY can delete a user document (all roles blocked)', async () => {
      await assertFails(deleteDoc(doc(db(SENIOR), 'users/client_a_uid')));
      await assertFails(deleteDoc(doc(db(ADMIN_STAFF), 'users/client_a_uid')));
      await assertFails(deleteDoc(doc(db(CLIENT_A), 'users/client_a_uid')));
    });
  });
});


// ════════════════════════════════════════════════════════════════════════════
// SECTION 2 — cases collection (CLIENT ISOLATION)
// ════════════════════════════════════════════════════════════════════════════
describe('cases collection — client isolation', () => {

  beforeEach(async () => {
    await seed('cases/case_a', {
      client_uid: 'client_a_uid', title: 'Case A', status: 'open', case_type: 'family',
    });
    await seed('cases/case_b', {
      client_uid: 'client_b_uid', title: 'Case B', status: 'open', case_type: 'corporate',
    });
  });

  describe('READ — client isolation', () => {
    test('client_a can read own case', async () => {
      await assertSucceeds(getDoc(doc(db(CLIENT_A), 'cases/case_a')));
    });

    test('client_a CANNOT read client_b case', async () => {
      await assertFails(getDoc(doc(db(CLIENT_A), 'cases/case_b')));
    });

    test('client_b CANNOT read client_a case', async () => {
      await assertFails(getDoc(doc(db(CLIENT_B), 'cases/case_a')));
    });

    test('admin_staff can read any case', async () => {
      await assertSucceeds(getDoc(doc(db(ADMIN_STAFF), 'cases/case_a')));
      await assertSucceeds(getDoc(doc(db(ADMIN_STAFF), 'cases/case_b')));
    });

    test('paralegal can read any case', async () => {
      await assertSucceeds(getDoc(doc(db(PARALEGAL), 'cases/case_a')));
    });

    test('junior_partner can read any case', async () => {
      await assertSucceeds(getDoc(doc(db(JUNIOR), 'cases/case_b')));
    });

    test('senior_partner can read any case', async () => {
      await assertSucceeds(getDoc(doc(db(SENIOR), 'cases/case_a')));
    });

    test('unauthenticated CANNOT read any case', async () => {
      await assertFails(getDoc(doc(db(UNAUTHENTICATED), 'cases/case_a')));
    });
  });

  describe('CREATE', () => {
    test('admin_staff can create a case with required fields', async () => {
      await assertSucceeds(setDoc(doc(db(ADMIN_STAFF), 'cases/new_case'), {
        client_uid: 'client_a_uid', title: 'New Case', status: 'open',
      }));
    });

    test('paralegal can create a case', async () => {
      await assertSucceeds(setDoc(doc(db(PARALEGAL), 'cases/new_case_2'), {
        client_uid: 'client_a_uid', title: 'Para Case', status: 'open',
      }));
    });

    test('client CANNOT create a case', async () => {
      await assertFails(setDoc(doc(db(CLIENT_A), 'cases/new_case'), {
        client_uid: 'client_a_uid', title: 'Self Case', status: 'open',
      }));
    });

    test('admin_staff CANNOT create a case with PHI fields', async () => {
      await assertFails(setDoc(doc(db(ADMIN_STAFF), 'cases/phi_case'), {
        client_uid: 'client_a_uid', title: 'Bad Case', status: 'open',
        phi_data: { health: 'injected' },
      }));
    });
  });

  describe('UPDATE — graduated by role', () => {
    test('admin_staff can update allowed task fields', async () => {
      await assertSucceeds(updateDoc(doc(db(ADMIN_STAFF), 'cases/case_a'), {
        task_status: 'in_progress', updated_at: new Date(),
      }));
    });

    test('admin_staff CANNOT change case status', async () => {
      await assertFails(updateDoc(doc(db(ADMIN_STAFF), 'cases/case_a'), {
        status: 'closed',
      }));
    });

    test('paralegal can add notes-related fields', async () => {
      await assertSucceeds(updateDoc(doc(db(PARALEGAL), 'cases/case_a'), {
        updated_at: new Date(),
      }));
    });

    test('paralegal CANNOT approve/reject (change status)', async () => {
      await assertFails(updateDoc(doc(db(PARALEGAL), 'cases/case_a'), {
        status: 'approved',
      }));
    });

    test('junior_partner CAN approve/reject (change status)', async () => {
      await assertSucceeds(updateDoc(doc(db(JUNIOR), 'cases/case_a'), {
        status: 'approved', updated_at: new Date(),
      }));
    });

    test('senior_partner can update any field', async () => {
      await assertSucceeds(updateDoc(doc(db(SENIOR), 'cases/case_a'), {
        status: 'closed', escalation_reason: 'test', updated_at: new Date(),
      }));
    });

    test('client_a can update own case client_message only', async () => {
      await assertSucceeds(updateDoc(doc(db(CLIENT_A), 'cases/case_a'), {
        client_message: 'Hello', updated_at: new Date(),
      }));
    });

    test('client_a CANNOT update another client case', async () => {
      await assertFails(updateDoc(doc(db(CLIENT_A), 'cases/case_b'), {
        client_message: 'Injected',
      }));
    });

    test('client CANNOT change case status', async () => {
      await assertFails(updateDoc(doc(db(CLIENT_A), 'cases/case_a'), {
        status: 'closed',
      }));
    });
  });

  describe('DELETE', () => {
    test('NOBODY can delete a case (all roles blocked)', async () => {
      await assertFails(deleteDoc(doc(db(SENIOR),      'cases/case_a')));
      await assertFails(deleteDoc(doc(db(ADMIN_STAFF), 'cases/case_a')));
      await assertFails(deleteDoc(doc(db(CLIENT_A),    'cases/case_a')));
    });
  });
});


// ════════════════════════════════════════════════════════════════════════════
// SECTION 3 — cases/{caseId}/documents subcollection
// ════════════════════════════════════════════════════════════════════════════
describe('cases/{caseId}/documents subcollection', () => {

  beforeEach(async () => {
    await seed('cases/case_a', { client_uid: 'client_a_uid', title: 'Case A', status: 'open' });
    await seed('cases/case_a/documents/doc_1', {
      filename: 'contract.pdf', uploaded_by: 'admin_staff_uid',
      uploaded_at: new Date(), visible_to_client: true,
    });
    await seed('cases/case_a/documents/doc_staff_only', {
      filename: 'internal.pdf', uploaded_by: 'paralegal_uid',
      uploaded_at: new Date(), visible_to_client: false,
    });
  });

  describe('READ', () => {
    test('client sees only visible_to_client=true docs in own case', async () => {
      await assertSucceeds(getDoc(doc(db(CLIENT_A), 'cases/case_a/documents/doc_1')));
    });

    test('client CANNOT see visible_to_client=false docs', async () => {
      await assertFails(getDoc(doc(db(CLIENT_A), 'cases/case_a/documents/doc_staff_only')));
    });

    test('client_b CANNOT read docs from client_a case', async () => {
      await assertFails(getDoc(doc(db(CLIENT_B), 'cases/case_a/documents/doc_1')));
    });

    test('staff can read all documents', async () => {
      await assertSucceeds(getDoc(doc(db(ADMIN_STAFF), 'cases/case_a/documents/doc_staff_only')));
      await assertSucceeds(getDoc(doc(db(PARALEGAL),   'cases/case_a/documents/doc_staff_only')));
    });
  });

  describe('CREATE', () => {
    test('client can upload a doc to own case', async () => {
      await assertSucceeds(setDoc(doc(db(CLIENT_A), 'cases/case_a/documents/client_upload'), {
        filename: 'id.pdf', uploaded_by: 'client_a_uid', uploaded_at: new Date(),
      }));
    });

    test('client CANNOT upload with a different uploaded_by', async () => {
      await assertFails(setDoc(doc(db(CLIENT_A), 'cases/case_a/documents/fake_upload'), {
        filename: 'id.pdf', uploaded_by: 'different_uid', uploaded_at: new Date(),
      }));
    });

    test('client_b CANNOT upload to client_a case', async () => {
      await assertFails(setDoc(doc(db(CLIENT_B), 'cases/case_a/documents/bad_upload'), {
        filename: 'id.pdf', uploaded_by: 'client_b_uid', uploaded_at: new Date(),
      }));
    });

    test('paralegal can upload to any case', async () => {
      await assertSucceeds(setDoc(doc(db(PARALEGAL), 'cases/case_a/documents/para_upload'), {
        filename: 'brief.pdf', uploaded_by: 'paralegal_uid', uploaded_at: new Date(),
      }));
    });
  });

  describe('DELETE', () => {
    test('senior_partner can delete a document', async () => {
      await assertSucceeds(deleteDoc(doc(db(SENIOR), 'cases/case_a/documents/doc_1')));
    });

    test('admin_staff CANNOT delete a document', async () => {
      await assertFails(deleteDoc(doc(db(ADMIN_STAFF), 'cases/case_a/documents/doc_1')));
    });

    test('client CANNOT delete any document', async () => {
      await assertFails(deleteDoc(doc(db(CLIENT_A), 'cases/case_a/documents/doc_1')));
    });
  });
});


// ════════════════════════════════════════════════════════════════════════════
// SECTION 4 — cases/{caseId}/notes subcollection
// ════════════════════════════════════════════════════════════════════════════
describe('cases/{caseId}/notes subcollection', () => {

  beforeEach(async () => {
    await seed('cases/case_a', { client_uid: 'client_a_uid', title: 'Case A', status: 'open' });
    await seed('cases/case_a/notes/note_visible', {
      content: 'Visible note', author_uid: 'paralegal_uid',
      created_at: new Date(), is_client_visible: true, is_privileged: false,
    });
    await seed('cases/case_a/notes/note_hidden', {
      content: 'Hidden note', author_uid: 'paralegal_uid',
      created_at: new Date(), is_client_visible: false, is_privileged: false,
    });
    await seed('cases/case_a/notes/note_privileged', {
      content: 'Attorney-client privileged', author_uid: 'junior_uid',
      created_at: new Date(), is_client_visible: false, is_privileged: true,
    });
  });

  describe('READ', () => {
    test('client sees only is_client_visible=true non-privileged notes', async () => {
      await assertSucceeds(getDoc(doc(db(CLIENT_A), 'cases/case_a/notes/note_visible')));
    });

    test('client CANNOT see hidden notes', async () => {
      await assertFails(getDoc(doc(db(CLIENT_A), 'cases/case_a/notes/note_hidden')));
    });

    test('client CANNOT see privileged notes', async () => {
      await assertFails(getDoc(doc(db(CLIENT_A), 'cases/case_a/notes/note_privileged')));
    });

    test('admin_staff can read non-privileged notes', async () => {
      await assertSucceeds(getDoc(doc(db(ADMIN_STAFF), 'cases/case_a/notes/note_hidden')));
    });

    test('admin_staff CANNOT read privileged notes', async () => {
      await assertFails(getDoc(doc(db(ADMIN_STAFF), 'cases/case_a/notes/note_privileged')));
    });

    test('paralegal CANNOT read privileged notes', async () => {
      await assertFails(getDoc(doc(db(PARALEGAL), 'cases/case_a/notes/note_privileged')));
    });

    test('junior_partner CAN read privileged notes', async () => {
      await assertSucceeds(getDoc(doc(db(JUNIOR), 'cases/case_a/notes/note_privileged')));
    });

    test('senior_partner can read all notes', async () => {
      await assertSucceeds(getDoc(doc(db(SENIOR), 'cases/case_a/notes/note_privileged')));
    });
  });

  describe('CREATE', () => {
    test('paralegal can add a note', async () => {
      await assertSucceeds(setDoc(doc(db(PARALEGAL), 'cases/case_a/notes/new_note'), {
        content: 'New note', author_uid: 'paralegal_uid', created_at: new Date(),
        is_client_visible: false, is_privileged: false,
      }));
    });

    test('admin_staff CANNOT add a note (below paralegal)', async () => {
      await assertFails(setDoc(doc(db(ADMIN_STAFF), 'cases/case_a/notes/bad_note'), {
        content: 'Bad note', author_uid: 'admin_staff_uid', created_at: new Date(),
      }));
    });

    test('client CANNOT add a note', async () => {
      await assertFails(setDoc(doc(db(CLIENT_A), 'cases/case_a/notes/client_note'), {
        content: 'Client note', author_uid: 'client_a_uid', created_at: new Date(),
      }));
    });

    test('paralegal CANNOT create a note with a different author_uid', async () => {
      await assertFails(setDoc(doc(db(PARALEGAL), 'cases/case_a/notes/fake_note'), {
        content: 'Spoofed', author_uid: 'someone_else_uid', created_at: new Date(),
      }));
    });
  });
});


// ════════════════════════════════════════════════════════════════════════════
// SECTION 5 — phi_records collection
// ════════════════════════════════════════════════════════════════════════════
describe('phi_records collection', () => {

  beforeEach(async () => {
    await seed('phi_records/client_a_uid', {
      health_conditions: ['hypertension'], medications: ['lisinopril'],
    });
  });

  test('junior_partner can read PHI records', async () => {
    await assertSucceeds(getDoc(doc(db(JUNIOR), 'phi_records/client_a_uid')));
  });

  test('senior_partner can read and write PHI records', async () => {
    await assertSucceeds(getDoc(doc(db(SENIOR), 'phi_records/client_a_uid')));
    await assertSucceeds(updateDoc(doc(db(SENIOR), 'phi_records/client_a_uid'), {
      notes: 'Updated',
    }));
  });

  test('paralegal CANNOT read PHI records', async () => {
    await assertFails(getDoc(doc(db(PARALEGAL), 'phi_records/client_a_uid')));
  });

  test('admin_staff CANNOT read PHI records', async () => {
    await assertFails(getDoc(doc(db(ADMIN_STAFF), 'phi_records/client_a_uid')));
  });

  test('client CANNOT read own PHI record (goes through staff only)', async () => {
    await assertFails(getDoc(doc(db(CLIENT_A), 'phi_records/client_a_uid')));
  });

  test('only senior_partner can delete a PHI record', async () => {
    await assertSucceeds(deleteDoc(doc(db(SENIOR), 'phi_records/client_a_uid')));
  });

  test('junior_partner CANNOT delete a PHI record', async () => {
    await assertFails(deleteDoc(doc(db(JUNIOR), 'phi_records/client_a_uid')));
  });
});


// ════════════════════════════════════════════════════════════════════════════
// SECTION 6 — audit_log (IMMUTABILITY)
// ════════════════════════════════════════════════════════════════════════════
describe('audit_log collection — immutability', () => {

  beforeEach(async () => {
    await seed('audit_log/log_1', {
      event_type: 'permission_denied', uid: 'client_a_uid',
      role: 'client', timestamp: new Date(),
    });
  });

  test('senior_partner CAN read audit log', async () => {
    await assertSucceeds(getDoc(doc(db(SENIOR), 'audit_log/log_1')));
  });

  test('junior_partner CANNOT read audit log', async () => {
    await assertFails(getDoc(doc(db(JUNIOR), 'audit_log/log_1')));
  });

  test('admin_staff CANNOT read audit log', async () => {
    await assertFails(getDoc(doc(db(ADMIN_STAFF), 'audit_log/log_1')));
  });

  test('client CANNOT read audit log', async () => {
    await assertFails(getDoc(doc(db(CLIENT_A), 'audit_log/log_1')));
  });

  test('NOBODY can create audit log entries from client SDK', async () => {
    await assertFails(addDoc(collection(db(SENIOR),      'audit_log'), { event: 'injected' }));
    await assertFails(addDoc(collection(db(ADMIN_STAFF), 'audit_log'), { event: 'injected' }));
    await assertFails(addDoc(collection(db(CLIENT_A),    'audit_log'), { event: 'injected' }));
  });

  test('NOBODY can update audit log entries', async () => {
    await assertFails(updateDoc(doc(db(SENIOR),      'audit_log/log_1'), { event_type: 'tampered' }));
    await assertFails(updateDoc(doc(db(ADMIN_STAFF), 'audit_log/log_1'), { event_type: 'tampered' }));
  });

  test('NOBODY can delete audit log entries', async () => {
    await assertFails(deleteDoc(doc(db(SENIOR),      'audit_log/log_1')));
    await assertFails(deleteDoc(doc(db(ADMIN_STAFF), 'audit_log/log_1')));
    await assertFails(deleteDoc(doc(db(CLIENT_A),    'audit_log/log_1')));
  });
});


// ════════════════════════════════════════════════════════════════════════════
// SECTION 7 — Internal collections (sessions, rate_limits, portal_invites)
// ════════════════════════════════════════════════════════════════════════════
describe('internal collections — fully locked from client SDK', () => {

  beforeEach(async () => {
    await seed('_sessions/sess_1',      { uid: 'client_a_uid', active: true });
    await seed('_rate_limits/hash_1',   { attempts: 3, window_start: new Date() });
    await seed('_portal_invites/tok_1', { email: 'a@test.com', used: false });
  });

  const internalCollections = ['_sessions', '_rate_limits', '_portal_invites'];
  const docIds = { _sessions: 'sess_1', _rate_limits: 'hash_1', _portal_invites: 'tok_1' };

  for (const col of internalCollections) {
    describe(col, () => {
      test('senior_partner CANNOT read', async () => {
        await assertFails(getDoc(doc(db(SENIOR), `${col}/${docIds[col]}`)));
      });
      test('admin_staff CANNOT read', async () => {
        await assertFails(getDoc(doc(db(ADMIN_STAFF), `${col}/${docIds[col]}`)));
      });
      test('client CANNOT read', async () => {
        await assertFails(getDoc(doc(db(CLIENT_A), `${col}/${docIds[col]}`)));
      });
      test('NOBODY can write', async () => {
        await assertFails(setDoc(doc(db(SENIOR), `${col}/injected`), { data: 'bad' }));
        await assertFails(setDoc(doc(db(CLIENT_A), `${col}/injected`), { data: 'bad' }));
      });
      test('NOBODY can delete', async () => {
        await assertFails(deleteDoc(doc(db(SENIOR), `${col}/${docIds[col]}`)));
        await assertFails(deleteDoc(doc(db(CLIENT_A), `${col}/${docIds[col]}`)));
      });
    });
  }
});


// ════════════════════════════════════════════════════════════════════════════
// SECTION 8 — Catch-all (unknown collections are denied)
// ════════════════════════════════════════════════════════════════════════════
describe('catch-all — unknown collections denied', () => {
  test('senior_partner CANNOT read an unknown collection', async () => {
    await assertFails(getDoc(doc(db(SENIOR), 'unknown_collection/doc_1')));
  });

  test('client CANNOT read an unknown collection', async () => {
    await assertFails(getDoc(doc(db(CLIENT_A), 'unknown_collection/doc_1')));
  });

  test('NOBODY can write to an unknown collection', async () => {
    await assertFails(setDoc(doc(db(SENIOR), 'unknown_collection/doc_1'), { data: 'bad' }));
  });
});
