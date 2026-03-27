import sys
import os

# Add the project root to sys.path so pytest can find the 'app' package
# regardless of which directory pytest is invoked from.
sys.path.insert(0, os.path.dirname(__file__))
