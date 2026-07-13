# Reporting Service

KPI and analytics reporting service for the SimpleTort / Zadroga Act case management platform.

## Overview

- **Framework**: FastAPI 0.110.x + uvicorn
- **Runtime**: Cloud Run (serverless, port 8080)
- **Database**: Cloud Firestore (read-only consumer)
- **Auth**: Firebase ID Token — `Authorization: Bearer <token>`
- **Cache**: In-memory TTL cache, 300s per key
- **CORS allowed origins**: `https://lookerstudio.google.com`, `https://staff.simpletort.com`

All endpoints are read-only (`GET`). There are no write operations in this service.

---

## Role Requirements

| Role | Level | Report access |
|---|---|---|
| admin_staff | 1 | none |
| paralegal | 2 | none |
| junior_partner | 3 | all except staff-performance |
| senior_partner | 4 | all endpoints |
| system_admin | 5 | all endpoints |

---

## Endpoints

### GET /health

Public. No auth required.

**Response:**
```json
{ "status": "ok", "service": "reporting-service" }
```

---

### GET /reports/dashboard

Comprehensive KPI metrics for a given time window. Computes new leads, active cases, settled cases, qualification rate, avg medical score, and avg lead-to-paralegal assignment time.

**Min role:** `junior_partner`

**Query params:**

| Param | Type | Default | Range |
|---|---|---|---|
| `period_days` | int | 30 | 7–365 |

**Response:**
```json
{
  "generated_at": "2026-05-22T10:00:00Z",
  "period_days": 30,
  "metrics": [
    {
      "label": "New Leads",
      "value": 42.0,
      "unit": "cases",
      "trend": 5.2,
      "trend_direction": "up"
    }
  ]
}
```

`trend_direction` is one of `"up"`, `"down"`, or `"neutral"`. `trend` and `trend_direction` are nullable.

Cache key: `kpi_dashboard_{period_days}`

---

### GET /reports/cases-by-status

Count of cases in each status, plus average days spent in that status.

**Min role:** `junior_partner`

No query params.

**Response:**
```json
{
  "generated_at": "2026-05-22T10:00:00Z",
  "total_active": 87,
  "items": [
    {
      "status": "Pending Paralegal Review",
      "count": 14,
      "avg_days_in_status": 8.3
    }
  ]
}
```

`total_active` = sum of counts for: New Lead, Pending Client Information, Pending Paralegal Review, Pending Attorney Review, Ready for Filing, VCF - Submitted, Awarded, On Hold.

`avg_days_in_status` is nullable.

Cache key: `cases_by_status`

---

### GET /reports/funnel

Case conversion funnel showing counts and conversion rates across all 8 pipeline stages.

**Min role:** `junior_partner`

No query params.

**Response:**
```json
{
  "generated_at": "2026-05-22T10:00:00Z",
  "stages": [
    { "stage": "New Lead",                   "count": 200, "conversion_rate": null, "avg_days_to_next": 3.2  },
    { "stage": "Pending Client Information", "count": 170, "conversion_rate": 85.0, "avg_days_to_next": 5.1  },
    { "stage": "Pending Paralegal Review",   "count": 140, "conversion_rate": 82.4, "avg_days_to_next": 7.8  },
    { "stage": "Pending Attorney Review",    "count": 100, "conversion_rate": 71.4, "avg_days_to_next": 4.0  },
    { "stage": "Ready for Filing",           "count": 80,  "conversion_rate": 80.0, "avg_days_to_next": 12.0 },
    { "stage": "VCF - Submitted",            "count": 60,  "conversion_rate": 75.0, "avg_days_to_next": 90.0 },
    { "stage": "Awarded",                    "count": 40,  "conversion_rate": 66.7, "avg_days_to_next": 30.0 },
    { "stage": "Settled",                    "count": 30,  "conversion_rate": 75.0, "avg_days_to_next": null }
  ]
}
```

