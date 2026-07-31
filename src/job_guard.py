"""Guards for scheduled local jobs: console kill resistance + exclusive run locks."""
from __future__ import annotations

import atexit
import logging
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from src.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

_LOCK_DIR = PROJECT_ROOT / "data" / "locks"
_handler_ref = None  # keep ctypes callback alive


def scheduled_mode() -> bool:
    return os.environ.get("TMM_SCHEDULED", "").strip().lower() in ("1", "true", "yes")


def install_console_guard() -> None:
    """Ignore Ctrl+C / Ctrl+Break / console-close while a scheduled job runs.

    Interactive Task Scheduler jobs attach a console; closing that window sends
    CTRL_CLOSE_EVENT (seen as exit -1073741510 / STATUS_CONTROL_C_EXIT).
    Hidden launchers avoid most cases; this is a second line of defense.
    """
    if sys.platform == "win32":
        _install_windows_console_handler()
    else:
        import signal

        signal.signal(signal.SIGINT, signal.SIG_IGN)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, signal.SIG_IGN)


def _install_windows_console_handler() -> None:
    global _handler_ref
    import ctypes
    from ctypes import wintypes

    HandlerRoutine = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

    @HandlerRoutine
    def _handler(ctrl_type: int) -> bool:
        # 0 CTRL_C, 1 CTRL_BREAK, 2 CTRL_CLOSE, 5 CTRL_LOGOFF, 6 CTRL_SHUTDOWN
        if ctrl_type in (0, 1, 2, 5):
            logger.warning(
                "Ignoring console control event %s (scheduled job continues)",
                ctrl_type,
            )
            return True
        return False

    _handler_ref = _handler
    if not ctypes.windll.kernel32.SetConsoleCtrlHandler(_handler, True):
        logger.warning("SetConsoleCtrlHandler failed; console close may still kill the job")


def maybe_install_scheduled_guards() -> None:
    if scheduled_mode():
        install_console_guard()


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return exit_code.value == STILL_ACTIVE
            return True
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def is_lock_held(name: str, *, stale_after_sec: int = 6 * 3600) -> bool:
    """True when another live process holds ``name`` (stale locks ignored)."""
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    path = _LOCK_DIR / f"{safe}.lock"
    if not path.exists():
        return False
    try:
        parts = path.read_text(encoding="utf-8").strip().split()
        pid = int(parts[0])
        started = float(parts[1]) if len(parts) > 1 else 0.0
    except (OSError, ValueError):
        return False
    age = time.time() - started if started else stale_after_sec + 1
    return _pid_is_running(pid) and age < stale_after_sec


class RunLock:
    """PID file lock with stale takeover when the holder process is gone."""

    def __init__(self, name: str, *, stale_after_sec: int = 6 * 3600) -> None:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        self.path = _LOCK_DIR / f"{safe}.lock"
        self.stale_after_sec = stale_after_sec
        self._held = False

    def acquire(self, *, block: bool = False, timeout_sec: float = 0) -> bool:
        _LOCK_DIR.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + max(0.0, timeout_sec)
        while True:
            if self._try_acquire():
                return True
            if not block:
                return False
            if timeout_sec and time.monotonic() >= deadline:
                return False
            time.sleep(5.0)

    def _try_acquire(self) -> bool:
        if self.path.exists():
            try:
                raw = self.path.read_text(encoding="utf-8").strip()
                parts = raw.split()
                pid = int(parts[0])
                started = float(parts[1]) if len(parts) > 1 else 0.0
            except (OSError, ValueError):
                pid, started = 0, 0.0

            age = time.time() - started if started else self.stale_after_sec + 1
            if _pid_is_running(pid) and age < self.stale_after_sec:
                logger.info(
                    "Lock %s held by pid=%s (age=%.0fs) — skip",
                    self.path.name,
                    pid,
                    age,
                )
                return False
            logger.warning(
                "Taking over stale lock %s (pid=%s age=%.0fs)",
                self.path.name,
                pid,
                age,
            )
            try:
                self.path.unlink()
            except OSError:
                pass

        try:
            fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        try:
            os.write(fd, f"{os.getpid()} {time.time():.3f}\n".encode("utf-8"))
        finally:
            os.close(fd)
        self._held = True
        atexit.register(self.release)
        return True

    def release(self) -> None:
        if not self._held:
            return
        self._held = False
        try:
            if self.path.exists():
                raw = self.path.read_text(encoding="utf-8").strip().split()
                if raw and int(raw[0]) == os.getpid():
                    self.path.unlink()
        except (OSError, ValueError):
            pass


@contextmanager
def pipeline_lock(
    name: str = "pipeline",
    *,
    block: bool = False,
    timeout_sec: float = 0,
) -> Iterator[bool]:
    """Yield True if lock acquired; False if skipped (caller should no-op)."""
    maybe_install_scheduled_guards()
    lock = RunLock(name)
    acquired = lock.acquire(block=block, timeout_sec=timeout_sec)
    try:
        yield acquired
    finally:
        if acquired:
            lock.release()


def monthly_report_path(year: int, month: int) -> Path:
    from src.config import load_settings

    settings = load_settings()
    return Path(settings.reports_output_dir) / f"monthly_{year:04d}-{month:02d}.md"
