"""Double-click this file to open the GUI with its isolated environment."""
import os
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
venv = root / ".venv" / "Scripts" / "pythonw.exe"
if os.name == "nt" and venv.is_file() and Path(sys.executable).resolve() != venv.resolve():
    subprocess.Popen([str(venv), str(root / "gui.py")], cwd=root, creationflags=subprocess.CREATE_NO_WINDOW)
    raise SystemExit(0)

from gui import main

main()
