import sys
import os
from pathlib import Path

# /var/task/ is the Vercel bundle root; backend/ is included via includeFiles
ROOT = Path(__file__).resolve().parent.parent  # /var/task
BACKEND = ROOT / "backend"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BACKEND))

# Tell data.py where the datasets folder lives
os.environ.setdefault("NODAL_ROOT", str(BACKEND))

from app.main import app  # noqa: E402  (imported after path setup)
