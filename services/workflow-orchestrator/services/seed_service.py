"""
Seed service — migrates all 7 hardcoded workflow definitions into Firestore.

Idempotent: any workflow document that already exists is skipped.
This ensures that admin edits made after the first seed are never overwritten
by a re-deployment or a subsequent seed call.

Called by:
  - POST /api/v1/admin/workflows/seed
  - main.py lifespan() when AUTO_SEED_DEFINITIONS=true (development only)
"""

from __future__ import annotations

import structlog
from datetime import datetime
from typing import Any

from models.workflow import (
    WorkflowDefinitionConfig,
    TaskTemplateConfig,
    AutomatedStepConfig,
    ParameterDefinition,
    EventTriggerConfig,
)
from services.firestore_service import FirestoreService

log = structlog.get_logger()


async def seed_workflow_definitions(db: FirestoreService) -> dict[str, int]:
    """
    Write-if-not-exists for all 7 workflow definitions.
    Returns {"seeded": N, "skipped": M}.
    """
    seeded = 0
    skipped = 0

    for workflow_id, seed_data in _build_seed_data().items():
        existing = await db.get_workflow_definition(workflow_id)
        if existing:
            log.debug("seed_skipped_existing", workflow_id=workflow_id)
            skipped += 1
            continue

        defn = WorkflowDefinitionConfig(**seed_data)
        await db.save_workflow_definition(defn)
        log.info("seed_workflow_definition", workflow_id=workflow_id)
        seeded += 1

    log.info("seed_complete", seeded=seeded, skipped=skipped)
    return {"seeded": seeded, "skipped": skipped}


