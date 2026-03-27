import sys
import os

# Allow imports of assigner, notifier, main from the function root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Provide a dummy GCP_PROJECT_ID so main.py module-level code doesn't raise
os.environ.setdefault("GCP_PROJECT_ID", "test-project")
