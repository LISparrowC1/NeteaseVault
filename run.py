"""Entry point for the frozen build.

PyInstaller executes its entry script as __main__ without a package context, so the
application has to be started from outside the package. Running this file directly
also works for development.
"""
from __future__ import annotations

import sys

from app.main import main

if __name__ == "__main__":
    sys.exit(main())
