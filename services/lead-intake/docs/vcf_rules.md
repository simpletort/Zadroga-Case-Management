# VCF Screening Rules — Reference Documentation

**Version:** 1.0
**Reference:** James Zadroga 9/11 Health and Compensation Act of 2010 (Pub. L. 111-347)
**VCF Eligibility Window:** September 11, 2001 – May 30, 2011

---

## Overview

The September 11th Victim Compensation Fund (VCF) compensates individuals who were
physically present at a 9/11 crash site or in the NYC exposure zone, and who suffered
a physical harm or death as a result of the September 11, 2001 attacks or the debris
removal effort.

Claims must be filed by **October 1, 2090** (deadline extended by the Never Forget the Heroes Act).

---

## Rule R01 — Exposure Site Verification

**Type:** Hard Fail
**Description:** The claimant must have been physically present at a recognized 9/11 exposure site.

### Recognized VCF-Eligible Sites

| Site | Notes |
|------|-------|
| World Trade Center (WTC) / Ground Zero | Primary site — Manhattan, New York |
| Lower Manhattan | Below Canal Street, including Financial District |
| Pentagon | Arlington, Virginia |
| Shanksville, Pennsylvania | Flight 93 crash site |
| Fresh Kills Landfill | Staten Island — debris removal site |
| Brooklyn, Queens, Bronx, New Jersey | Downwind/debris cloud dispersal zones |
| Staten Island | Adjacent to Fresh Kills |

**Screener behavior:** Substring match against known site keywords. Unrecognized locations → INELIGIBLE_SITE.

---

## Rule R02 — Exposure Date Window

**Type:** Hard Fail
**Window:** 2001-09-11 through 2011-05-30 (inclusive)
**Description:** The claimant's exposure period must overlap the VCF eligibility window.

### Overlap Logic
```
Overlap = (exposure_start ≤ 2011-05-30) AND (exposure_end ≥ 2001-09-11)
```

### Date Boundary Cases

| Scenario | Result |
|----------|--------|
| Exposure exactly on 2001-09-11 | PASS (boundary inclusive) |
| Exposure exactly on 2011-05-30 | PASS (boundary inclusive) |
| Exposure ends on 2001-09-10 | FAIL (one day before window) |
| Exposure starts on 2011-05-31 | FAIL (one day after window) |
| Exposure spans the entire window | PASS |
| Exposure entirely after 2011 | FAIL |
| Missing dates | FAIL (MISSING_DATES) |

---

## Rule R03 — WTC Health Program Enrollment

**Type:** Soft Flag (non-blocking)
**Description:** Enrollment in the WTC Health Program is strong corroborating evidence
of eligibility but is not required to file a VCF claim.

| Status | Result |
|--------|--------|
| `enrolled` | PASS — strong positive signal |
| `applied` | PASS — enrollment in progress |
| `not_applied` | SOFT FLAG — follow up to encourage enrollment |
| `unknown` | SOFT FLAG — gather more information |

---

## Rule R04 — Prior Attorney Flag

**Type:** Soft Flag (non-blocking)
**Description:** Prior legal representation may indicate a previously denied or settled VCF claim.
Not disqualifying but requires manual review.

---

## Rule R05 — Data Completeness

**Type:** Hard Fail
**Required fields:** `firstName`, `lastName`, `email`, `phone`, `exposureLocation`

Missing any required field → INCOMPLETE (hard fail).

---

## Rule R06 — Medical Conditions (VCF-Covered Categories)

**Type:** Soft Flag (non-blocking)
**Reference:** 42 U.S.C. § 300mm-22 — WTC Health Program certified conditions

### Aerodigestive Disorders
- Rhinosinusitis, Nasopharyngitis, Laryngitis, Pharyngitis
- Upper airway hyperreactivity, Reactive upper airways dysfunction syndrome (RUADS)
- WTC-exacerbated chronic rhinosinusitis
- Sleep apnea (obstructive, in first responders)
- Interstitial lung disease, Asthma, COPD

### Cancers (45 types covered)
Including but not limited to:
- Mesothelioma
- All lymphatic and hematopoietic cancers (lymphoma, leukemia, myeloma)
- Thyroid, prostate, breast, bladder, colon, rectal, esophageal cancers
- Skin cancer (melanoma and non-melanoma)
- Lung and bronchus cancer

### Mental Health Conditions
- Post-Traumatic Stress Disorder (PTSD)
- Major Depressive Disorder
- Panic Disorder
- Generalized Anxiety Disorder
- Adjustment Disorder

### Musculoskeletal Disorders
- Carpal Tunnel Syndrome
- Tendinopathy, Tendinitis

### Other Covered Conditions
- Gastroesophageal reflux disease (GERD)
- Sleep disorders
- Peripheral neuropathy

---

## Eligibility Determination Matrix

| Hard Fails | Soft Flags | Result | Score |
|-----------|-----------|--------|-------|
| 0 | 0 | **ELIGIBLE** | 95 |
| 0 | 1+ | **NEEDS_REVIEW** | 60 |
| 1+ | Any | **INELIGIBLE** | 0 |

---

## Status Transitions

```
New Lead → Screened → Qualified → Active
                    → Disqualified
                    → Needs Review → Qualified (after manual review)
                                   → Disqualified
```

---

## API Integration

### Lead Conditions Field

Marketing partners should pass the `conditions` field as a list of free-text
medical condition descriptions. The screener performs substring matching against
the covered conditions list.

**Example:**
```json
{
  "conditions": ["respiratory issues", "asthma", "PTSD"]
}
```

### VCF Eligibility Window (configurable)

The window dates are configurable via environment variables:
- `VCF_WINDOW_START` (default: `2001-09-11`)
- `VCF_WINDOW_END` (default: `2011-05-30`)

Do not change these without legal review.
