"""Shared atomic JSON helpers (no Qt, no project imports -> no import cycles)."""

import contextlib
import json
import os
import tempfile
from pathlib import Path


def read_json_dict(path) -> dict:
    """Return the JSON object stored in ``path``; {} if missing/invalid/non-dict."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_json_atomic(path, data) -> None:
    """Write ``data`` as JSON via a temp file in the same directory + os.replace."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def update_json_file(path, **changes) -> dict:
    """Read-modify-write ``path`` atomically, preserving other keys."""
    config = read_json_dict(path)
    config.update(changes)
    write_json_atomic(path, config)
    return config
