"""Long scan progress always goes to stderr, including callers with JSON stdout."""
import sys
import threading
import time
from contextlib import contextmanager


class Progress:
    MIN_SECONDS = 2

    def __init__(self):
        self.started = time.monotonic()
        self.last_file = 0

    def emit(self, message):
        elapsed = time.monotonic() - self.started
        if elapsed >= self.MIN_SECONDS:
            print(f"[scan {elapsed:.1f}s] {message}", file=sys.stderr, flush=True)

    @contextmanager
    def phase(self, name):
        start = time.monotonic()
        self.emit(name)
        stopped = threading.Event()

        def heartbeat():
            while not stopped.wait(2):
                self.emit(f"{name} in progress")

        worker = threading.Thread(target=heartbeat, daemon=True)
        worker.start()
        try:
            yield
        finally:
            stopped.set()
            worker.join()
            self.emit(f"{name} finished in {time.monotonic() - start:.1f}s")

    def file(self, phase, index, total, path):
        now = time.monotonic()
        if index == 1 or index == total or now - self.last_file >= 2:
            self.emit(f"{phase} {index}/{total}: {path}")
            self.last_file = now
