"""Allow `python -m ai_content.entrypoints.cli`."""

import sys

from .main import main

if __name__ == "__main__":
    sys.exit(main())
