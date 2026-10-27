"""JSON-lines event channel between the Python core and the CrowSplat app.

The app reads one JSON object per line on the process's stdout. Everything
else the core prints (engine logs, COLMAP and Brush output, installer chatter)
must not corrupt that stream, so ``open_channel`` moves the real stdout aside
and points file descriptor 1 at stderr: prints and child processes then land
in stderr, which the app shows as the raw log.

Event shapes (all carry ``"type"``):

    step      {"id", "label", "index", "count"}   a new stage of the job begins
    progress  {"step", "value"}                    0-100 within the current step
    eta       {"step", "seconds"}                  seconds left, -1 = unknown
    status    {"text"}                             short human line ("image 12/40")
    log       {"text", "level"}                    a log line worth keeping
    artifact  {"kind", "path"}                     a file the job produced
    done      {"ok", "message", "result"}          always the last event
"""

import json
import os
import sys
import threading
import time


class Channel:
    def __init__(self, stream):
        self._stream = stream
        self._lock = threading.Lock()
        self.step: str | None = None

    def emit(self, type_: str, **fields) -> None:
        fields["type"] = type_
        fields.setdefault("t", round(time.time(), 3))
        line = json.dumps(fields, ensure_ascii=False, default=str)
        with self._lock:
            self._stream.write(line + "\n")
            self._stream.flush()

    # Shorthands used by the jobs
    def begin(self, step_id: str, label: str, index: int, count: int) -> None:
        self.step = step_id
        self.emit("step", id=step_id, label=label, index=index, count=count)

    def progress(self, value: float) -> None:
        self.emit("progress", step=self.step, value=round(float(value), 2))

    def eta(self, seconds: float | None) -> None:
        self.emit("eta", step=self.step, seconds=-1 if seconds is None else round(seconds, 1))

    def status(self, text: str) -> None:
        self.emit("status", text=str(text))

    def log(self, text: str, level: str = "info") -> None:
        self.emit("log", text=str(text), level=level)

    def artifact(self, kind: str, path) -> None:
        self.emit("artifact", kind=kind, path=str(path))

    def done(self, ok: bool, message: str = "", **result) -> None:
        self.emit("done", ok=bool(ok), message=message, result=result)


def open_channel() -> Channel:
    """Claim the real stdout for events and send fd 1 to stderr."""
    sys.stdout.flush()
    events_fd = os.dup(1)
    os.dup2(2, 1)
    # Line-buffered text stream on the saved descriptor.
    stream = os.fdopen(events_fd, "w", buffering=1, encoding="utf-8")
    sys.stdout = sys.stderr
    return Channel(stream)
