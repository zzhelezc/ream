"""Allow `python -m ream` from a source checkout."""
import sys

from .app import main

if __name__ == "__main__":
    sys.exit(main())
