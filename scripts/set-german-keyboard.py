#!/usr/bin/env python3
"""Use Omarchy's installed keyboard handler in the logged-in desktop session."""
import importlib.util
import os
from pathlib import Path
import sys

if os.geteuid() == 0:
    sys.exit('Als normaler Benutzer in der Omarchy-Desktopsitzung ausführen.')
path = Path('/usr/share/omarchy/default/input-methods/typing_setup.py')
sys.path.insert(0, str(path.parent))
spec = importlib.util.spec_from_file_location('typing_setup', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.save_keyboard(['de'])
