import os
from pathlib import Path
from dotenv import load_dotenv
envpath=Path(__file__).parent
load_dotenv(envpath / ".env")

class Config:
    PROJECT_ID=os.getenv("FIREBASE_PROJECT_ID")
    DATABASE_ID=os.getenv("FIRESTORE_DATABASE_ID")
    REGION=os.getenv("REGION")
    ALLOWED_ORIGIN=os.getenv("ALLOWED_ORIGIN")
    STAFF_COL=os.getenv("FIRESTORE_STAFF_COLLECTION")
    CASE_COL=os.getenv("FIRESTORE_CASE_COLLECTION")
    RATE_LIMIT=os.getenv("FIRESTORE_RATE_LIMITS_COLLECTION")
    PORTAL_INVITES=os.getenv("FIRESTORE_PORTAL_INVITES_COLLECTION")
    SESSIONS=os.getenv("FIRESTORE_SESSIONS_COLLECTION")
    FIRM_SETTINGS=os.getenv("FIRESTORE_FIRM_SETTING_COLLECTION")
    AUDIT_LOGS=os.getenv("FIRESTORE_AUDIT_LOGS_COLLECTION")