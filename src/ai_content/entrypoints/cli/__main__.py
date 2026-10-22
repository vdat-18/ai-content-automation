"""Allow `python -m ai_content.entrypoints.cli`."""

from .main import main

if __name__ == "__main__":
    raise SystemExit(main())