`conversion_rate` = (stage_count / previous_stage_count) × 100, rounded to 1 decimal. Null for the first stage. `avg_days_to_next` is nullable (null for the last stage).

Cache key: `funnel`

---

### GET /reports/bottlenecks

Cases stuck in a status longer than a configurable threshold, grouped by status with paralegal assignment info.

**Min role:** `junior_partner`

**Query params:**

| Param | Type | Default | Range |
|---|---|---|---|
| `threshold_days` | int | 30 | 7–180 |

**Response:**
```json
{
  "generated_at": "2026-05-22T10:00:00Z",
  "threshold_days": 30,
  "bottlenecks": [
    {
      "status": "Pending Attorney Review",
      "case_count": 12,
      "avg_days_stuck": 45.2,
      "oldest_case_days": 91.0,
      "assigned_paralegal_ids": ["uid_abc", "uid_def"]
    }
  ]
}
```

Only statuses where at least one case has been stuck longer than `threshold_days` appear in the response.

Cache key: `bottlenecks_{threshold_days}`

---

### GET /reports/lead-conversion

Lead-to-active conversion analysis for a given time window. Reports qualification rate, conversion rate, and average time from lead creation to paralegal assignment.

**Min role:** `junior_partner`

**Query params:**

| Param | Type | Default | Range |
|---|---|---|---|
| `period_days` | int | 30 | 7–365 |

**Response:**
```json
{
  "generated_at": "2026-05-22T10:00:00Z",
  "period_days": 30,
  "total_leads": 55,
  "qualified": 48,
  "converted_to_active": 40,
  "qualification_rate": 87.3,
  "conversion_rate": 72.7,
  "avg_days_lead_to_active": 4.8,
  "disqualified": 7
}
```

- `disqualified` = cases in "Does Not Qualify" or "Withdrawn"
- `qualified` = `total_leads` − `disqualified`
- `converted_to_active` = cases that progressed past New Lead and are not disqualified
- `avg_days_lead_to_active` = avg(`paralegalAssignedAt` − `createdAt`), nullable

Cache key: `lead_conversion_{period_days}`

---

### GET /reports/staff-performance

Per-staff performance metrics: active caseload, completions, and overdue task count.

**Min role:** `senior_partner`

**Query params:**

| Param | Type | Default | Range |
|---|---|---|---|
| `period_days` | int | 30 | 7–90 |

**Response:**
```json
{
  "generated_at": "2026-05-22T10:00:00Z",
  "period_days": 30,
  "staff": [
    {
      "user_id": "uid_xyz",
      "display_name": "Jane Smith",
      "role": "paralegal",
      "active_cases": 18,
      "cases_completed_period": 4,
      "avg_days_to_review": 6.2,
      "overdue_tasks": 3
    }
  ]
}
```

- `active_cases` — cases in active statuses where `assignedParalegal` or `assignedAttorney` matches the user
- `cases_completed_period` — cases settled within the period assigned to that user
- `avg_days_to_review` — nullable
- `overdue_tasks` — open tasks from the `tasks` subcollection group where `dueAt < now` for that user

Cache key: `staff_performance_{period_days}`

---

## Firestore Collections

| Collection | Used by |
|---|---|
| `cases` | All report endpoints |
| `users` | staff-performance (display name, role) |
| `tasks` (subcollection group) | staff-performance (overdue task count) |
| `analyticsCache` | KPI dashboard (persistent cache fallback) |

### Case fields consumed by this service

| Field | Type | Description |
|---|---|---|
| `status` | string | Current case status |
| `createdAt` | timestamp | Lead arrival time |
| `lastStatusChangedAt` | timestamp | When status last changed |
| `paralegalAssignedAt` | timestamp | When paralegal was first assigned |
| `settledAt` | timestamp | Settlement date |
| `assignedParalegal` | string (uid) | Assigned paralegal user ID |
| `assignedAttorney` | string (uid) | Assigned attorney user ID |
| `qualificationScore` | float | Medical qualification score |
