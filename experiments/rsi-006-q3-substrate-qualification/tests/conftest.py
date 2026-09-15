import sys
from pathlib import Path

# Make the Q3 stage modules importable regardless of the pytest invocation
# directory: CI runs pytest from the repository root, where the experiment
# directory is not on sys.path. conftest.py is imported before any test
# module is collected, so this runs before `import env_qualify` et al.
_EXP_DIR = str(Path(__file__).resolve().parent.parent)
if _EXP_DIR not in sys.path:
    sys.path.insert(0, _EXP_DIR)

collect_ignore = ["fixtures"]
