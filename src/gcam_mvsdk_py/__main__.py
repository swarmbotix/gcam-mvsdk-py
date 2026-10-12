"""Allow ``python -m gcam_mvsdk_py <command>``."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
