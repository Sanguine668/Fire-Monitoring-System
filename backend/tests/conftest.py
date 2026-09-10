import os
import tempfile
from pathlib import Path

tmp = tempfile.mkdtemp(prefix="fireguard-test-")
os.environ["FIREGUARD_DB"] = str(Path(tmp) / "test.db")
