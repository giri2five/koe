"""Koe entry point.

Run with: python -m koe
Or after install: koe
"""

import logging
import os
import sys
import threading
import tempfile
import time
import ctypes
from datetime import datetime
from pathlib import Path

_INSTANCE_MUTEX = None


def _acquire_single_instance() -> bool:
    """Ensure only one Koe app instance owns the runtime."""
    if sys.platform != "win32":
        return True

    global _INSTANCE_MUTEX
    kernel32 = ctypes.windll.kernel32
    mutex = kernel32.CreateMutexW(None, False, "Local\\KoeAppSingleInstance")
    if not mutex:
        return True
    _INSTANCE_MUTEX = mutex
    return kernel32.GetLastError() != 183

def _hide_stray_launcher_windows():
    """Hide Windows Terminal windows that incorrectly attach to Koe launch."""
    if sys.platform != "win32":
        return

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    repo_root = Path(__file__).resolve().parents[1]
    exe_markers = [
        str((repo_root / ".venv" / "Scripts" / "pythonw.exe")).lower(),
        str((repo_root / ".venv" / "Scripts" / "koe-gui.exe")).lower(),
    ]
    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    def _image_path_for_hwnd(hwnd) -> str:
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not handle:
            return ""
        try:
            size = ctypes.c_ulong(1024)
            buffer = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return buffer.value.lower()
        finally:
            kernel32.CloseHandle(handle)
        return ""

    def worker():
        def callback(hwnd, lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value.strip().lower()
            image_path = _image_path_for_hwnd(hwnd)
            if "windowsterminal.exe" in image_path and (
                any(marker in title for marker in exe_markers) or not title
            ):
                user32.ShowWindow(hwnd, 0)
            return True

        for _ in range(10):
            try:
                user32.EnumWindows(enum_proc(callback), 0)
            except Exception:
                pass
            time.sleep(0.6)

    threading.Thread(target=worker, daemon=True, name="koe-hide-launcher").start()

def _run_file_transcription(path: str, model: str | None = None, skip_clean: bool = False) -> None:
    """Transcribe an audio or video file and print cleaned text to stdout."""
    from pathlib import Path as _Path
    import sys as _sys

    src = _Path(path)
    if not src.exists():
        print(f"koe: file not found: {path}", file=_sys.stderr)
        _sys.exit(1)

    # Minimal logging — only errors to stderr
    import logging as _logging
    _logging.basicConfig(level=_logging.ERROR, format="%(message)s")

    from koe.config import load_config
    from koe.transcriber import Transcriber
    from koe.cleaner import TextCleaner

    config = load_config()
    if model:
        config.transcription.model = model

    print(f"Loading model '{config.transcription.model}'…", file=_sys.stderr)
    transcriber = Transcriber(config.transcription)

    print(f"Transcribing {src.name}…", file=_sys.stderr)
    try:
        # faster-whisper accepts file paths directly
        text = transcriber.transcribe_file(str(src))
    except Exception as exc:
        print(f"koe: transcription failed: {exc}", file=_sys.stderr)
        _sys.exit(1)

    if not text:
        print("koe: no speech detected", file=_sys.stderr)
        _sys.exit(0)

    if not skip_clean:
        cleaner = TextCleaner(config.cleanup)
        text = cleaner.clean(text)

    print(text)
    transcriber.unload()


def main():
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    os.chdir(Path(__file__).resolve().parents[1])

    import argparse
    parser = argparse.ArgumentParser(prog="koe", add_help=True)
    parser.add_argument("--file", metavar="PATH", help="Transcribe an audio file and print the result")
    parser.add_argument("--model", default=None, metavar="MODEL", help="Whisper model to use (default: from config)")
    parser.add_argument("--no-clean", action="store_true", help="Skip text cleanup")
    args, _ = parser.parse_known_args()

    if args.file:
        _run_file_transcription(args.file, model=args.model, skip_clean=args.no_clean)
        return

    if not _acquire_single_instance():
        return

    _hide_stray_launcher_windows()

    # Set up logging
    log_dir = Path.home() / ".koe"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "koe.log"

    handlers: list[logging.Handler] = []
    try:
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))
    except OSError:
        fallback_dir = Path(tempfile.gettempdir()) / "koe-logs"
        fallback_dir.mkdir(parents=True, exist_ok=True)
        fallback_path = fallback_dir / f"koe-{datetime.now():%Y%m%d-%H%M%S}.log"
        handlers.append(logging.FileHandler(fallback_path, encoding="utf-8"))
    if sys.stdout is not None and sys.stdout is not sys.__stdout__:
        handlers.append(logging.StreamHandler())

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=handlers,
    )

    def _log_unhandled(exc_type, exc_value, exc_traceback):
        logging.getLogger("koe").error(
            "Unhandled exception",
            exc_info=(exc_type, exc_value, exc_traceback),
        )

    def _log_thread_exception(args: threading.ExceptHookArgs):
        logging.getLogger("koe").error(
            "Unhandled thread exception in %s",
            args.thread.name if args.thread is not None else "unknown",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = _log_unhandled
    threading.excepthook = _log_thread_exception

    # Check platform
    if sys.platform != "win32":
        print("Koe is currently Windows-only. macOS/Linux support coming later.")
        sys.exit(1)

    from koe.app import KoeApp

    _first_run = not (Path.home() / ".koe" / "config.toml").exists()
    app = KoeApp()
    if _first_run:
        import threading as _t
        import time as _time
        def _notify():
            _time.sleep(2)  # wait for tray icon to appear
            try:
                if app._tray_icon:
                    app._tray_icon.notify(
                        "Hold Alt + K to start speaking. Text appears in any app.",
                        "Koe is ready"
                    )
            except Exception:
                pass
        _t.Thread(target=_notify, daemon=True, name="koe-onboard").start()
    try:
        app.run()
    except KeyboardInterrupt:
        app._shutdown()


if __name__ == "__main__":
    main()
