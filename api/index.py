import sys
from pathlib import Path

# Add project root and backend to python path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from backend.app.main import app
