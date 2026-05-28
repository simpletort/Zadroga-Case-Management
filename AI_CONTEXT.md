# AI_CONTEXT.md — SimpleTort Canonical Project Context

> This document is the authoritative reference for all AI tools on this project. Read it before making any suggestion, generating any code, or proposing any architecture change.

---

## PROJECT

**SimpleTort** is an AI-powered legal case management platform for high-volume law firms.

| Attribute | Value |
|---|---|
| Practice areas | `mass_tort`, `personal_injury`, `workers_comp` |
| Lifecycle stages | Lead Intake → Document Collection → AI Document Processing → Program Enrollment & Deadlines → Attorney Review & Filing → Settlement & Disbursement |

---

## TECH STACK

| Layer | Technology |
|---|---|
| Runtime | Python 3.11, FastAPI |
| Hosting | Google Cloud Run (one service per container) |
| Database | Cloud Firestore (native mode) |
| Auth | Firebase Auth + custom RBAC (JWT claims) |
| Async messaging | Google Cloud Pub/Sub |
| Scheduled tasks | Google Cloud Tasks |
| Workflow orchestration | Google Cloud Workflows |
| File storage | Google Cloud Storage (GCS) |
| Email | SendGrid |
| SMS | Twilio |
| AI/ML | Vertex AI, Document AI, MedLM (evidence-management service — not yet built) |
| CI/CD | Google Cloud Build (`cloudbuild.yaml` per service) |
| API Gateway | Google Cloud API Gateway (`openapi.yaml` at repo root) |
| Virus scanning | ClamAV (`cloud-functions/virus-scanner`) |
| Shared lib | `shared/` package installed as editable dep in each service |

---

## REPO STRUCTURE

### `services/`

| Folder | Description |
|---|---|
| `auth-rbac/` | Firebase Auth, RBAC role management, JWT claims **(RED zone — do not modify auth logic here without extreme care)** |
| `case-development/` | Attorney review, escalation, approval chain, case dashboard |
| `enrollment-workflow/` | VCF/WTC program enrollment, deadlines, timeline tracking |
| `lead-intake/` | Partner API, lead ingestion, duplicate detection, eligibility screener |
| `notification/` | Email (SendGrid) + SMS (Twilio), templates, opt-out, delivery tracking |
| `reporting-service/` | KPIs, case/lead/staff aggregation, dashboard metrics |
| `settlement-financial/` | Settlement calculator, fee config, PDF statements, lien/expense tracking |
| `storage-gateway/` | GCS upload, signed URLs, document lifecycle, audit logging |
| `task-management/` | Task assignment, reminders, user task queues |
| `workflow-orchestrator/` | Event-driven workflow engine, Cloud Workflows trigger, PubSub handler |

#### Skeleton services (scaffolded only — do not call these services)

| Folder | Intended purpose |
|---|---|
| `evidence-management/` | Document AI OCR + MedLM qualification scoring |
| `hipaa-compliance/` | *(not yet implemented)* |
| `vcf-claim-tracking/` | *(not yet implemented)* |
| `revenue-analytics/` | *(not yet implemented)* |
| `reporting-kpi/` | *(not yet implemented)* |
| `counsel-substitution/` | *(not yet implemented)* |
| `external-sync/` | *(not yet implemented)* |

### `cloud-functions/`

| Folder | Description |
|---|---|
| `case-assignment/` | Auto-assigns new cases to paralegals |
| `deadline-alerter/` | Fires deadline notifications at 90/30/7 days |
| `intake-drive-sync/` | Syncs lead intake docs to Google Drive |
| `case-reminder-trigger/` | Schedules task reminders via Cloud Tasks |
| `virus-scanner/` | ClamAV scan triggered on GCS upload events |
| `build-notifier/` | CI/CD Teams notifications |

### `shared/shared/middlewares/`

| Module | Purpose |
|---|---|
| `auth.py` | JWT verification, exposes `request.state.user_role` |
| `cors.py` | CORS configuration |
| `logging.py` | Structured logging |
| `error_handler.py` | Standardized error responses |
| `file_validation.py` | Upload validation helpers |
| `signed_url_expiry.py` | GCS signed URL expiry helpers |

### `services/workflow-orchestrator/cloud_workflows/`

`lead-qualification.yaml`, `client-onboarding.yaml`, `medical-processing.yaml`, `settlement.yaml`, `vcf-enrollment.yaml`

---

## SERVICE ARCHITECTURE PATTERN

Every service follows this standard layout:

