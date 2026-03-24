import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Prevent Firebase/Firestore init during import
os.environ.setdefault("GCP_PROJECT_ID", "test-project")
os.environ.setdefault("ENVIRONMENT", "test")
