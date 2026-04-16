import os
from pathlib import Path
from dotenv import load_dotenv
envpath=Path(__file__).parent
load_dotenv(envpath / ".env")

class Config:
    PROJECT_ID=os.getenv("FIREBASE_PROJECT_ID")
    DATABASE_ID="simpletort-dev"
