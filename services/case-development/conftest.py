import sys
import os

# Add repo root to path so `shared` package is importable during local test runs.
# In Cloud Build / Docker the package is installed explicitly before pytest runs.
_repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

sys.path.insert(0, os.path.dirname(__file__))
