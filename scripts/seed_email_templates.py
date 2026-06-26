"""
seed_email_templates.py — Create email notification templates in Firestore.

Run once:
    python scripts/seed_email_templates.py
"""
import os
from google.cloud import firestore

db = firestore.Client(
    project=os.environ["GCP_PROJECT_ID"],
    database=os.environ.get("FIRESTORE_DATABASE_ID", "simpletort-dev"),
)
collection = db.collection("notificationTemplates")

templates = [
    {
        "id": "welcome_email",
        "data": {
            "name": "Welcome Email",
            "channel": "EMAIL",
            "triggerEvent": "new_lead_created",
            "isActive": True,
            "subject": "Welcome to {{firmName}}, {{clientName}} — Your Case {{caseId}}",
            "htmlBody": """<html>
<body style="font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: 0 auto;">
  <h2 style="color: #1a3c6e;">Welcome to {{firmName}}</h2>
  <p>Dear {{clientName}},</p>
  <p>Thank you for choosing {{firmName}}. We have received your case and our team is ready to assist you.</p>
  <p><strong>Case ID:</strong> {{caseId}}</p>
  <p>Your dedicated attorney will be in touch shortly to discuss the next steps in your case.</p>
  <p>If you have any immediate questions, please don't hesitate to reach out to us.</p>
  <br>
  <p>Warm regards,<br><strong>The {{firmName}} Team</strong></p>
</body>
</html>""",
            "body": "Dear {{clientName}}, welcome to {{firmName}}. Your case {{caseId}} has been received and our team will be in touch shortly.",
        },
    },
    {
        "id": "document_reminder_48hr_email",
        "data": {
            "name": "48-Hour Document Reminder Email",
            "channel": "EMAIL",
            "triggerEvent": "document_reminder_48hr",
            "isActive": True,
            "subject": "Action Required: Documents Needed for Case {{caseId}} — Deadline in 48 Hours",
            "htmlBody": """<html>
<body style="font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: 0 auto;">
  <h2 style="color: #c0392b;">Action Required — Documents Due Soon</h2>
  <p>Dear {{clientName}},</p>
  <p>This is a reminder that we are still waiting for the following documents for your case <strong>{{caseId}}</strong>:</p>
  <div style="background:#f8f8f8; padding:12px; border-left:4px solid #c0392b; margin:16px 0;">
    {{missingDocsList}}
  </div>
  <p><strong>Deadline: {{deadlineLabel}}</strong></p>
  <p>Please upload your documents as soon as possible using your client portal:</p>
  <p><a href="{{portalUrl}}" style="background:#1a3c6e; color:white; padding:10px 20px; text-decoration:none; border-radius:4px; display:inline-block;">Upload Documents Now</a></p>
  <p>If you have already uploaded your documents, please disregard this message.</p>
  <br>
  <p>Thank you,<br><strong>The {{firmName}} Team</strong></p>
</body>
</html>""",
            "body": "Dear {{clientName}}, this is a reminder that documents are still needed for case {{caseId}}. Deadline: {{deadlineLabel}}. Upload at: {{portalUrl}}",
        },
    },
    {
        "id": "document_reminder_7day_email",
        "data": {
            "name": "7-Day Document Reminder Email",
            "channel": "EMAIL",
            "triggerEvent": "document_reminder_7day",
            "isActive": True,
            "subject": "Final Reminder: Documents Still Needed for Case {{caseId}}",
            "htmlBody": """<html>
<body style="font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: 0 auto;">
  <h2 style="color: #c0392b;">Final Reminder — Documents Still Required</h2>
  <p>Dear {{clientName}},</p>
  <p>We have not yet received all required documents for your case <strong>{{caseId}}</strong>. Without these documents, we may be unable to proceed with your case.</p>
  <p>Outstanding documents:</p>
  <div style="background:#f8f8f8; padding:12px; border-left:4px solid #c0392b; margin:16px 0;">
    {{missingDocsList}}
  </div>
  <p>Please upload your documents immediately using your client portal:</p>
  <p><a href="{{portalUrl}}" style="background:#c0392b; color:white; padding:10px 20px; text-decoration:none; border-radius:4px; display:inline-block;">Upload Documents Now</a></p>
  <p>If you need assistance, please contact our office directly.</p>
  <br>
  <p>Thank you,<br><strong>The {{firmName}} Team</strong></p>
</body>
</html>""",
            "body": "Dear {{clientName}}, this is your final reminder. Documents are still needed for case {{caseId}}. Please upload immediately at: {{portalUrl}}",
        },
    },
]

for t in templates:
    doc_ref = collection.document(t["id"])
    doc_ref.set({**t["data"], "templateId": t["id"]}, merge=True)
    print(f"Created/updated template: {t['id']}")

print("\nDone! Templates created in notificationTemplates collection.")
