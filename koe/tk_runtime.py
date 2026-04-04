"""Helpers for making Tkinter work reliably in Koe's Windows runtimes."""

from __future__ import annotations

import os
from pathlib import Path
import sys


def ensure_tk_runtime():
    """Point Tkinter at a usable bundled Tcl/Tk runtime when needed."""
    repo_root = Path(__file__).resolve().parents[1]
    candidates = [
        Path(sys.base_prefix) / "tcl",
        Path(sys.exec_prefix) / "tcl",
        repo_root / ".uv-python" / "cpython-3.11.15-windows-x86_64-none" / "tcl",
        repo_root / ".uv-python" / "cpython-3.11-windows-x86_64-none" / "tcl",
        Path(os.environ.get("PYTHONHOME", "")) / "tcl",
    ]

    for tcl_root in candidates:
        tcl_dir = tcl_root / "tcl8.6"
        tk_dir = tcl_root / "tk8.6"
        if tcl_dir.joinpath("init.tcl").exists() and tk_dir.exists():
            os.environ["TCL_LIBRARY"] = str(tcl_dir)
            os.environ["TK_LIBRARY"] = str(tk_dir)
            dll_dir = tcl_root.parent / "DLLs"
            path_parts = [str(tcl_root.parent), str(dll_dir), os.environ.get("PATH", "")]
            os.environ["PATH"] = os.pathsep.join(part for part in path_parts if part)
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(str(tcl_root.parent))
                    if dll_dir.exists():
                        os.add_dll_directory(str(dll_dir))
                except OSError:
                    pass
            return
