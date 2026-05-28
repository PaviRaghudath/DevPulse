"""Memory monitoring and garbage collection helpers."""
import gc
import os

try:
    import psutil
    _PSUTIL_AVAILABLE = True
except ImportError:
    _PSUTIL_AVAILABLE = False

from src.config import MEMORY_WARN_MB


def current_usage_mb() -> float:
    """Return current process RSS in MB, or 0 if psutil is unavailable."""
    if not _PSUTIL_AVAILABLE:
        return 0.0
    return psutil.Process(os.getpid()).memory_info().rss / (1024 ** 2)


def check_and_warn(console=None) -> None:
    """Print a warning if memory usage exceeds MEMORY_WARN_MB."""
    usage = current_usage_mb()
    if usage > MEMORY_WARN_MB:
        msg = f"[yellow]Warning: Memory usage is {usage:.0f} MB[/yellow]"
        if console:
            console.print(msg)
        else:
            print(f"Warning: Memory usage is {usage:.0f} MB")


def force_gc() -> None:
    """Force a full garbage collection cycle."""
    gc.collect()
