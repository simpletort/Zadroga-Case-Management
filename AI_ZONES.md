# AI_ZONES.md — SimpleTort AI Confidence Zones

> Zones are set by the Tech Lead and may only be changed via a documented decision. Do not reclassify a path without that record.

---

## Zone Definitions

| Zone | Who writes code | Reviewers | Additional gates |
|---|---|---|---|
| **GREEN** | AI writes full implementation | 1 reviewer | Comprehension Declaration required |
| **AMBER** | AI drafts; developer rewrites or edits meaningfully | 2 reviewers | Developer walks a senior through the logic. No AI-only explanations accepted in review. |
| **RED** | AI lists every decision; human confirms each before any code is generated | 2 reviewers | Security review. Architect sign-off. Decision confirmation trail must be attached to the PR. |

---

## Summary Table

| Path | Zone | Reason |
|---|---|---|
| `services/auth-rbac/` | 🔴 RED | Security boundary — auth breach affects entire platform |
| `services/auth-rbac/backend/firestore/firestore.rules` | 🔴 RED | Gates all database access |
| `shared/shared/middlewares/auth.py` | 🔴 RED | Token verification used by every service |
| `shared/shared/middlewares/signed_url_expiry.py` | 🔴 RED | Signed URL expiry — security-critical |
| `services/storage-gateway/app/utils/audit.py` | 🔴 RED | PHI audit trail — must be complete and accurate |
| `services/settlement-financial/services/calculator.py` | 🔴 RED | Financial calculations — errors cause client harm |
| `services/settlement-financial/services/fee_calculator.py` | 🔴 RED | Attorney fee logic — contractually sensitive |
| `cloud-functions/virus-scanner/` | 🔴 RED | Security boundary for all uploaded files |
| Any `config.py` handling secrets or credentials | 🔴 RED | Secret/credential handling |
| `services/case-development/app/services/` | 🟡 AMBER | Core case state machine, approval logic, escalation rules |
| `services/enrollment-workflow/services/` | 🟡 AMBER | VCF/WTC enrollment rules — program-specific legal logic |
| `services/lead-intake/api/services/vcf_screener.py` | 🟡 AMBER | Eligibility screening logic |
| `services/lead-intake/api/services/duplicate_detection.py` | 🟡 AMBER | Deduplication logic |
| `services/lead-intake/api/services/validation.py` | 🟡 AMBER | Lead validation rules |
| `services/lead-intake/api/services/case_service.py` | 🟡 AMBER | Case creation transaction, atomic case-ID allocation, and `process_lead_submission()` — the full dedup/screening/notification/pubsub/follow-up pipeline shared by `POST /leads` and bulk import. Same sensitivity tier as the AMBER files above it processes rows through. |
| `services/lead-intake/api/services/bulk_import_service.py` | 🟡 AMBER | Drives `case_service.process_lead_submission()` per row for bulk lead import; job status transitions and per-row idempotency logic. |
| `services/notification/services/` | 🟡 AMBER | Template rendering, opt-out enforcement |
| `services/workflow-orchestrator/services/workflow_engine.py` | 🟡 AMBER | Event routing and workflow triggering |
| `services/workflow-orchestrator/cloud_workflows/*.yaml` | 🟡 AMBER | Cloud Workflow definitions |
| `services/reporting-service/app/services/` | 🟡 AMBER | KPI aggregation and metric calculation |
| `services/task-management/app/services/task_service.py` | 🟡 AMBER | Task assignment and priority logic |
| `services/settlement-financial/services/` (excl. calculator.py, fee_calculator.py) | 🟡 AMBER | Lien tracking, expense tracking, PDF generation |
| `cloud-functions/case-assignment/assigner.py` | 🟡 AMBER | Auto-assignment algorithm |
| `cloud-functions/deadline-alerter/main.py` | 🟡 AMBER | Deadline alert triggering logic |
| `services/*/app/routes/` | 🟢 GREEN | Thin route handlers |
| `services/*/app/models/` | 🟢 GREEN | Pydantic models |
| `services/*/app/utils/firestore.py` | 🟢 GREEN | Firestore client wrappers |
| `services/*/app/utils/date_helpers.py` | 🟢 GREEN | Date utilities |
| `services/*/app/utils/auth.py` | 🟢 GREEN | Auth helpers (not the auth service itself) |
| `services/*/app/config.py` (non-secret) | 🟢 GREEN | Non-secret Pydantic Settings |
| `services/*/tests/` | 🟢 GREEN | All test files |
| `services/*/requirements.txt` | 🟢 GREEN | Dependency manifests |
| `services/*/Dockerfile` | 🟢 GREEN | Container definitions |
| `services/*/cloudbuild.yaml` | 🟢 GREEN | CI/CD config |
| `shared/shared/middlewares/logging.py` | 🟢 GREEN | Logging middleware |
| `shared/shared/middlewares/cors.py` | 🟢 GREEN | CORS middleware |
| `shared/shared/middlewares/error_handler.py` | 🟢 GREEN | Error handling middleware |
| `shared/shared/middlewares/file_validation.py` | 🟢 GREEN | File validation middleware |
| `firestore/firestore.indexes.json` | 🟢 GREEN | Index definitions |
| `scripts/` | 🟢 GREEN | Utility scripts |
| `infrastructure/` | 🟢 GREEN | Infrastructure config |
| `integrations/` | 🟢 GREEN | Integration scaffolding |
| Skeleton services | 🟢 GREEN | New scaffolding until the service becomes real |

