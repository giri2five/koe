"""Repo-pinned launcher for Koe.

Ensures the app boots from the current source tree instead of any stale
editable-install resolution path.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main():
    repo_root = Path(__file__).resolve().parent
    root_str = str(repo_root)
    if sys.path[0] != root_str:
        sys.path.insert(0, root_str)

    from koe.__main__ import main as koe_main

    koe_main()


if __name__ == "__main__":
    main()
