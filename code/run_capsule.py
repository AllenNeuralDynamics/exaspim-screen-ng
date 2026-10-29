"""Code Ocean entry point; logic lives in the ``exaspim_screen_ng`` package.

The package sits beside this file in the capsule's ``code`` folder, so it is
present in every run: capsule, pipeline and interactive session. This file's own
directory is put at the front of ``sys.path`` so that package is imported ahead
of any copy installed into the image, which only supplies the dependencies.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from exaspim_screen_ng.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