---

## 🔴 RED Zone

**Process:** AI proposes approach and lists every decision. Human explicitly confirms each decision before any code is generated. Two reviewers. Security review. Architect sign-off. Decision confirmation trail must be attached to the PR.

### Paths

| Path | Reason |
|---|---|
| `services/auth-rbac/` | Firebase Auth, JWT claims, role assignment. Any mistake is a security breach affecting the entire platform. |
| `services/auth-rbac/backend/firestore/firestore.rules` | Gates all Firestore database access across every service. |
| `shared/shared/middlewares/auth.py` | Token verification imported and executed by every service on every request. |
| `shared/shared/middlewares/signed_url_expiry.py` | Controls signed URL expiry windows — a misconfiguration leaks file access. |
| `services/storage-gateway/app/utils/audit.py` | PHI audit trail. Must be complete, accurate, and tamper-evident. Gaps are a HIPAA liability. |
| `services/settlement-financial/services/calculator.py` | Financial calculations used in client-facing disbursements. Errors cause direct monetary harm. |
| `services/settlement-financial/services/fee_calculator.py` | Attorney fee logic. Contractually sensitive — outputs appear on client settlement statements. |
| `cloud-functions/virus-scanner/` | Security boundary for every file uploaded to the platform. Must catch all malware before storage. |
| Any `config.py` handling secrets or credentials | Misconfigured secret handling can expose keys, tokens, or service account credentials. |

### Red Zone Decision-Gate Process

Follow these steps in order. Do not skip or merge steps.

1. **Open a new session.** Do not reuse a session that already has implementation context — decisions must be made before code exists.
2. **Provide context.** Share `AI_CONTEXT.md` and the full user story or ticket.
3. **Instruct AI to list decisions only.** Explicitly tell the AI: *"List every decision required to implement this. Do not write any code yet."*
4. **Confirm each decision explicitly.** Review every item in the list. Respond with an explicit yes/no/alternative for each. No implicit approvals.
5. **Save the decision trail.** Paste the confirmed decision list into the PR description or a linked document before any code is written.
6. **AI generates code against confirmed decisions only.** If a new decision point surfaces during implementation, stop and repeat steps 3–5 for it.
7. **Attach the decision trail to the PR.** Both reviewers must verify that the implementation matches the confirmed decisions, not just that the code is correct.

---

## 🟡 AMBER Zone

**Process:** AI drafts the implementation. Developer rewrites or edits meaningfully — do not merge AI output verbatim. Two reviewers. Developer must walk a senior through the logic in review. No AI-only explanations accepted — the developer must be able to explain every line independently.

### Paths