def _build_seed_data() -> dict[str, dict[str, Any]]:
    """
    Constructs seed data for all 7 workflows from the existing hardcoded sources:
      - WORKFLOW_REGISTRY   → id, display_name, description, gcp_workflow_id, required_arguments
      - WORKFLOW_INITIAL_TASKS → task_templates (hours ÷ 24 = due_offset_days)
      - event_handler if/elif → event_triggers
      - Known threshold/template values → automated_steps
    """
    return {
        # ------------------------------------------------------------------
        "lead-qualification": {
            "id": "lead-qualification",
            "display_name": "Lead Qualification",
            "description": (
                "Screens a new lead against VCF eligibility criteria "
                "and initiates client onboarding."
            ),
            "gcp_workflow_id": "lead-qualification",
            "required_arguments": ["lead_id"],
            "estimated_duration_hours": 0.5,
            "is_active": True,
            "task_templates": [
                TaskTemplateConfig(
                    step_id="complete_questionnaire",
                    display_name="Lead Qualification Questionnaire",
                    description="Paralegal completes eligibility intake before any onboarding",
                    title="Complete lead qualification questionnaire",
                    priority="high",
                    due_offset_days=1,  # 24h ÷ 24
                    assigned_to_role="paralegal",
                    task_type="complete_questionnaire",
                    order=1,
                ),
            ],
            "automated_steps": [
                AutomatedStepConfig(
                    step_id="check_vcf_eligibility",
                    display_name="VCF Eligibility Check",
                    description="Validates that the lead meets minimum VCF/WTC eligibility criteria",
                    is_condition=True,
                    parameter_schema=[
                        ParameterDefinition(
                            name="min_exposure_years",
                            label="Minimum Exposure Duration (years)",
                            description=(
                                "Minimum number of years of WTC site exposure required "
                                "to pass the initial eligibility screen"
                            ),
                            type="number",
                            default_value=0,
                            min_value=0,
                            max_value=10,
                        ),
                        ParameterDefinition(
                            name="accepted_injury_types",
                            label="Accepted Injury Types",
                            description=(
                                "Comma-separated list of injury types accepted for VCF eligibility"
                            ),
                            type="string",
                            default_value="respiratory,cancer,mental_health",
                        ),
                    ],
                    parameters={
                        "min_exposure_years": 0,
                        "accepted_injury_types": "respiratory,cancer,mental_health",
                    },
                ),
            ],
            "event_triggers": [],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "created_by": "system",
        },

        # ------------------------------------------------------------------
        "client-onboarding": {
            "id": "client-onboarding",
            "display_name": "Client Onboarding",
            "description": (
                "Creates client portal account, sends retainer for e-signature, "
                "and builds document checklist."
            ),
            "gcp_workflow_id": "client-onboarding",
            "required_arguments": ["case_id", "client_email"],
            "estimated_duration_hours": 24.0,
            "is_active": True,
            "task_templates": [
                TaskTemplateConfig(
                    step_id="sign_retainer",
                    display_name="Sign Retainer Agreement",
                    description="Client must sign the retainer agreement before case can proceed",
                    title="Sign retainer agreement (DocuSign)",
                    priority="critical",
                    due_offset_days=2,  # 48h ÷ 24
                    assigned_to_role="client",
                    task_type="sign_retainer",
                    order=1,
                ),
                TaskTemplateConfig(
                    step_id="upload_documents",
                    display_name="Upload Identification Documents",
                    description="Client uploads required ID documents for medical review and VCF processing",
                    title="Upload required identification documents",
                    priority="high",
                    due_offset_days=3,  # 72h ÷ 24
                    assigned_to_role="client",
                    task_type="upload_documents",
                    order=2,
                ),
            ],
            "automated_steps": [
                AutomatedStepConfig(
                    step_id="send_retainer",
                    display_name="Send Retainer via DocuSign",
                    description="Sends the retainer agreement to the client via DocuSign for e-signature",
                    is_condition=False,
                    parameter_schema=[
                        ParameterDefinition(
                            name="docusign_template_id",
                            label="DocuSign Template ID",
                            description=(
                                "The DocuSign template ID for the retainer agreement. "
                                "Update this when the retainer template changes."
                            ),
                            type="string",
                            default_value="retainer_agreement",
                        ),
                        ParameterDefinition(
                            name="retainer_expiry_days",
                            label="Retainer Expiry (days)",
                            description=(
                                "Number of days the DocuSign envelope remains open "
                                "before it expires and must be resent"
                            ),
                            type="number",
                            default_value=7,
                            min_value=1,
                            max_value=30,
                        ),
                    ],
                    parameters={
                        "docusign_template_id": "retainer_agreement",
                        "retainer_expiry_days": 7,
                    },
                ),
            ],
            "event_triggers": [
                EventTriggerConfig(
                    event_type="lead.qualified",
                    arguments_mapping={
                        "case_id": "data.case_id",
                        "client_email": "data.client_email",
                    },
                    description="Auto-triggered when a lead passes the qualification screen",
                ),
            ],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "created_by": "system",
        },

        # ------------------------------------------------------------------
        "medical-processing": {
            "id": "medical-processing",
            "display_name": "Medical Document Processing",
            "description": (
                "Runs Document AI OCR + MedLM summarisation and qualification scoring."
            ),
            "gcp_workflow_id": "medical-processing",
            "required_arguments": ["case_id", "document_ids"],
            "estimated_duration_hours": 1.0,
            "is_active": True,
            "task_templates": [
                TaskTemplateConfig(
                    step_id="review_medical_summary",
                    display_name="Review AI Medical Summary",
                    description="Paralegal QA-checks the AI summary before attorney sign-off",
                    title="Review AI-generated medical summary",
                    priority="high",
                    due_offset_days=1,  # 24h ÷ 24
                    assigned_to_role="paralegal",
                    task_type="review_medical_summary",
                    order=1,
                ),
                TaskTemplateConfig(
                    step_id="verify_qualification_score",
                    display_name="Verify AI Qualification Score",
                    description="Attorney makes final eligibility decision based on AI score",
                    title="Verify AI qualification score",
                    priority="high",
                    due_offset_days=2,  # 48h ÷ 24
                    assigned_to_role="attorney",
                    task_type="verify_qualification_score",
                    order=2,
                ),
            ],
            "automated_steps": [
                AutomatedStepConfig(
                    step_id="check_qualification_score",
                    display_name="Qualification Score Threshold Check",
                    description=(
                        "Cases scoring at or above the threshold proceed to attorney review. "
                        "Cases below are flagged for manual review."
                    ),
                    is_condition=True,
                    parameter_schema=[
                        ParameterDefinition(
                            name="qualification_threshold",
                            label="Qualification Score Threshold",
                            description=(
                                "Minimum AI qualification score (0–100) required for a case "
                                "to automatically advance to attorney review. "
                                "Cases below this score are flagged for manual review."
                            ),
                            type="number",
                            default_value=65,
                            min_value=0,
                            max_value=100,
                        ),
                    ],
                    parameters={
                        "qualification_threshold": 65,
                    },
                ),
            ],
            "event_triggers": [
                EventTriggerConfig(
                    event_type="documents.uploaded",
                    arguments_mapping={
                        "case_id": "data.case_id",
                        "document_ids": "data.document_ids",
                    },
                    description="Auto-triggered when a client uploads documents",
                ),
            ],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "created_by": "system",
        },

        # ------------------------------------------------------------------
        "vcf-enrollment": {
            "id": "vcf-enrollment",
            "display_name": "WTC / VCF Enrollment",
            "description": (
                "Tracks WTC Health Program and VCF registration status, "
                "schedules deadline alerts."
            ),
            "gcp_workflow_id": "vcf-enrollment",
            "required_arguments": ["case_id"],
            "estimated_duration_hours": None,
            "is_active": True,
            "task_templates": [
                TaskTemplateConfig(
                    step_id="confirm_wtc_enrollment",
                    display_name="Confirm WTC Health Program Enrollment",
                    description="Must confirm WTC coverage is active before VCF submission",
                    title="Confirm WTC Health Program enrollment",
                    priority="critical",
                    due_offset_days=3,  # 72h ÷ 24
                    assigned_to_role="paralegal",
                    task_type="confirm_wtc_enrollment",
                    order=1,
                ),
                TaskTemplateConfig(
                    step_id="submit_vcf_registration",
                    display_name="Submit VCF Registration",
                    description="VCF registration is time-sensitive; must not miss the deadline",
                    title="Submit VCF registration",
                    priority="critical",
                    due_offset_days=7,  # 168h ÷ 24
                    assigned_to_role="paralegal",
                    task_type="submit_vcf_registration",
                    order=2,
                ),
                TaskTemplateConfig(
                    step_id="check_enrollment_deadline",
                    display_name="Check Enrollment Deadline Alerts",
                    description="Trigger deadline alert system to send reminders at key milestones",
                    title="Check and set enrollment deadline alerts",
                    priority="high",
                    due_offset_days=1,  # 24h ÷ 24
                    assigned_to_role="paralegal",
                    task_type="check_enrollment_deadline",
                    order=3,
                ),
            ],
            "automated_steps": [
                AutomatedStepConfig(
                    step_id="schedule_deadline_alerts",
                    display_name="Deadline Alert Schedule",
                    description=(
                        "Configures when automated deadline reminder tasks are created "
                        "before the VCF enrollment deadline"
                    ),
                    is_condition=False,
                    parameter_schema=[
                        ParameterDefinition(
                            name="alert_days_before",
                            label="Alert Days Before Deadline",
                            description=(
                                "Comma-separated list of days before the deadline when "
                                "reminder tasks are automatically created (e.g. 90,60,30,14,7)"
                            ),
                            type="string",
                            default_value="90,60,30,14,7",
                        ),
                    ],
                    parameters={
                        "alert_days_before": "90,60,30,14,7",
                    },
                ),
            ],
            "event_triggers": [],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "created_by": "system",
        },

        # ------------------------------------------------------------------
        "substitution-of-counsel": {
            "id": "substitution-of-counsel",
            "display_name": "Substitution of Counsel",
            "description": (
                "Generates substitution form, collects e-signature via DocuSign, "
                "requests prior attorney files."
            ),
            "gcp_workflow_id": "substitution-of-counsel",
            "required_arguments": ["case_id", "prior_attorney_id"],
            "estimated_duration_hours": 72.0,
            "is_active": True,
            "task_templates": [
                TaskTemplateConfig(
                    step_id="generate_substitution_form",
                    display_name="Generate Substitution of Counsel Form",
                    description="Generate the formal court substitution form before requesting signatures",
                    title="Generate substitution of counsel form",
                    priority="high",
                    due_offset_days=1,  # 24h ÷ 24
                    assigned_to_role="paralegal",
                    task_type="generate_substitution_form",
                    order=1,
                ),
                TaskTemplateConfig(
                    step_id="request_prior_files",
                    display_name="Request Files from Prior Attorney",
                    description="Request prior case files; may take time to retrieve",
                    title="Request case files from prior attorney",
                    priority="high",
                    due_offset_days=3,  # 72h ÷ 24
                    assigned_to_role="paralegal",
                    task_type="request_prior_files",
                    order=2,
                ),
                TaskTemplateConfig(
                    step_id="obtain_signature",
                    display_name="Obtain Client Signature",
                    description="Client signature is required for court filing",
                    title="Obtain client signature via DocuSign",
                    priority="critical",
                    due_offset_days=2,  # 48h ÷ 24
                    assigned_to_role="client",
                    task_type="obtain_signature",
                    order=3,
                ),
            ],
            "automated_steps": [
                AutomatedStepConfig(
                    step_id="send_substitution_form",
                    display_name="Send Substitution Form via DocuSign",
                    description="Sends the substitution of counsel form to all parties for signature",
                    is_condition=False,
                    parameter_schema=[
                        ParameterDefinition(
                            name="docusign_template_id",
                            label="DocuSign Template ID",
                            description=(
                                "The DocuSign template ID for the substitution of counsel form. "
                                "Update when the form template changes."
                            ),
                            type="string",
                            default_value="substitution_of_counsel",
                        ),
                        ParameterDefinition(
                            name="signature_deadline_days",
                            label="Signature Deadline (days)",
                            description=(
                                "Number of days all parties have to sign the substitution form "
                                "before a follow-up reminder is sent"
                            ),
                            type="number",
                            default_value=14,
                            min_value=1,
                            max_value=60,
                        ),
                    ],
                    parameters={
                        "docusign_template_id": "substitution_of_counsel",
                        "signature_deadline_days": 14,
                    },
                ),
            ],
            "event_triggers": [],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "created_by": "system",
        },

        # ------------------------------------------------------------------
        "claim-submission": {
            "id": "claim-submission",
            "display_name": "VCF Claim Submission",
            "description": (
                "Assembles claim package, submits to VCF, "
                "and begins post-filing status tracking."
            ),
            "gcp_workflow_id": "claim-submission",
            "required_arguments": ["case_id"],
            "estimated_duration_hours": 2.0,
            "is_active": True,
            "task_templates": [
                TaskTemplateConfig(
                    step_id="review_case_file",
                    display_name="Final Claim Package Review",
                    description="Attorney final QA: is the package complete and compliant?",
                    title="Final review of claim package",
                    priority="critical",
                    due_offset_days=1,  # 24h ÷ 24
                    assigned_to_role="attorney",
                    task_type="review_case_file",
                    order=1,
                ),
                TaskTemplateConfig(
                    step_id="submit_vcf_claim",
                    display_name="Submit VCF Claim",
                    description="Paralegal submits the claim after attorney approval",
                    title="Submit VCF claim",
                    priority="critical",
                    due_offset_days=2,  # 48h ÷ 24
                    assigned_to_role="paralegal",
                    task_type="submit_vcf_claim",
                    order=2,
                ),
            ],
            "automated_steps": [
                AutomatedStepConfig(
                    step_id="check_document_completeness",
                    display_name="Document Completeness Check",
                    description=(
                        "Verifies that all required document categories are present "
                        "before assembling the claim package"
                    ),
                    is_condition=True,
                    parameter_schema=[
                        ParameterDefinition(
                            name="min_document_count",
                            label="Minimum Document Count",
                            description=(
                                "Minimum number of uploaded documents required before "
                                "the claim package can be assembled and submitted"
                            ),
                            type="number",
                            default_value=3,
                            min_value=1,
                            max_value=50,
                        ),
                        ParameterDefinition(
                            name="required_categories",
                            label="Required Document Categories",
                            description=(
                                "Comma-separated list of document categories that must be present. "
                                "e.g. medical_record,proof_of_presence,id_document"
                            ),
                            type="string",
                            default_value="medical_record,proof_of_presence,id_document",
                        ),
                    ],
                    parameters={
                        "min_document_count": 3,
                        "required_categories": "medical_record,proof_of_presence,id_document",
                    },
                ),
            ],
            "event_triggers": [],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "created_by": "system",
        },

        # ------------------------------------------------------------------
        "settlement": {
            "id": "settlement",
            "display_name": "Settlement & Disbursement",
            "description": (
                "Calculates settlement, generates settlement statement, "
                "obtains signatures, disburses funds via QuickBooks."
            ),
            "gcp_workflow_id": "settlement",
            "required_arguments": ["case_id", "award_amount"],
            "estimated_duration_hours": 48.0,
            "is_active": True,
            "task_templates": [
                TaskTemplateConfig(
                    step_id="prepare_settlement_statement",
                    display_name="Prepare Settlement Statement",
                    description="Paralegal calculates settlement amounts and drafts the statement",
                    title="Prepare settlement statement",
                    priority="high",
                    due_offset_days=2,  # 48h ÷ 24
                    assigned_to_role="paralegal",
                    task_type="prepare_settlement_statement",
                    order=1,
                ),
                TaskTemplateConfig(
                    step_id="attorney_approval",
                    display_name="Attorney Approval of Settlement Terms",
                    description="Attorney must approve terms before client signature (fiduciary duty)",
                    title="Attorney approval of settlement terms",
                    priority="critical",
                    due_offset_days=3,  # 72h ÷ 24
                    assigned_to_role="attorney",
                    task_type="attorney_approval",
                    order=2,
                ),
                TaskTemplateConfig(
                    step_id="obtain_client_signature",
                    display_name="Client Signature on Settlement Agreement",
                    description="Client signs after attorney sign-off; required for valid settlement",
                    title="Client signature on settlement agreement",
                    priority="critical",
                    due_offset_days=4,  # 96h ÷ 24
                    assigned_to_role="client",
                    task_type="obtain_signature",
                    order=3,
                ),
                TaskTemplateConfig(
                    step_id="disburse_funds",
                    display_name="Disburse Funds via QuickBooks",
                    description="Final step: disburse after all approvals and signatures collected",
                    title="Disburse funds via QuickBooks",
                    priority="high",
                    due_offset_days=5,  # 120h ÷ 24
                    assigned_to_role="paralegal",
                    task_type="disburse_funds",
                    order=4,
                ),
            ],
            "automated_steps": [
                AutomatedStepConfig(
                    step_id="calculate_fees",
                    display_name="Attorney Fee Calculation",
                    description=(
                        "Calculates the attorney fee as a percentage of the gross award amount. "
                        "This percentage is applied to every settlement calculation."
                    ),
                    is_condition=False,
                    parameter_schema=[
                        ParameterDefinition(
                            name="default_attorney_fee_percent",
                            label="Default Attorney Fee (%)",
                            description=(
                                "Default attorney fee as a percentage of the gross award. "
                                "Applied when no case-specific fee has been set. "
                                "Typical Zadroga Act fee is 33.33%."
                            ),
                            type="percent",
                            default_value=33.33,
                            min_value=0.0,
                            max_value=40.0,
                        ),
                    ],
                    parameters={
                        "default_attorney_fee_percent": 33.33,
                    },
                ),
            ],
            "event_triggers": [
                EventTriggerConfig(
                    event_type="award_letter.received",
                    arguments_mapping={
                        "case_id": "data.case_id",
                        "award_amount": "data.award_amount",
                    },
                    description="Auto-triggered when an award letter is uploaded and processed",
                ),
            ],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "created_by": "system",
        },
    }
