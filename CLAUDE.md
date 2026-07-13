# CLAUDE.md

## Start of every session

- Read [AI_CONTEXT.md](AI_CONTEXT.md) before writing any code. Every suggestion must be consistent with it.
- Check [AI_ZONES.md](AI_ZONES.md) before implementing anything.
  - **Red zone modules** require the decision-gate process: list all decisions, get explicit confirmation for each, then generate code. Do not skip this.

## API contract (spec-first)

- Root spec: [openapi.yaml](openapi.yaml)
- Lead intake spec: [services/lead-intake/openapi.yaml](services/lead-intake/openapi.yaml)
- Match these contracts exactly. Never add endpoints, fields, or status codes not in the spec without flagging it first.

## Hard rules (apply on every task)

- Always use the shared middleware stack from `shared/shared/middlewares/`
- Never hardcode GCP project IDs, Cloud Run URLs, or service account keys
- All inter-service calls use OIDC auth
- Python services use FastAPI — do not introduce any other framework
- Routes are thin — business logic belongs in `app/services/`, not route handlers
- All file operations go through `storage-gateway` — never call GCS directly from another service
- Every PHI access and case state change must be audit logged
- New Firestore collections require an update to `firestore/firestore.indexes.json`
- New endpoints require an update to `openapi.yaml` before implementation

## Skeleton services — never call these

`evidence-management`, `hipaa-compliance`, `vcf-claim-tracking`, `revenue-analytics`, `reporting-kpi`, `counsel-substitution`, `external-sync`

These are scaffolded but empty. Do not reference or invoke them.