| Path | Reason |
|---|---|
| `services/case-development/app/services/` | Core case state machine, approval logic, escalation rules. Incorrect transitions corrupt case history. |
| `services/case-development/app/services/attorney_review_service.py` | Multi-tier approval chain. Logic errors block cases or let unreviewed cases through. |
| `services/case-development/app/services/escalation_service.py` | Escalation routing rules. Missed escalations delay or bypass senior review. |
| `services/case-development/app/services/rejection_service.py` | Rejection and reinstatement logic. Errors can permanently close valid cases or reopen closed ones. |
| `services/enrollment-workflow/services/` | VCF/WTC enrollment rules. Program-specific legal logic — incorrect enrollment can forfeit compensation. |
| `services/enrollment-workflow/services/deadline_service.py` | Deadline calculations. Missed hard deadlines kill cases. |
| `services/lead-intake/api/services/vcf_screener.py` | Eligibility screening logic. False negatives disqualify valid clients. |
| `services/lead-intake/api/services/duplicate_detection.py` | Deduplication logic. False positives silently drop valid leads; false negatives create duplicate cases. |
| `services/lead-intake/api/services/validation.py` | Lead validation rules. Determines which leads enter the pipeline. |
| `services/lead-intake/api/services/case_service.py` | Case creation transaction and atomic case-ID allocation; hosts `process_lead_submission()`, the shared dedup/screening/notification/pubsub/follow-up pipeline used by both single-lead and bulk-import creation. Errors here corrupt case identity or duplicate/skip lead creation at scale. |
| `services/lead-intake/api/services/bulk_import_service.py` | Drives `process_lead_submission()` per row for bulk lead import from Excel; owns job status transitions and per-row idempotency. A logic error can misfire hundreds of case creations from one bad column mapping. |
| `services/notification/services/` | Template rendering and opt-out enforcement. Violations of opt-out are legally and regulatorily significant. |
| `services/workflow-orchestrator/services/workflow_engine.py` | Event routing and workflow triggering. Incorrect routing silently breaks cross-service state transitions. |
| `services/workflow-orchestrator/cloud_workflows/*.yaml` | Cloud Workflow definitions. Errors stall automated case progression across multiple services. |
| `services/reporting-service/app/services/` | KPI aggregation and metric calculation. Inaccurate metrics mislead firm leadership decisions. |
| `services/task-management/app/services/task_service.py` | Task assignment and priority logic. Errors leave work unassigned or misrouted. |
| `services/settlement-financial/services/` (excl. `calculator.py`, `fee_calculator.py`) | Lien tracking, expense tracking, PDF generation. Errors affect settlement accuracy and client documents. |
| `cloud-functions/case-assignment/assigner.py` | Auto-assignment algorithm. Unbalanced assignment creates paralegal overload or idle staff. |
| `cloud-functions/deadline-alerter/main.py` | Deadline alert triggering logic. Silent failures mean attorneys miss filing windows. |

---

## 🟢 GREEN Zone

**Process:** AI writes the full implementation. Developer reviews for correctness. One reviewer. Developer must sign a Comprehension Declaration confirming they understand what was generated.

### Paths

| Path | Notes |
|---|---|
| `services/*/app/routes/` | FastAPI route handlers — must remain thin, delegate to `services/` |
| `services/*/app/models/` | Pydantic request/response models |
| `services/*/app/utils/firestore.py` | Firestore client wrappers |
| `services/*/app/utils/date_helpers.py` | Date utilities |
| `services/*/app/utils/auth.py` | Auth helpers — not the auth-rbac service itself |
| `services/*/app/config.py` | Non-secret Pydantic Settings only — see RED zone if handling credentials |
| `services/*/tests/` | All test files |
| `services/*/requirements.txt` | Dependency manifests |
| `services/*/Dockerfile` | Container definitions |
| `services/*/cloudbuild.yaml` | CI/CD config |
| `shared/shared/middlewares/logging.py` | Logging middleware |
| `shared/shared/middlewares/cors.py` | CORS middleware |
| `shared/shared/middlewares/error_handler.py` | Error handling middleware |
| `shared/shared/middlewares/file_validation.py` | File validation middleware |
| `firestore/firestore.indexes.json` | Index definitions — still required for new collections |
| `scripts/` | Utility scripts |
| `infrastructure/` | Infrastructure config |
| `integrations/` | Integration scaffolding |
| Skeleton services (`evidence-management`, `hipaa-compliance`, `vcf-claim-tracking`, `revenue-analytics`, `reporting-kpi`, `counsel-substitution`, `external-sync`) | GREEN until the service becomes real — at that point zone must be reassessed and documented |

---

## Zone Violation Protocol

If code is merged to a RED or AMBER path without following the required process:

1. **Notify the Tech Lead immediately.**
2. **Trigger a security review** before the next deploy to any environment beyond dev.
3. **Record the violation in the next retrospective** — include what was skipped and why.
4. If the violation involves a RED path, treat it as a potential security incident until the review clears it.
