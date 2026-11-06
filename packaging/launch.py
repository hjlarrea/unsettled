"""Entry point for the desktop bundle, preserving package-relative imports."""
import os
import sys

# Windowed Windows executables have no standard streams. Some libraries still
# write diagnostics to them, so supply file-like sinks before importing the app.
for name in ("stdout", "stderr"):
    if getattr(sys, name) is None:
        setattr(sys, name, open(os.devnull, "w"))

from unsettled.__main__ import main

if __name__ == "__main__":
    main()