```
main.py
app/
  config.py          # Pydantic Settings — all config here
  models/            # Pydantic request/response models
  routes/            # Thin route handlers — delegate to services/
  services/          # Business logic lives here
  utils/
    firestore.py     # Firestore wrapper — never instantiate Client() directly elsewhere
tests/
requirements.txt
Dockerfile
cloudbuild.yaml
```

---

## PRACTICE AREAS & CAMPAIGNS

### `mass_tort`
- Has **campaigns** (e.g. Zadroga, Camp Lejeune, Roundup).
- Each campaign carries its own eligibility ruleset, filing deadlines, document requirements, and fee config.
- Campaign is a **first-class entity**, admin-configurable.

### `personal_injury`
- `case_type` only. No campaign concept. No sub-types yet.

### `workers_comp`
- `case_type` only. No campaign concept. No sub-types yet.

---

## CASE STATUS MACHINE

### Lead statuses (`lead-intake` service)

```
New Lead → Screened → Qualified ──────────────→ Active → Closed
                    → Disqualified
                    → Needs Review → (human decision) → Qualified or Disqualified
```

### Case statuses — shared approval chain (`case-development` service)

```
Pending Paralegal Review
  → Pending Attorney Review
      → Approved for Filing                     [manual: attorney sign-off]
      → Pending Senior Review                   [manual: attorney escalates — discretionary]
          → Approved for Filing                 [manual: senior partner approves]
          → Pending Attorney Review             [manual: senior de-escalates]
          → Pending Paralegal Review            [manual: senior de-escalates further]
      → Rejected                                [manual: attorney rejects]
          → Pending Paralegal Review            [manual: reinstatement]
  ← Pending Paralegal Review                    [manual: attorney flags back]
```

### Case statuses — type-specific middle stages

These run between the "Active" lead status and "Pending Paralegal Review":

| Practice Area | Stages (in order) | Trigger |
|---|---|---|
| `mass_tort` | Enrolled (via enrollment-workflow) | Automated by workflow-orchestrator |
| `personal_injury` | Investigation → Demand Sent → Negotiating → Litigation (if no settlement) | Manual user transitions |
| `workers_comp` | Claim Filed → IME Scheduled → Hearing Scheduled → Award / Settlement | Manual user transitions |

**Automated transitions** are triggered by `workflow-orchestrator` publishing Pub/Sub events. All other transitions are **manual** (user action via API).

---

## ELIGIBILITY SCREENING

| Practice Area | Method | Outcomes |
|---|---|---|
| `mass_tort` | Admin-configurable ruleset per campaign (exposure dates, diagnosis codes, geographic criteria, etc.) | Qualified / Disqualified / Needs Review |
| `personal_injury` | No automated screener yet — manual qualification | N/A |
| `workers_comp` | No automated screener yet — manual qualification | N/A |

- **Needs Review** routes to a human for a final decision before the lead can proceed.

---

## DUPLICATE DETECTION

| Practice Area | Hard Duplicate | Fuzzy Duplicate |
|---|---|---|
| `mass_tort` | SSN + DOB → auto-flag | Name + DOB + phone → Needs Review |
| `personal_injury` | Name + DOB + incident date + incident type | — |
| `workers_comp` | Name + DOB + employer + injury date | — |

---

## APPROVAL CHAIN

Identical across all three practice areas:

1. Paralegal collects all required documents and completes initial review.
2. Paralegal submits → case moves to **Pending Attorney Review**.
3. Attorney reviews. If anything is missing or needs correction, flags back to paralegal (case returns to **Pending Paralegal Review**).
4. Paralegal updates. Cycle repeats until attorney is satisfied.
5. Attorney gives final sign-off → **Approved for Filing**.
6. Attorney may optionally escalate → **Pending Senior Review** (discretionary, not mandatory).
7. Senior partner reviews and either approves or returns to attorney.

---

## DEADLINES

Two types run in parallel on every case:

| Type | Description | Consequence | Alert recipients |
|---|---|---|---|
| Hard deadlines | External cutoffs (filing windows, statute of limitations, program enrollment cutoffs) | Missing can kill the case | Attorney + senior partner |
| Internal SLAs | Firm-set targets (e.g. doc collection within X days, attorney review within Y days) | Missing is an ops issue | Assigned paralegal + manager |

- Both types are **end-user configurable** per case.
- Mass tort campaigns have **campaign-level deadline defaults** that apply unless overridden at case level.
- Alerts fire at **90, 30, and 7 days** before the deadline.

---

## SETTLEMENT CALCULATION

