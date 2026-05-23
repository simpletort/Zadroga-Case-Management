import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

# Make the shared package importable when running tests locally
_shared_path = os.path.join(os.path.dirname(__file__), "..", "..", "shared")
if os.path.isdir(_shared_path):
    sys.path.insert(0, os.path.abspath(_shared_path))
