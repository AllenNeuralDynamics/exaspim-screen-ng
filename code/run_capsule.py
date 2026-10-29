"""Code Ocean entry point; logic lives in the ``exaspim_screen_ng`` package.

The capsule's own ``src`` directory is put ahead of ``sys.path`` so a run always
executes the code committed to this capsule, not the copy installed into the
image. The installed copy still supplies the third-party dependencies.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from exaspim_screen_ng.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