- **Attorney contingency fee percentage**: user-configurable per case type or campaign.
- **Lien deduction order**: user-configurable per case (before or after attorney fees).
- **Case expenses**: filing fees, expert witnesses, medical record costs, etc. — tracked per case and included in the waterfall.
- The calculator applies whatever fee/lien/expense waterfall the user has configured. **No hardcoded percentages or order of operations.**

---

## CASE ASSIGNMENT

| Type | Logic |
|---|---|
| Auto-assignment | Workload-balanced round robin — assign to the paralegal with the lowest current active caseload, cycling through the team |
| Manual override | Any manager can reassign at any time. Manual assignment takes precedence over auto-assignment. |

---

## DOCUMENTS

- Required document checklists are **configurable per case type** and **per campaign** (mass tort).
- Document completeness is tracked against the configured checklist for that case.
- **All file operations route through `storage-gateway`. No service calls GCS directly.**

---

## RBAC ROLES

| Role | Access Level |
|---|---|
| `admin` | Full system: user management, campaign config, disbursement |
| `senior_partner` | Campaign analytics, all cases, final approval |
| `junior_partner` | Assigned cases, approval workflow, escalation |
| `paralegal` | Assigned case queue, document review, client communications |
| `intake_staff` | Lead intake and initial screening only |

- Role is set as a **custom claim on the Firebase JWT**.
- Shared auth middleware exposes `request.state.user_role` after verification.
- Always import from `shared/shared/middlewares/auth.py` — never re-implement token verification.

---

## KEY FIRESTORE COLLECTIONS

| Collection | Owning service |
|---|---|
| `leads` | `lead-intake` |
| `cases` | `case-development` |
| `case_assignments` | `case-development` |
| `attorney_reviews` | `case-development` |
| `escalations` | `case-development` |
| `enrollments` | `enrollment-workflow` |
| `tasks` | `task-management` |
| `notifications` | `notification` |
| `documents` | `storage-gateway` |
| `settlements` | `settlement-financial` |
| `campaigns` | `lead-intake` / `enrollment-workflow` |

---

## NAMING CONVENTIONS

| Artifact | Convention |
|---|---|
| Firestore collections | `snake_case` plural |
| Firestore fields | `snake_case` |
| API endpoints | REST, kebab-case paths — e.g. `/api/v1/cases/{case_id}/attorney-review` |
| Python | PEP 8: `PascalCase` classes, `snake_case` functions/vars |
| Cloud Run services | `kebab-case` |
| Pub/Sub topics | `kebab-case` |
| Cloud Workflow names | `kebab-case` |

---

## PATTERNS TO FOLLOW

Enforce these in every suggestion and every code change:

| Pattern | Rule |
|---|---|
| Auth | Always import from `shared/shared/middlewares/auth.py` — never re-implement token verification |
| Inter-service calls | Always use OIDC service account tokens |
| Firestore | Use the service's local `utils/firestore.py` wrapper — never instantiate `Client()` directly in routes or services |
| Error handling | Use `shared/shared/middlewares/error_handler.py` — return `{ "error": "...", "detail": "..." }` |
| Config | All config via Pydantic Settings in `app/config.py` — never hardcode GCP project IDs, URLs, or keys |
| Pub/Sub | Publish an event when state changes — downstream services subscribe |
| Audit logging | Every PHI access and case state change must be logged. PHI = any field in `leads` or `cases` documents |
| File uploads | All file operations via `storage-gateway` — no direct GCS calls from other services |
| Route handlers | Routes are thin — business logic belongs in `services/`, not route handlers |
| Firestore indexes | New Firestore collections must update `firestore/firestore.indexes.json` |
| API contract | New endpoints must be added to `openapi.yaml` before implementation |

---

## ANTI-PATTERNS

Never do any of the following:

- Business logic in route handlers
- Direct GCS calls from any service other than `storage-gateway`
- Hardcoded Cloud Run service URLs
- Skipping the shared auth middleware
- Using `requests` for inter-service calls (use `google.auth.transport.requests` with OIDC)
- Secrets in code or committed `.env` files
- Tests that hit real Firestore (use the emulator or mock the client)
- Adding Firestore collections without updating the index file
- Adding endpoints without updating `openapi.yaml`

---

## API CONTRACT

| Spec file | Scope |
|---|---|
| `openapi.yaml` (repo root) | Root API Gateway spec — all services |
| `services/lead-intake/openapi.yaml` | Lead intake service spec |

**All new endpoints must be added to the relevant spec before any implementation begins.**
